"""Native position binding and bounded edits; never opens or saves borrowed windows."""
import copy
from . import document as dm
from .errors import WriterError


def cell_coordinate(address):
    import re
    m=re.fullmatch(r'([A-Z]+)([1-9][0-9]*)',address.upper())
    if not m:dm.fail('UNSUPPORTED_SELECTION','표 셀 주소를 해석하지 못했습니다.')
    col=0
    for c in m[1]:col=col*26+ord(c)-64
    return int(m[2]),col

def cell_address(row,column):
    label=''
    while column:
        column,n=divmod(column-1,26);label=chr(65+n)+label
    return label+str(row)

def selected_cells(h):
    result=set()
    for address in h.get_selected_range():
        pair=address.split(':')
        if len(pair)==1:result.add(address.upper())
        elif len(pair)==2:
            a,b=map(cell_coordinate,pair)
            if (b[0]-a[0]+1)*(b[1]-a[1]+1)>100000:dm.fail('UNSUPPORTED_SELECTION','선택한 표 범위가 너무 큽니다.')
            for row in range(a[0],b[0]+1):
                for col in range(a[1],b[1]+1):result.add(cell_address(row,col))
        else:dm.fail('UNSUPPORTED_SELECTION','표 셀 범위를 해석하지 못했습니다.')
    return sorted(result,key=cell_coordinate)

def enrich_selection(doc,state):
    if not state or not state.get('cells'):return
    cells=state['cells']
    table=next((t for t in doc['tables'] if t.get('_anchor')==cells['anchor']),None)
    if table is None:dm.fail('SELECTION_MISSING','선택한 표를 확인하지 못했습니다.')
    cells['table']=table['number'];positions={}
    for p in doc['paragraphs']:
        if p['scope']=='excluded':continue
        for ti,cell in zip(p['cell_path'][::2],p['cell_path'][1::2]):
            if ti['table']==table['number']:
                addr=cell_address(cell['row'],cell['column'])
                if p['mapped']:positions.setdefault(addr,[*p['native'],0])
    if any(a not in positions for a in cells['addresses']):dm.fail('UNMAPPED_LOCATION','선택한 셀 위치를 확인하지 못했습니다.')
    cells['first']=positions[cells['addresses'][0]]
    cells['last_address']=cells['addresses'][-1]

def restore_cells(h,cells):
    if 'first' not in cells:dm.fail('SELECTION_RESTORE_FAILED','셀 선택 복원 정보가 없습니다.')
    h.Cancel();h.set_pos(*cells['first']);h.TableCellBlock()
    if len(cells['addresses'])>1:
        h.TableCellBlockExtend()
        target=cell_coordinate(cells['last_address'])
        for _ in range(target[0]+target[1]+len(cells['addresses'])+10):
            now=cell_coordinate(h.get_cell_addr())
            if now==target:break
            if now[0]<target[0]:ok=h.TableLowerCell()
            elif now[1]<target[1]:ok=h.TableRightCell()
            else:dm.fail('SELECTION_RESTORE_FAILED','병합 셀의 선택 범위를 복원하지 못했습니다.')
            if not ok:dm.fail('SELECTION_RESTORE_FAILED','셀 선택 이동에 실패했습니다.')
        else:dm.fail('SELECTION_RESTORE_FAILED','셀 선택 복원이 종료되지 않았습니다.')
    if selected_cells(h)!=cells['addresses']:dm.fail('SELECTION_RESTORE_FAILED','복원한 셀 선택이 원래 범위와 다릅니다.')


def capture(h):
    state={'position':list(h.get_pos()),'selection':list(h.get_selected_pos()),'control':None}
    try:
        c=h.CurSelectedCtrl
        if c:
            p=c.GetAnchorPos(0)
            state['control']={'kind':c.CtrlID,'position':[int(p.Item(k)) for k in ('List','Para','Pos')]}
    except Exception: pass
    state['cells']=None
    if int(h.SelectionMode)==19:
        c=h.ParentCtrl;p=c.GetAnchorPos(0)
        state['cells']={'anchor':[int(p.Item(k)) for k in ('List','Para','Pos')],'addresses':selected_cells(h)}
    return state

def restore(h,state):
    if not state:return
    if state.get('cells'):
        restore_cells(h,state['cells']);return
    h.Cancel()
    control=state.get('control')
    if control:
        h.set_pos(*control['position']);h.FindCtrl()
        current=capture(h).get('control')
        if current!=control:dm.fail('SELECTION_RESTORE_FAILED','선택된 개체 복원에 실패했습니다.')
    elif state.get('selection',[False])[0]:
        s=state['selection'];h.select_text_by_get_pos(tuple(map(int,s[1:4])),tuple(map(int,s[4:7])))
    else:h.set_pos(*state['position'])

def controls(h):
    found={}
    for c in h.ctrl_list:
        try:
            p=c.GetAnchorPos(0);key=tuple(int(p.Item(k)) for k in ('List','Para','Pos'))
            if key in found:found[key]=None
            else:found[key]=c
        except Exception:continue
    return found

def inspect(hancom,selection=None,validate_target=None):
    guard=validate_target or (lambda:None)
    guard()
    h=hancom.hwp;state=capture(h)
    try:
        xml=hancom.xml();doc=dm.model(xml)
        scanned={};h.init_scan()
        try:
            for _ in range(1000000):
                guard();status,text=h.get_text()
                if status>=100:dm.fail('SCAN_FAILED','한글 문서 검색에 실패했습니다.')
                if status>1 or text:
                    h.move_pos(201);pos=tuple(map(int,h.get_pos()))
                    scanned.setdefault(pos[:2],[]).append((pos[2],text))
                if status<=1:break
            else:dm.fail('SCAN_FAILED','문서 검색이 종료되지 않았습니다.')
        finally:h.release_scan()
        keys=list(scanned)
        if len(keys)!=len(doc['paragraphs']):
            dm.fail('POSITION_MAP_FAILED','XML 문단과 실제 한글 문단 개수가 다릅니다. 추측해 수정하지 않습니다.')
        ctrl=controls(h)
        for p,key in zip(doc['paragraphs'],keys):
            guard()
            p['native']=list(key);p['mapped']=False
            chunks=scanned[key]
            expected=''.join(a['text'] if a['kind']=='text' else (a.get('value') if a.get('type') in ('TAB','LINEBREAK','HYPHEN','NBSPACE','FWSPACE') else '') for a in p['parts'])
            text=''.join(t[:-2] if t.endswith('\r\n') else t for _,t in chunks)
            if text!=expected:continue
            if not h.set_pos(*key,0):continue
            h.MoveParaEnd()
            if tuple(map(int,h.get_pos()))!=(*key,p['length']):continue
            valid=True
            for part in p['parts']:
                if part['kind']=='equation':
                    c=ctrl.get((*key,part['start']))
                    if c is None or c.CtrlID!='eqed' or c.Properties.Item('String')!=part['script']:
                        valid=False;break
                    part['font']=str(c.Properties.Item('EqFontName'))
                    part['size_pt']=int(c.Properties.Item('BaseUnit'))/100
                elif part.get('type')=='TABLE':
                    c=ctrl.get((*key,part['start']))
                    if c is None or c.CtrlID!='tbl':valid=False;break
                    table=next((t for t in doc['tables'] if t['xml_target_id']==part['id']),None)
                    if table is not None:table['_anchor']=[*key,part['start']]
            p['mapped']=valid
        enrich_selection(doc,state)
        original=selection if selection is not None else state
        if selection is not None and selection.get('revision',doc['revision'])!=doc['revision']:
            doc['selection_stale']=True;original={}
        enrich_selection(doc,original)
        apply_selection(doc,original)
        doc['bookmark_targets']={}
        for b in doc['bookmarks']:
            if b['scope']=='unsupported' or b['ambiguous']:continue
            try:
                guard();h.Cancel();hancom.bookmark(b['name'],1)
                sel=capture(h)
                if sel['selection'][0]:
                    previous=doc.pop('selection_target',None)
                    apply_selection(doc,sel)
                    key=doc.pop('selection_target',None)
                    if previous:doc['selection_target']=previous
                    if key:doc['bookmark_targets'][b['name']]=key
                else:
                    start=h.get_pos()
                    p=next(p for p in doc['paragraphs'] if tuple(p['native'])==tuple(start[:2]))
                    doc['bookmark_targets'][b['name']]=p['id']
            except WriterError:raise
            except Exception:continue
        return doc
    finally:
        guard();restore(h,state)

def apply_selection(doc,state):
    if not state:return
    entries=[]
    if state.get('cells'):
        cells=state['cells']
        for p in doc['paragraphs']:
            if p['scope']=='excluded':continue
            for ti,cell in zip(p['cell_path'][::2],p['cell_path'][1::2]):
                if ti['table']==cells['table'] and cell_address(cell['row'],cell['column']) in cells['addresses']:
                    entries.append(p['id']);break
    c=state.get('control')
    if c and c['kind']=='tbl':
        table=next((t for t in doc['tables'] if t.get('_anchor')==c['position']),None)
        if table:
            entries += [p['id'] for p in doc['paragraphs'] if p['scope']!='excluded' and any(ti['table']==table['number'] for ti in p['cell_path'][::2])]
    if c and c['kind']=='eqed':
        for p in doc['paragraphs']:
            if p['scope']=='excluded':continue
            for a in p['parts']:
                if [*p['native'],a['start']]==c['position'] and a['kind']=='equation':
                    entries.append(a['id'])
    s=state.get('selection',[False])
    if not entries and s and s[0]:
        start=tuple(map(int,s[1:4]));end=tuple(map(int,s[4:7]))
        order={tuple(p['native']):i for i,p in enumerate(doc['paragraphs'])}
        if start[:2] in order and end[:2] in order:
            a=(order[start[:2]],start[2]);b=(order[end[:2]],end[2])
            if a>b:a,b=b,a
            for p in doc['paragraphs'][a[0]:b[0]+1]:
                if p['scope']=='excluded':continue
                lo=a[1] if p['index']==a[0] else 0
                hi=b[1] if p['index']==b[0] else p['length']
                if lo<hi:entries.append(dm.add_target(doc,{'kind':'range','paragraph':p['index'],'start':lo,'end':hi}))
    if entries:doc['selection_target']=dm.add_target(doc,{'kind':'group','members':entries})

def installed_fonts():
    import win32gui
    result=set();dc=win32gui.GetDC(0)
    def collect(logfont,metric,kind,param):
        result.add(logfont.lfFaceName.lstrip('@'));return 1
    try:win32gui.EnumFontFamilies(dc,None,collect,None)
    finally:win32gui.ReleaseDC(0,dc)
    return result

def validate_fonts(ops):
    requested={v for o in ops if o['type']=='set_format' for k,v in o['properties'].items() if k in ('font_name','equation_font')}
    if not requested:return
    available=installed_fonts()
    missing=requested-available
    if missing:dm.fail('FONT_UNAVAILABLE','설치되지 않은 글꼴입니다: '+', '.join(sorted(missing)))

def equation_at(h,p,offset,script):
    c=controls(h).get((*p['native'],offset))
    if c is None or c.CtrlID!='eqed' or c.Properties.Item('String')!=script:
        dm.fail('STALE_TARGET','대상 수식 개체의 위치 또는 내용이 다릅니다.')
    return c

def select(h,p,start,end):
    h.Cancel()
    if not h.select_text_by_get_pos((*p['native'],start),(*p['native'],end)):
        dm.fail('POSITION_MAP_FAILED','정확한 글자 범위를 선택하지 못했습니다.')

def apply_native(hancom,before,ops,cancelled=None,validate_target=None):
    h=hancom.hwp
    validate_fonts(ops)
    def ready():
        if cancelled is not None and cancelled.is_set():dm.fail('HANCOM_TIMEOUT','시간 초과 후 추가 수정을 중단했습니다.')
        if validate_target:validate_target()
    ready()
    counts={'text_replacements':0,'equation_replacements':0,'formatted_text_ranges':0,'formatted_equations':0}
    content=[o for o in ops if o['type']!='set_format']
    for op in sorted(content,key=lambda o:(o['paragraph'],o['start']),reverse=True):
        ready();p=before['paragraphs'][op['paragraph']]
        if op['type']=='replace_text':
            select(h,p,op['start'],op['end'])
            if h.get_text_file('UNICODE','saveblock:true')!=op['expected_text']:
                dm.fail('STALE_TARGET','선택한 실제 원문이 다릅니다.')
            select(h,p,op['start'],op['start']+dm.units(op['expected_text'][0]))
            shape={k:v for k,v in h.get_charshape_as_dict().items() if k!='HSet' and v is not None}
            select(h,p,op['start'],op['end'])
            if op['text']:
                if not h.insert_text(op['text']):dm.fail('HANCOM_FAILED','본문 교체 실패')
                end=op['start']+dm.units(op['text'])
                select(h,p,op['start'],end)
                if not h.set_charshape(shape):dm.fail('HANCOM_FAILED','교체한 글자 서식 복원 실패')
            else:
                if not h.Run('Delete'):dm.fail('HANCOM_FAILED','선택 글자 삭제 실패')
                if op['start']==0 and op['end']==p['length'] and all(a['kind']=='text' for a in p['parts']):
                    if not h.set_charshape(shape):dm.fail('HANCOM_FAILED','빈 문단의 기본 서식 복원 실패')
            counts['text_replacements']+=1
        else:
            c=equation_at(h,p,op['start'],op['expected_script'])
            prop=c.Properties;prop.SetItem('String',op['script']);c.Properties=prop
            counts['equation_replacements']+=1
    current=inspect(hancom,validate_target=ready)
    for op in (o for o in ops if o['type']=='set_format'):
        ready();p=current['paragraphs'][op['paragraph']]
        changes=[o for o in content if o['paragraph']==op['paragraph']]
        lo=dm.shifted(op['start'],changes);hi=dm.shifted(op['end'],changes)
        props=op['properties']
        if not p['parts'] and ({'font_name','size_pt'}&props.keys()):
            h.Cancel();h.set_pos(*p['native'],0)
            action=h.create_action('CharShape');ps=action.CreateSet();action.GetDefault(ps)
            if 'size_pt' in props:ps.SetItem('Height',round(props['size_pt']*100))
            if 'font_name' in props:
                for lang in dm.LANGS:
                    ps.SetItem('FaceName'+lang,props['font_name']);ps.SetItem('FontType'+lang,1)
            if not action.Execute(ps):dm.fail('HANCOM_FAILED','빈 문단 서식 변경 실패')
            counts['formatted_text_ranges']+=1
        for a in p['parts']:
            ready()
            if a['kind']=='text':
                start=max(lo,a['start']);end=min(hi,a['end'])
                if start>=end or not ({'font_name','size_pt'}&props.keys()):continue
                select(h,p,start,end)
                # Only write the requested HCharShape items. set_font() writes
                # additional defaults (e.g. font type) even for size-only edits.
                action=h.create_action('CharShape');ps=action.CreateSet();action.GetDefault(ps)
                if 'size_pt' in props:ps.SetItem('Height',round(props['size_pt']*100))
                if 'font_name' in props:
                    for lang in dm.LANGS:
                        ps.SetItem('FaceName'+lang,props['font_name']);ps.SetItem('FontType'+lang,1)
                if not action.Execute(ps):dm.fail('HANCOM_FAILED','글자 서식 변경 실패')
                counts['formatted_text_ranges']+=1
            elif a['kind']=='equation' and lo<=a['start']<a['end']<=hi and ({'equation_font','equation_size_pt'}&props.keys()):
                c=equation_at(h,p,a['start'],a['script']);prop=c.Properties
                if 'equation_size_pt' in props:prop.SetItem('BaseUnit',round(props['equation_size_pt']*100))
                if 'equation_font' in props:prop.SetItem('EqFontName',props['equation_font'])
                c.Properties=prop;counts['formatted_equations']+=1
    ready();after=inspect(hancom,validate_target=ready)
    dm.verify_edit(before,after,ops)
    h.Cancel()
    return {'counts':counts,'revision':after['revision'],'verification':{'content':True,'outside_scope':True,'format':True,'table_structure':True,'equation_scripts':True},
            'warnings':['글자·수식 크기 변경에 따른 줄바꿈과 표 셀의 시각적 넘침은 한글에서 확인하세요.'] if any(o['type']=='set_format' for o in ops) else [],
            'excluded':before['excluded']}

def execute(hancom,job):
    from pathlib import Path
    hancom.open(job['path'])
    before=inspect(hancom)
    if before['revision']!=job['revision']:dm.fail('STALE_REVISION','분석 후 문서가 변경됐습니다. 다시 읽으세요.')
    before['targets']=job['targets']
    ops=dm.compile_edits(before,job['edits'])
    report=apply_native(hancom,before,ops)
    hancom.save(job['path']);hancom.hwp.clear(1);hancom.open(job['path'])
    after=inspect(hancom);dm.verify_edit(before,after,ops)
    report.update(ok=True,version=hancom.version,security_module=hancom.module,revision=after['revision'])
    report['verification']['reopened']=True
    return report


def smoke(hancom,directory):
    from pathlib import Path
    reports=[]
    for ext in ('.hwp','.hwpx'):
        h=hancom.hwp;h.clear(1)
        h.insert_text('문장 검사 ');hancom.equation('x^2 +1',1000)
        path=Path(directory)/('edit-smoke'+ext);hancom.save(path)
        before=inspect(hancom)
        text=dm.locate(before,{'type':'text','text':'문장 검사'})[0]['target_id']
        equation=dm.locate(before,{'type':'equation'})[0]['target_id']
        edits=[{'type':'replace_text','target_id':text,'expected_text':'문장 검사','text':'검사 완료'},
               {'type':'replace_equation','target_id':equation,'expected_script':'x^2 +1','script':'x^{3}+1','format':'latex'},
               {'type':'set_format','target_id':'all','properties':{'size_pt':11,'equation_size_pt':11}}]
        report=execute(hancom,{'path':str(path),'revision':before['revision'],'targets':before['targets'],'edits':edits})
        reports.append({'format':ext,'ok':True,'verification':report['verification']})
    return reports
