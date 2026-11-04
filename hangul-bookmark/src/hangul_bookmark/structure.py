"""Checked structural edits on Hancom's native object model.

The model is a precondition, not a document writer. Each native operation has
an independent expected result; only the transaction layer can publish a file.
"""
from collections import Counter
import copy
import hashlib
import math
from pathlib import Path
import tempfile

from . import content, document as dm, xmlcheck
from .errors import WriterError

KINDS = frozenset({
    'insert_at', 'replace_range', 'delete_range', 'delete_object',
    'copy_range', 'move_range', 'insert_table', 'table_change', 'table_format',
    'set_character', 'set_paragraph', 'set_page', 'insert_break', 'region_edit', 'set_picture', 'crop_picture', 'caption_picture',
})
LEGACY = frozenset({'replace_text', 'replace_equation', 'set_format', 'insert_blocks'})
OBJECTS = {'equation': 'eqed', 'PICTURE': 'gso', 'TABLE': 'tbl'}


def invalid(message):
    dm.fail('INVALID_EDIT', message)


def check(ok, message):
    if not ok:
        dm.fail('HANCOM_FAILED', message)


def verify(ok, message):
    if not ok:
        dm.fail('VERIFY_FAILED', message)


def positive(value, limit, label):
    if type(value) is not int or not 1 <= value <= limit:
        invalid(f'{label}은(는) 1~{limit} 정수여야 합니다.')
    return value


def optional_target(doc, key):
    if not isinstance(key, str) or key not in doc['targets']:
        dm.fail('TARGET_MISSING', '이번 문서 분석에서 반환된 대상 ID가 필요합니다.')
    return key


def part_at(p, entry):
    return next((a for a in p['parts'] if a['start'] == entry['start'] and a['end'] == entry['end']), None)


def object_type(part):
    if not part:
        return None
    return 'equation' if part['kind'] == 'equation' else part.get('type')


def range_for(doc, target, point=None, objects=False):
    entries = dm.expand(doc, optional_target(doc, target))
    if not entries:
        invalid('선택 범위가 비어 있습니다.')
    entries = sorted(entries, key=lambda e:(e['paragraph'], e['start']))
    if point is not None:
        if len(entries) != 1 or point not in ('before', 'after'):
            invalid('삽입 위치는 단일 대상의 before 또는 after입니다.')
        e=entries[0];p=doc['paragraphs'][e['paragraph']]
        pos=e['start' if point=='before' else 'end']
        entries=[dict(e,start=pos,end=pos)]
    paras = doc['paragraphs']
    first,last = entries[0]['paragraph'],entries[-1]['paragraph']
    if [e['paragraph'] for e in entries] != list(range(first,last+1)):
        invalid('하나의 연속된 범위만 편집할 수 있습니다.')
    parent = paras[first]['path'].rsplit('/',1)[0]
    for i,e in enumerate(entries):
        p = paras[e['paragraph']]
        if p['scope']=='excluded' or not p.get('mapped') or p['path'].rsplit('/',1)[0]!=parent:
            dm.fail('UNMAPPED_LOCATION','같은 본문 구역 또는 같은 셀 안의 검증된 위치만 편집할 수 있습니다.')
        lo,hi=e['start'],e['end']
        if not 0<=lo<=hi<=p['length'] or (i and lo!=0) or (i<len(entries)-1 and hi!=p['length']):
            invalid('연속된 문단 범위가 아닙니다.')
        atoms=[a for a in dm.atoms(p) if a['kind']!='empty']
        boundaries={0,p['length']} | {a[k] for a in atoms for k in ('start','end')}
        if lo not in boundaries or hi not in boundaries:
            invalid('문자 또는 개체 중간에는 삽입하거나 삭제할 수 없습니다.')
        for a in atoms:
            if a['start']<hi and lo<a['end'] and a['kind']!='text':
                if not objects or object_type(a) not in ('equation','PICTURE'):
                    dm.fail('PROTECTED_RANGE','범위에 개체 또는 구조 표시가 있습니다. 편집할 개체를 따로 지정하세요.')
    return first,entries[0]['start'],last,entries[-1]['end']


def normalize_blocks(blocks):
    blocks=content.normalize(blocks)
    if any(b['type']=='text' and any(ord(c)<32 for c in b['text']) for b in blocks):
        invalid('본문에는 제어 문자를 넣을 수 없습니다. 줄바꿈은 문단 나누기를 사용하세요.')
    return blocks


def compile_batch(doc, edits):
    steps=[]
    for edit in edits:
        if not isinstance(edit,dict) or edit.get('type') not in KINDS | LEGACY:
            invalid('지원하지 않는 편집 종류입니다.')
        e=copy.deepcopy(edit);kind=e['type']
        if e.get('uncertain'):
            dm.fail('UNCERTAIN_CONTENT','대상 또는 입력 내용을 확인하세요.')
        optional_target(doc,e.get('target_id'))
        if kind in ('insert_at','insert_table'):
            e.setdefault('position','after')
            range_for(doc,e['target_id'],e['position'])
        elif kind in ('replace_range','delete_range','copy_range','move_range'):
            span=range_for(doc,e['target_id'],objects=True)
            if span[:2]==span[2:]:
                invalid('편집할 내용이나 문단 경계가 필요합니다.')
            if kind in ('copy_range','move_range'):
                e.setdefault('position','after')
                target=range_for(doc,e.get('destination_id'),e['position'])
                if span[:2]<=target[:2]<=span[2:]:
                    invalid('원본 범위 내부로 복사하거나 이동할 수 없습니다.')
        elif kind=='delete_object':
            es=dm.expand(doc,e['target_id'])
            if len(es)!=1 or doc['targets'][e['target_id']]['kind'] not in ('control','equation'):
                invalid('삭제할 개체 하나를 지정하세요.')
            p=doc['paragraphs'][es[0]['paragraph']]
            if not p.get('mapped') or p['scope']=='excluded' or object_type(part_at(p,es[0])) not in OBJECTS:
                invalid('삭제할 수식·사진·표 개체의 ID를 지정하세요.')
        if kind in ('set_character','set_paragraph','set_page','insert_break'):
            from .format_edit import validate
            validate(doc,e)
        if kind in ('set_picture','crop_picture','caption_picture'):
            from .picture_edit import validate
            validate(doc,e)
        if kind=='region_edit':
            from .region_edit import validate
            validate(doc,e)
        if kind=='table_format':
            from .table_format import validate
            validate(doc,e)
        if kind=='table_change':
            from .table_edit import compile_change
            compile_change(doc,e)
        if kind in ('insert_at','replace_range'):
            e['blocks']=normalize_blocks(e.get('blocks'))
        if kind=='insert_table':
            rows=positive(e.get('rows'),100,'행 수');cols=positive(e.get('columns'),100,'열 수')
            if rows*cols>1000:
                invalid('한 표는 1,000셀 이내입니다.')
            cells=e.get('cells',[])
            if not isinstance(cells,list) or len(cells)>rows:
                invalid('cells에는 행별 셀 배열을 지정하세요.')
            normalized=[]
            for row in cells:
                if not isinstance(row,list) or len(row)>cols:
                    invalid('cells의 각 행에 열 수 이내의 셀을 지정하세요.')
                normalized.append([normalize_blocks(c) if c else [] for c in row])
            e['cells']=normalized
        steps.append(e)
    payloads=[e.get('blocks',[]) for e in steps]+[cell for e in steps if e['type']=='insert_table' for row in e['cells'] for cell in row]
    if sum(len(b.get('text',''))+len(b.get('script','')) for blocks in payloads for b in blocks)>200000 or sum(map(len,payloads))>2000:
        invalid('한 요청은 2,000블록·200,000자 이내여야 합니다.')
    return [{'type':'structural_batch','steps':steps}]


def select(h,doc,span):
    a,lo,b,hi=span;ps=doc['paragraphs']
    h.Cancel()
    start=(*ps[a]['native'],lo);end=(*ps[b]['native'],hi)
    if start==end:
        check(h.set_pos(*start),'지정한 삽입 위치로 이동하지 못했습니다.')
        verify(tuple(map(int,h.get_pos()))==start,'실제 삽입 위치가 다릅니다.')
    else:
        check(h.select_text_by_get_pos(start,end),'선택 범위를 만들지 못했습니다.')
        result=h.get_selected_pos()
        if not result[0] or {tuple(map(int,result[1:4])),tuple(map(int,result[4:7]))}!={start,end}:
            dm.fail('STALE_TARGET','실제 한글의 선택 범위가 요청과 다릅니다.')


def atoms(p):
    return [a for a in dm.atoms(p) if a['kind']!='empty']


def stable(value):
    """Ignore instance IDs and stacking numbers of inline objects."""
    if isinstance(value,dict):
        return {k:stable(v) for k,v in value.items() if k.lower() not in ('instid','instanceid')}
    if isinstance(value,list):
        if len(value)==4 and value[0]=='SHAPEOBJECT':
            pos=next((v for v in value[3] if v[0]=='POSITION'),None)
            if pos and pos[1].get('TreatAsChar')=='true':
                attrs={k:v for k,v in value[1].items() if k!='ZOrder'}
                return [value[0],stable(attrs),value[2],stable(value[3])]
        return [stable(v) for v in value]
    return value


def semantic(a):
    out=stable({k:v for k,v in a.items() if k not in ('id','start','end','image')})
    if a.get('type')=='PICTURE':
        out['image_bytes']=a['image'].get('asset_hash')
        def clean(item):
            if isinstance(item,list):
                for x in item:clean(x)
            elif isinstance(item,dict):
                item.pop('BinItem',None)
                for x in item.values():clean(x)
        clean(out)
    return out


def coords(p):
    return [x if 'table' not in x else {'table':True} for x in p['cell_path']]


def snapshot(p):
    attributes={k:v for k,v in p['attributes'].items() if k not in ('PageBreak','ColumnBreak') or v!='false'}
    return stable([p['scope'],coords(p),p['paragraph_shape'],p['style'],attributes,
                   [semantic(a) for a in dm.atoms(p)]])


def table_snapshot(doc):
    return stable(doc['table_structure'])


def full_snapshot(doc):
    return dm.digest([list(map(snapshot,doc['paragraphs'])),table_snapshot(doc),[stable(t.get('direct_geometry')) for t in doc['tables']],doc['bookmarks'],
                      doc.get('structure_metadata',[])])


def plain(a):
    if a['kind']=='text':
        return ('text',a['text'])
    if a['kind']=='equation':
        return ('equation',a['script'].strip())
    return (a.get('type'),None)


def lines_for(blocks,offset):
    lines=[[]]
    for b in blocks:
        if b['type']=='paragraph_break':
            lines.append([])
        elif b['type']=='equation' and b['display']=='block':
            if lines[-1] or (len(lines)==1 and offset):
                lines.append([])
            lines[-1].append(b)
            lines.append([])
        else:
            lines[-1].append(b)
    return lines


def tokens(line):
    result=[]
    for b in line:
        if b['type']=='text':
            result.extend(('text',c) for c in b['text'])
        elif b['type']=='equation':
            result.append(('equation',b['script'].strip()))
        elif b['type']=='image':
            result.append(('PICTURE',None))
        else:
            result.append(('TABLE',None))
    return result


def splice_result(before,after,span,lines,*,tables=True):
    a,lo,b,hi=span;old=before['paragraphs'];new=after['paragraphs'];n=len(lines)
    verify(len(new)==len(old)-(b-a+1)+n,'입력 대상 밖 문단 수가 달라졌습니다.')
    verify([snapshot(p) for p in old[:a]]==[snapshot(p) for p in new[:a]]
           and [snapshot(p) for p in old[b+1:]]==[snapshot(p) for p in new[a+n:]],
           '대상 밖 문단·서식·개체가 달라졌습니다.')
    verify(before['bookmarks']==after['bookmarks'],'기존 책갈피가 달라졌습니다.')
    if tables:
        verify(table_snapshot(before)==table_snapshot(after),'대상 밖 표 구조가 달라졌습니다.')
    verify(before.get('structure_metadata')==after.get('structure_metadata'),'쪽·검토 정보가 달라졌습니다.')
    prefix=[x for x in atoms(old[a]) if x['end']<=lo]
    suffix=[x for x in atoms(old[b]) if x['start']>=hi]
    for i,line in enumerate(lines):
        p=new[a+i];actual=atoms(p)
        head=prefix if i==0 else [];tail=suffix if i==n-1 else []
        verify(coords(p)==coords(old[a]) and p['scope']==old[a]['scope'],'삽입된 내용이 지정 영역을 벗어났습니다.')
        verify([plain(x) for x in actual]==[plain(x) for x in head]+tokens(line)+[plain(x) for x in tail],
               '지정한 위치의 글·수식·개체가 요청과 다릅니다.')
        verify(list(map(semantic,actual[:len(head)]))==list(map(semantic,head)) and
               (not tail or list(map(semantic,actual[-len(tail):]))==list(map(semantic,tail))),
               '편집 범위 옆 내용이나 서식이 달라졌습니다.')
        for block,atom in zip(expand_line(line),actual[len(head):len(actual)-len(tail)]):
            if block['type']=='image':
                verify(atom['image'].get('embedded') and atom['image'].get('asset_hash')==block.get('asset_hash'),
                       '삽입된 사진 데이터가 요청과 다릅니다.')


def expand_line(line):
    for b in line:
        if b['type']=='text':
            yield from ({'type':'text'} for _ in b['text'])
        else:
            yield b


def import_object_fragment(h,fragment,fmt):
    from .native_edit import controls
    start=tuple(map(int,h.get_pos()))
    before=controls(h)
    old=before.get(start)
    had_column=start in before and (old is None or old.CtrlID=='cold')
    check(h.set_text_file(fragment,fmt,'insertfile'),'내장 개체 조각을 삽입하지 못했습니다.')
    # Hancom can prepend a new column definition when importing into a
    # paragraph that starts with the object. Preserve any existing definition.
    added=controls(h).get(start)
    if not had_column and added is not None and added.CtrlID=='cold':
        end=tuple(map(int,h.get_pos()))
        check(h.delete_ctrl(added),'조각에 추가된 구역 제어를 제거하지 못했습니다.')
        if end[:2]==start[:2] and end[2]>=start[2]+8:
            check(h.set_pos(*end[:2],end[2]-8),'개체 뒤의 삽입 위치를 복원하지 못했습니다.')


def picture(hancom,block,directory):
    from PIL import Image
    h=hancom.hwp
    target=Path(directory)/'picture.png'
    with Image.open(block['path']) as im:
        crop=im.crop(block['crop'])
        crop.save(target,format='PNG')
        w,ht=crop.size
    block['asset_hash']=hashlib.sha256(target.read_bytes()).hexdigest()
    if h.is_cell():
        margins=h.get_cell_margin();ps=h.HParameterSet.HShapeObject
        h.HAction.GetDefault('TablePropertyDialog',ps.HSet)
        limit=h.HwpUnitToMili(ps.ShapeTableCell.Width)-margins['left']-margins['right']
    else:
        ps=h.HParameterSet.HSecDef;h.HAction.GetDefault('PageSetup',ps.HSet)
        limit=h.HwpUnitToMili(ps.PageDef.PaperWidth-ps.PageDef.LeftMargin-ps.PageDef.RightMargin-ps.PageDef.GutterLen)
        action=h.create_action('MultiColumn');cols=h.hwp.CreateSet('ColDef');action.GetDefault(cols)
        n=int(cols.Item('Count') or 1)
        limit=(limit-h.HwpUnitToMili(int(cols.Item('SameGap') or 0))*(n-1))/n
    if not math.isfinite(limit) or limit<=0:
        dm.fail('INVALID_LOCATION','사진을 넣을 영역의 너비를 확인할 수 없습니다.')
    width=min(limit,w/block['dpi']*25.4)
    def embed(owner):
        owner.require_file_access()
        w0=owner.hwp
        ctrl=w0.insert_picture(str(target),embedded=True,sizeoption=1,width=width,height=width*ht/w)
        check(ctrl,'사진을 삽입하지 못했습니다.')
        prop=ctrl.Properties
        prop.SetItem('Width',round(w0.MiliToHwpUnit(width)))
        prop.SetItem('Height',round(w0.MiliToHwpUnit(width*ht/w)))
        prop.SetItem('TreatAsChar',True)
        ctrl.Properties=prop
        return ctrl
    if hancom.owned and not getattr(hancom,'memory_images',False):
        embed(hancom)
        return
    # Never request file access from a borrowed user window. Import an
    # embedded native fragment constructed in a dedicated private instance.
    import os
    from .backend import Hancom
    from .native_edit import capture
    from .live import native_bytes
    pidfile=Path(os.environ['HANGUL_PID_FILE']) if os.environ.get('HANGUL_PID_FILE') else None
    prior=pidfile.read_bytes() if pidfile and pidfile.exists() else None
    scratch=Hancom(visible=False)
    try:
        if not scratch.exclusive_process:
            dm.fail('SHARED_HANCOM_INSTANCE','격리된 사진 조각 인스턴스를 만들 수 없습니다.')
        c=embed(scratch);p=c.GetAnchorPos(0)
        anchor=[int(p.Item(k)) for k in ('List','Para','Pos')]
        w0=scratch.hwp;w0.Cancel();check(w0.set_pos(*anchor),'사진 조각으로 이동하지 못했습니다.')
        w0.FindCtrl()
        verify(capture(w0).get('control')=={'kind':'gso','position':anchor},'사진 조각을 정확히 선택하지 못했습니다.')
        fragment=w0.get_text_file('HWP','saveblock:true')
        native_bytes(fragment)
    finally:
        scratch.close()
        if pidfile:
            if prior is not None:pidfile.write_bytes(prior)
            else:pidfile.unlink(missing_ok=True)
    import_object_fragment(h,fragment,'HWP')


def write_lines(hancom,lines,ready):
    h=hancom.hwp
    if not any(lines) and len(lines)==1:
        return
    charshape,parashape=h.get_charshape(),h.get_parashape()
    size=int(h.CharShape.Item('Height'))
    with tempfile.TemporaryDirectory(prefix='hangul-structure-') as tmp:
        for i,line in enumerate(lines):
            ready()
            if i:
                check(h.Run('BreakPara'),'문단을 나누지 못했습니다.')
                check(h.set_parashape(parashape),'문단 서식을 유지하지 못했습니다.')
            for block in line:
                ready()
                kind=block['type']
                if kind=='text':
                    check(h.insert_text(block['text']),'본문을 입력하지 못했습니다.')
                elif kind=='equation':
                    hancom.equation(block['script'],size)
                elif kind=='image':
                    picture(hancom,block,tmp)
                check(h.set_charshape(charshape),'글자 서식을 유지하지 못했습니다.')


def remove_object(hancom,doc,entry):
    from .native_edit import controls
    h=hancom.hwp;p=doc['paragraphs'][entry['paragraph']]
    part=part_at(p,entry);kind=object_type(part)
    ctrl=controls(h).get((*p['native'],entry['start']))
    if ctrl is None or ctrl.CtrlID!=OBJECTS.get(kind):
        dm.fail('STALE_TARGET','삭제할 개체의 종류 또는 위치가 바뀌었습니다.')
    if kind=='equation' and ctrl.Properties.Item('String')!=part['script']:
        dm.fail('STALE_TARGET','삭제할 수식 내용이 바뀌었습니다.')
    check(h.delete_ctrl(ctrl),'지정한 개체를 삭제하지 못했습니다.')


def splice(hancom,doc,e,ready,inspect):
    h=hancom.hwp;kind=e['type']
    if kind=='insert_at':
        span=range_for(doc,e['target_id'],e['position'])
    elif kind=='delete_object':
        entry=dm.expand(doc,e['target_id'])[0]
        span=range_for(doc,e['target_id'],objects=True)
    else:
        span=range_for(doc,e['target_id'],objects=True)
    lines=lines_for(e.get('blocks',[]),span[1])
    ready()
    if kind=='delete_object':
        remove_object(hancom,doc,entry)
    else:
        select(h,doc,span)
        if span[:2]!=span[2:]:
            check(h.Run('Delete'),'선택한 범위를 삭제하지 못했습니다.')
        write_lines(hancom,lines,ready)
    after=inspect(hancom,validate_target=ready)
    splice_result(doc,after,span,lines)
    return after,span,lines


def insert_table(hancom,doc,e,ready,inspect):
    h=hancom.hwp;span=range_for(doc,e['target_id'],e['position'])
    a,lo,_,_=span
    ready();select(h,doc,span)
    check(h.create_table(rows=e['rows'],cols=e['columns'],header=False),'표를 만들지 못했습니다.')
    current=inspect(hancom,validate_target=ready)
    candidates=[]
    # Depending on the caret position Hancom puts the table in the current
    # paragraph or in its own paragraph with a trailing paragraph.
    for table in current['tables']:
        if not table.get('_anchor') or (table['rows'],table['columns'])!=(e['rows'],e['columns']):
            continue
        if not any(p['native']==table['_anchor'][:2] for p in current['paragraphs'][a:a+3]):
            continue
        def contains(p):return any(x.get('table')==table['number'] for x in p['cell_path'])
        reduced=dict(current,paragraphs=[p for p in current['paragraphs'] if not contains(p)])
        if [t for i,t in enumerate(table_snapshot(current),1) if i!=table['number']]!=table_snapshot(doc):
            continue
        for lines in ([[{'type':'table'}]], [[],[{'type':'table'}]], [[{'type':'table'}],[]], [[],[{'type':'table'}],[]]):
            try:splice_result(doc,reduced,span,lines,tables=False)
            except WriterError:continue
            candidates.append((table,lines))
    verify(len(candidates)==1,'지정한 위치에 요청한 크기의 표가 생기지 않았습니다.')
    table,table_lines=candidates[0]
    def inside(item):
        return any(x.get('table')==table['number'] for x in item['cell_path'])
    targets={}
    for p in current['paragraphs']:
        if not inside(p):
            continue
        cell=p['cell_path'][-1]
        key=cell['row'],cell['column']
        verify(key not in targets and p.get('mapped') and not p['parts'],'새 표의 셀을 확인하지 못했습니다.')
        targets[key]=p
    verify(len(targets)==e['rows']*e['columns'],'새 표의 셀 개수가 다릅니다.')
    expected={}
    for row,col in sorted(targets,reverse=True):
        p=targets[row,col]
        block=e['cells'][row-1][col-1] if row<=len(e['cells']) and col<=len(e['cells'][row-1]) else []
        lines=lines_for(block,0);expected[row,col]=lines
        if not block:
            continue
        ready();h.Cancel();check(h.set_pos(*p['native'],0),'새 표의 셀로 이동하지 못했습니다.')
        write_lines(hancom,lines,ready)
    after=inspect(hancom,validate_target=ready)
    actual={}
    for p in after['paragraphs']:
        if inside(p):
            cell=p['cell_path'][-1];actual.setdefault((cell['row'],cell['column']),[]).append(atoms(p))
    verify(set(actual)==set(expected),'새 표의 셀 주소가 달라졌습니다.')
    for key,lines in expected.items():
        verify([[plain(a) for a in aa] for aa in actual[key]]==[tokens(l) for l in lines],'새 표의 셀 내용이 요청과 다릅니다.')
        for line,aa in zip(lines,actual[key]):
            for block,atom in zip(expand_line(line),aa):
                if block['type']=='image':
                    verify(atom['image'].get('embedded') and atom['image'].get('asset_hash')==block.get('asset_hash'),
                           '새 표에 삽입한 사진 데이터가 요청과 다릅니다.')
    reduced=dict(after,paragraphs=[p for p in after['paragraphs'] if not inside(p)])
    splice_result(doc,reduced,span,table_lines,tables=False)
    verify([t for i,t in enumerate(table_snapshot(after),1) if i!=table['number']]==table_snapshot(doc),
           '새 표 이외의 표 구조가 달라졌습니다.')
    return after


def delete_table(hancom,doc,e,ready,inspect):
    entry=dm.expand(doc,e['target_id'])[0]
    p=doc['paragraphs'][entry['paragraph']];part=part_at(p,entry)
    table=next((t for t in doc['tables'] if t['xml_target_id']==part['id']),None)
    verify(table is not None,'표 위치를 확인하지 못했습니다.')
    def inside(item):
        return any(x.get('table')==table['number'] for x in item['cell_path'])
    def inside_table(item):
        return any(x.get('table')==table['number'] for x in item['path'])
    ready();remove_object(hancom,doc,entry)
    after=inspect(hancom,validate_target=ready)
    reduced=dict(doc,paragraphs=[p for p in doc['paragraphs'] if not inside(p)])
    i=entry['paragraph']
    index=sum(not inside(x) for x in doc['paragraphs'][:i])
    splice_result(reduced,after,(index,entry['start'],index,entry['end']),[[]],tables=False)
    removed={t['number'] for t in doc['tables'] if inside_table(t)}
    verify([t for i,t in enumerate(table_snapshot(doc),1) if i not in removed]==table_snapshot(after),
           '삭제 대상 이외의 표 구조가 달라졌습니다.')
    return after


def line_width(line):
    return sum(dm.units(b['text']) if b['type']=='text' else 8 for b in line)


def bind_targets(before,after,change=None):
    """Keep existing handles only when their unchanged semantic span is proven."""
    index={}
    old_keys=Counter(dm.digest(snapshot(p)) for p in before['paragraphs'])
    for p in after['paragraphs']:
        index.setdefault(dm.digest(snapshot(p)),[]).append(p)
    for key,entry in before['targets'].items():
        if entry['kind']=='group':
            continue
        original=before['paragraphs'][entry['paragraph']]
        e=dict(entry)
        lo,hi=e['start'],e['end'];i=e['paragraph']
        if change is None:
            sig=dm.digest(snapshot(original));matched=index.get(sig,[])
            if old_keys[sig]!=1 or len(matched)!=1:
                continue
            e['paragraph']=matched[0]['index']
        else:
            (a,start,b,end),lines=change
            if i<a:
                pass
            elif i>b:
                e['paragraph']+=len(lines)-(b-a+1)
            elif i==a and hi<=start:
                pass
            elif i==b and lo>=end:
                e['paragraph']=a+len(lines)-1
                delta=line_width(lines[-1])+(start if len(lines)==1 else 0)-end
                e['start']+=delta;e['end']+=delta
            else:
                continue
        if not 0<=e['paragraph']<len(after['paragraphs']):
            continue
        target=after['paragraphs'][e['paragraph']]
        if target.get('mapped') and coords(original)==coords(target):
            old_atoms=[semantic(x) for x in atoms(original) if lo<=x['start'] and x['end']<=hi]
            new_atoms=[semantic(x) for x in atoms(target) if e['start']<=x['start'] and x['end']<=e['end']]
            if old_atoms==new_atoms:
                after['targets'][key]=e
    for key,entry in before['targets'].items():
        if entry['kind']=='group' and key!='all' and all(x in after['targets'] for x in entry['members']):
            after['targets'][key]=entry


def execute_batch(hancom,before,ops,ready):
    from . import native_edit
    current=before;counts=Counter()
    for e in ops[0]['steps']:
        ready()
        # Revalidate the operation against the fresh mapping before any action.
        kind=e['type'];change=None
        if kind in LEGACY:
            report=native_edit.apply_native(hancom,current,dm.compile_edits(current,[e]),validate_target=ready)
            counts.update(report['counts']);after=native_edit.inspect(hancom,validate_target=ready)
        else:
            e=compile_batch(current,[e])[0]['steps'][0]
            if kind in ('set_character','set_paragraph','set_page','insert_break'):
                from .format_edit import execute
                after=execute(hancom,current,e,ready,native_edit.inspect)
            elif kind in ('set_picture','crop_picture','caption_picture'):
                from .picture_edit import execute
                after=execute(hancom,current,e,ready,native_edit.inspect)
            elif kind=='region_edit':
                from .region_edit import execute
                after=execute(hancom,current,e,ready,native_edit.inspect)
            elif kind in ('table_change','table_format'):
                if kind=='table_change':
                    from .table_edit import execute
                else:
                    from .table_format import execute
                after=execute(hancom,current,e,ready,native_edit.inspect)
                # The same table anchor remains at the same position even
                # when cell content and the grid have changed.
                after['targets'][e['target_id']]=current['targets'][e['target_id']] | {
                    'paragraph':next(p['index'] for p in after['paragraphs']
                                     if p['native']==current['paragraphs'][current['targets'][e['target_id']]['paragraph']]['native'])}
            elif kind=='insert_table':
                after=insert_table(hancom,current,e,ready,native_edit.inspect)
            elif kind=='delete_object' and object_type(part_at(
                current['paragraphs'][current['targets'][e['target_id']]['paragraph']],
                current['targets'][e['target_id']]))=='TABLE':
                after=delete_table(hancom,current,e,ready,native_edit.inspect)
            elif kind in ('copy_range','move_range'):
                after=transfer(hancom,current,e,ready,native_edit.inspect)
            else:
                after,span,lines=splice(hancom,current,e,ready,native_edit.inspect)
                change=(span,lines)
            counts[kind]+=1
        bind_targets(current,after,change);current=after
    hancom.hwp.Cancel()
    return {'counts':dict(counts),'revision':current['revision'],'_structure_snapshot':full_snapshot(current),
            'verification':{'content':True,'outside_scope':True,'table_structure':True},
            'excluded':current['excluded'],'warnings':['사진과 표의 화면 배치·넘침은 한글에서 확인하세요.']}


def transfer(hancom,doc,e,ready,inspect):
    """Use a native fragment; never put document data on the OS clipboard."""
    h=hancom.hwp
    source=range_for(doc,e['target_id'],objects=True)
    target=range_for(doc,e['destination_id'],e['position'])
    a,lo,b,hi=source
    ps=doc['paragraphs']
    selected=[[x for x in atoms(ps[i]) if (i!=a or x['start']>=lo) and (i!=b or x['end']<=hi)]
              for i in range(a,b+1)]
    ready();select(h,doc,source)
    fragment=h.get_text_file('HWP','saveblock:true')
    check(fragment,'선택 내용을 복사하지 못했습니다.')
    ready();select(h,doc,target)
    check(h.set_text_file(fragment,'HWP','insertfile'),'지정 위치에 내용을 붙이지 못했습니다.')
    after=inspect(hancom,validate_target=ready)
    x,pos,_,_=target
    inserted=len(after['paragraphs'])-len(ps)+1
    # Native block import can append a trailing empty paragraph. Verify the
    # exact semantic payload and both surrounding fragments before moving.
    verify(inserted==len(selected),'붙여 넣은 문단 구성이 원본과 다릅니다.')
    old=ps[x];new=after['paragraphs']
    verify(list(map(snapshot,ps[:x]))==list(map(snapshot,new[:x])) and
           list(map(snapshot,ps[x+1:]))==list(map(snapshot,new[x+inserted:])),
           '복사 대상 밖의 내용이 변경됐습니다.')
    for j,aa in enumerate(selected):
        head=[v for v in atoms(old) if v['end']<=pos] if j==0 else []
        tail=[v for v in atoms(old) if v['start']>=pos] if j==inserted-1 else []
        p=new[x+j]
        verify(coords(p)==coords(old) and list(map(semantic,atoms(p)))==list(map(semantic,head+aa+tail)),
               '붙여 넣은 내용·서식이 원본과 다릅니다.')
    verify(table_snapshot(after)==table_snapshot(doc) and after['bookmarks']==doc['bookmarks']
           and after.get('structure_metadata')==doc.get('structure_metadata'),'복사로 기존 표·책갈피·쪽·검토 정보가 바뀌었습니다.')
    if e['type']=='copy_range':
        return after
    offset=inserted-1 if x<a else 0
    if x==a and pos<lo:
        a+=inserted-1;b+=inserted-1
        last_width=sum(v['end']-v['start'] for v in selected[-1])
        delta=last_width+(0 if inserted==1 else -pos)
        lo+=delta
        if source[0]==source[2]:hi+=delta
    span=(a+offset,lo,b+offset,hi)
    ready();select(h,after,span);check(h.Run('Delete'),'이동 원본을 삭제하지 못했습니다.')
    final=inspect(hancom,validate_target=ready)
    splice_result(after,final,span,[[]])
    return final


def pin_assets(edits,directory):
    """The scratch test and live edit must see the same input image bytes."""
    result=copy.deepcopy(edits);paths={}
    for edit in result:
        if edit.get('type')=='insert_table':
            lists=[cell for row in edit.get('cells',[]) for cell in row]
        else:
            lists=[edit.get('blocks',[])]
        for blocks in lists:
            for block in blocks:
                if block.get('type')!='image':
                    continue
                source=Path(block['path']).expanduser().resolve()
                if source not in paths:
                    with source.open('rb') as f:data=f.read(24*1024*1024+1)
                    if len(data)>24*1024*1024:
                        invalid('각 입력 사진은 24MB 이내여야 합니다.')
                    path=directory/(str(len(paths))+'.image')
                    path.write_bytes(data);paths[source]=path
                block['path']=str(paths[source])
    return result
