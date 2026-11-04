"""Lossless review snapshots. HWPML export does not retain track changes."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import struct
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from . import document as dm
from .errors import WriterError


def local(e):
    return e.tag.rsplit('}',1)[-1]


def native_snapshot(hancom):
    from .live import native_bytes
    return native_bytes(hancom.hwp.get_text_file('HWP',''))


def file_flags(binary):
    """Read the named compound-file stream, not a magic substring in the body."""
    import pythoncom
    with tempfile.TemporaryDirectory(prefix='hangul-header-') as root:
        p=Path(root)/'snapshot.hwp'
        p.write_bytes(binary)
        storage=stream=None
        try:
            storage=pythoncom.StgOpenStorage(str(p),None,0x10,None,0)
            stream=storage.OpenStream('FileHeader',None,0x10,0)
            head=stream.Read(40)
            if len(head)!=40 or not head.startswith(b'HWP Document File'):
                dm.fail('BACKUP_FAILED','네이티브 사본의 파일 정보를 확인하지 못했습니다.')
            return struct.unpack_from('<I',head,36)[0]
        finally:
            del stream,storage


def tracking_status(hancom):
    try:
        value=int(hancom.hwp.hwp.IsTrackChange)
    except Exception:
        dm.fail('UNVERIFIED_REVIEW','이 한글 빌드에서 변경 추적 상태를 확인할 수 없습니다.')
    if value not in (0,1):
        dm.fail('UNVERIFIED_REVIEW','변경 추적 상태의 값이 올바르지 않습니다.')
    return bool(value)


def guard_hml(hancom):
    # The file flag stays set for existing revisions even if recording stops.
    try:enabled=int(hancom.hwp.hwp.IsTrackChange)==1
    except Exception:enabled=False
    binary=native_snapshot(hancom)
    if enabled or file_flags(binary) & (1<<14):
        dm.fail('REVIEW_SNAPSHOT_REQUIRED','추적 정보가 있는 문서는 검토 범위(scope=review)로 먼저 읽으세요.')


def snapshot(hancom):
    from .backend import Hancom
    enabled=tracking_status(hancom)
    binary=native_snapshot(hancom)
    with tempfile.TemporaryDirectory(prefix='hangul-review-') as root:
        hwp=Path(root)/'snapshot.hwp';hwpx=Path(root)/'snapshot.hwpx'
        hwp.write_bytes(binary)
        # The borrowed document is never SaveAs'd to inspect review metadata.
        pidfile=Path(os.environ['HANGUL_PID_FILE']) if os.environ.get('HANGUL_PID_FILE') else None
        oldpid=pidfile.read_bytes() if pidfile and pidfile.exists() else None
        clone=Hancom(visible=False)
        try:
            if not clone.exclusive_process:
                dm.fail('SHARED_HANCOM_INSTANCE','격리된 검토 사본 인스턴스를 만들 수 없습니다.')
            clone.open(hwp);clone.save(hwpx)
            return read_package(hwpx,enabled)
        finally:
            clone.close()
            if pidfile:
                if oldpid is not None:pidfile.write_bytes(oldpid)
                else:pidfile.unlink(missing_ok=True)


def read_package(path,enabled):
    with ZipFile(path) as z:
        names=z.namelist()
        sections=sorted((n for n in names if re.fullmatch(r'Contents/section\d+\.xml',n)),
                        key=lambda n:int(re.search(r'(\d+)\.xml',n)[1]))
        if not sections or len(set(names))!=len(names):
            dm.fail('REVIEW_SNAPSHOT_FAILED','구역 XML을 확인하지 못했습니다.')
        relevant=['Contents/header.xml',*sections,*sorted(n for n in names if n.startswith('BinData/'))]
        if sum(z.getinfo(n).file_size for n in relevant)>256*1024*1024:
            dm.fail('REVIEW_SNAPSHOT_FAILED','검토용 사본이 너무 큽니다.')
        head=ET.fromstring(z.read(relevant[0]));body=[ET.fromstring(z.read(n)) for n in sections]
        assets=[(n,hashlib.sha256(z.read(n)).hexdigest()) for n in relevant[len(sections)+1:]]
    changes={}
    authors={e.get('id'):e.get('name','') for e in head.iter() if local(e)=='trackChangeAuthor'}
    for e in head.iter():
        if local(e)=='trackChange':
            key=e.get('id')
            if not key or key in changes:
                dm.fail('REVIEW_SNAPSHOT_FAILED','중복되거나 잘못된 변경 ID입니다.')
            changes[key]=dict(e.attrib,author=authors.get(e.get('authorID'),''))
    return {'head':head,'body':body,'assets':assets,'changes':changes,'tracking_enabled':enabled}


MARKS={'insertBegin':('Insert',True),'insertEnd':('Insert',False),
       'deleteBegin':('Delete',True),'deleteEnd':('Delete',False)}
OBJECT_WIDTH={'secPr':8,'ctrl':8,'tbl':8,'pic':8,'equation':8,'lineBreak':1,'tab':8,'hyphen':1,'nbSpace':1,'fwSpace':1}


def raw_xml(e):
    return [local(e),dict(e.attrib),e.text or '',e.tail or '',[raw_xml(c) for c in e if local(c)!='linesegarray']]


def paragraph_tokens(p):
    """Yield flat styled characters, markers and whole objects in native order."""
    for run in p:
        if local(run)=='linesegarray':continue
        if local(run)!='run':
            yield None,'opaque',run
            continue
        style=tuple(sorted(run.attrib.items()))
        for item in run:
            k=local(item)
            if k!='t':
                yield style,'opaque',item
                continue
            for c in item.text or '':yield style,'text',c
            for child in item:
                yield style,'mark' if local(child) in MARKS else 'opaque',child
                for c in child.tail or '':yield style,'text',c


def projection(snap,decisions=None,ids=None):
    """Compute expected visible content after applying/cancelling named marks."""
    decisions=decisions or {}
    changed_counts={k:[0,0] for k in decisions}
    def node(e):
        k=local(e)
        if k=='p':
            active={};out=[]
            for style,typ,value in paragraph_tokens(e):
                if typ=='mark' and value.get('TcId') in decisions:
                    key=value.get('TcId');change,opening=MARKS[local(value)]
                    changed_counts[key][int(not opening)]+=1
                    if opening:
                        if active or key in active:
                            dm.fail('UNVERIFIED_REVIEW','겹친 변경은 안전하게 적용하거나 취소할 수 없습니다.')
                        if snap['changes'].get(key,{}).get('type')!=change:
                            dm.fail('UNVERIFIED_REVIEW','변경 표식과 목록의 종류가 다릅니다.')
                        active[key]=(change=='Insert')==(decisions[key]=='reject')
                    else:
                        if key not in active or value.get('paraend','0') not in ('0',''):
                            dm.fail('UNVERIFIED_REVIEW','여러 문단 또는 문단 끝에 걸친 변경은 검증되지 않았습니다.')
                        del active[key]
                    continue
                if active and typ!='text':
                    dm.fail('UNVERIFIED_REVIEW','개체 또는 다른 변경과 겹친 검토 범위는 지원하지 않습니다.')
                if typ=='text':
                    if not any(active.values()):out.append([style,'text',value])
                elif typ=='mark':
                    attrs=dict(value.attrib)
                    if ids is not None and attrs.get('TcId') in ids:
                        attrs['TcId']=ids[attrs['TcId']]
                    out.append([style,'mark',local(value),attrs])
                else:
                    out.append([style,'opaque',node(value)])
            if active:dm.fail('UNVERIFIED_REVIEW','여러 문단에 걸친 변경은 검증되지 않았습니다.')
            return [k,{a:v for a,v in e.attrib.items() if a!='id'},out]
        return [k,dict(e.attrib),e.text or '',[node(c) for c in e if local(c)!='linesegarray']]
    result=[node(x) for x in snap['body']]
    if any(v!=[1,1] for v in changed_counts.values()):
        dm.fail('UNVERIFIED_REVIEW','변경의 시작과 끝을 하나씩 확인하지 못했습니다.')
    return result


def header_projection(e):
    return [local(e),dict(e.attrib),e.text or '',[header_projection(c) for c in e
             if local(c) not in ('trackChanges','trackChangeAuthors')]]


def payload(snap,decisions=None,enabled=None,normalize_ids=False):
    changes={k:v for k,v in snap['changes'].items() if k not in (decisions or {})}
    ids={k:str(i) for i,k in enumerate(changes,1)} if normalize_ids else None
    if ids is not None:
        changes={ids[k]:dict(v,id=ids[k]) for k,v in changes.items()}
    return [projection(snap,decisions,ids),header_projection(snap['head']),snap['assets'],changes,
            snap['tracking_enabled'] if enabled is None else enabled]


def locations(snap):
    result={}
    para_index=0
    for si,section in enumerate(snap['body']):
        for p in section:
            if local(p)!='p':continue
            offset=0;unknown=False;active={}
            for _,typ,e in paragraph_tokens(p):
                if typ=='text':
                    offset+=dm.units(e)
                    for item in active.values():item['text']+=e
                elif typ=='mark':
                    key=e.get('TcId');kind,opening=MARKS[local(e)]
                    if opening:
                        active[key]={'section':si+1,'paragraph_index':para_index,'start':offset,'text':'','change_type':kind,'exact':not unknown and not active}
                    elif key in active:
                        item=active.pop(key);item['end']=offset
                        item['exact'] &= e.get('paraend','0') in ('0','') and offset>item['start']
                        if key in result:item['exact']=False
                        result[key]=item
                else:
                    k=local(e)
                    if k not in OBJECT_WIDTH:unknown=True
                    offset+=OBJECT_WIDTH.get(k,0)
                    for item in active.values():item['exact']=False
            para_index+=1
    return result


def inspect(hancom):
    snap=snapshot(hancom)
    revision='review:'+dm.digest(payload(snap))
    loc=locations(snap)
    changes=[{'target_id':dm.uid(revision,'change:'+k),'change_id':k,'kind':'change',
              'change_type':v.get('type'),'author':v.get('author'),'date':v.get('date'),
              'text':loc.get(k,{}).get('text','')[:2048],
              'section':loc.get(k,{}).get('section'),'paragraph_index':loc.get(k,{}).get('paragraph_index'),
              'mapped':bool(loc.get(k,{}).get('exact'))}
             for k,v in snap['changes'].items()]
    return {'review_mode':True,'revision':revision,'changes':changes,'tracking_enabled':snap['tracking_enabled'],'text_runs':searchable_text(snap)}


def compile_actions(analysis,edits):
    if not isinstance(edits,list) or not 1<=len(edits)<=100:
        dm.fail('INVALID_EDIT','검토 작업을 1~100개 지정하세요.')
    if len(edits)==1 and isinstance(edits[0],dict) and edits[0].get('type')=='review_text':
        compile_text(analysis,edits[0]);return []
    index={c['target_id']:c for c in analysis['changes']};seen=set();result=[]
    for e in edits:
        if not isinstance(e,dict) or e.get('type')!='review_change' or e.get('action') not in ('accept','reject'):
            dm.fail('INVALID_EDIT','검토 범위에는 review_change의 accept 또는 reject를 사용하세요.')
        key=e.get('target_id')
        if not isinstance(key,str):dm.fail('TARGET_MISSING','변경 내역 ID가 필요합니다.')
        if key=='all':
            if len(edits)!=1 or e.get('all_changes') is not True:
                dm.fail('INVALID_EDIT','전체 적용·취소는 all_changes=true로 명시하세요.')
            values=analysis['changes']
        elif key in index:values=[index[key]]
        else:dm.fail('TARGET_MISSING','이번 검토 목록에 없는 변경 내역입니다.')
        if not values:dm.fail('TARGET_MISSING','적용하거나 취소할 변경 내역이 없습니다.')
        for c in values:
            if c['change_id'] in seen:dm.fail('OVERLAPPING_EDITS','같은 변경 내역을 반복 지정했습니다.')
            if not c['mapped'] or c['change_type'] not in ('Insert','Delete'):
                dm.fail('UNVERIFIED_REVIEW','현재 검증된 검토 대상은 본문의 단일 문단 글 삽입·삭제 변경입니다.')
            seen.add(c['change_id']);result.append((c['change_id'],e['action']))
    return result


def apply(hancom,analysis,edits,ready):
    ops=compile_actions(analysis,edits)
    h=hancom.hwp
    current=snapshot(hancom)
    if 'review:'+dm.digest(payload(current))!=analysis['revision']:
        dm.fail('STALE_REVISION','검토 목록을 읽은 뒤 문서가 변경됐습니다.')
    if not ops:
        return apply_text(hancom,current,analysis,edits[0],ready)
    expected=payload(current,dict(ops),normalize_ids=True)
    # Hancom compacts remaining track-change IDs after each decision. Preserve
    # their order, metadata, text, and marker locations when remapping IDs.
    names={k:k for k in current['changes']}
    for original,action in ops:
        key=names[original]
        ready();loc=locations(current).get(key)
        if not loc or not loc['exact']:
            dm.fail('STALE_TARGET','변경 범위를 다시 찾지 못했습니다.')
        want=payload(current,{key:action},normalize_ids=True)
        survivors=[k for k in current['changes'] if k!=key]
        pos=(0,loc['paragraph_index'],loc['start']+int(loc['end']-loc['start']>1))
        h.Cancel()
        if not h.set_pos(*pos) or tuple(map(int,h.get_pos()))!=pos:
            dm.fail('STALE_TARGET','한글의 검토 위치가 문서 구조와 다릅니다.')
        ready()
        if not h.Run('TrackChangeApply' if action=='accept' else 'TrackChangeCancel'):
            dm.fail('HANCOM_FAILED','변경 내역을 처리하지 못했습니다.')
        ready();current=snapshot(hancom)
        if payload(current,normalize_ids=True)!=want:
            dm.fail('VERIFY_FAILED','지정한 변경 외에 다른 내용 또는 추적 정보가 달라졌습니다.')
        remap=dict(zip(survivors,current['changes']))
        names={o:remap[k] for o,k in names.items() if k in remap}
    if payload(current,normalize_ids=True)!=expected:
        dm.fail('VERIFY_FAILED','요청한 검토 결과가 다릅니다.')
    revision='review:'+dm.digest(payload(current))
    return {'ok':True,'revision':revision,'counts':{'review_changes':len(ops)},
            'verification':{'content':True,'outside_scope':True,'review':True},'warnings':[]}


def searchable_text(snap):
    """Index plain runs by UTF-16 position, without crossing an existing mark."""
    result=[];index=0
    for section in snap['body']:
        for p in section:
            if local(p)!='p':continue
            offset=0;run=None;runs=[];safe=True
            for style,kind,value in paragraph_tokens(p):
                if kind=='text':
                    if run is None or run['style']!=list(style):
                        run={'paragraph_index':index,'start':offset,'text':'','style':list(style)}
                        runs.append(run)
                    run['text']+=value;offset+=dm.units(value)
                else:
                    run=None
                    if kind=='mark' or local(value) not in OBJECT_WIDTH:
                        safe=False
                    elif kind=='opaque':
                        offset+=OBJECT_WIDTH[local(value)]
            if safe:result.extend(runs)
            index+=1
    return result


def find_text(analysis,selector):
    needle=selector.get('text')
    if not isinstance(needle,str) or not needle or any(ord(c)<32 for c in needle) or len(needle)>4096:
        dm.fail('INVALID_SELECTOR','검토용 글자 검색에는 1~4,096자의 정확한 원문이 필요합니다.')
    hits=[]
    for run in analysis['text_runs']:
        for match in re.finditer(re.escape(needle),run['text']):
            offset=run['start']+dm.units(run['text'][:match.start()])
            entry={'paragraph_index':run['paragraph_index'],'start':offset,'end':offset+dm.units(needle),
                   'text':needle,'style':run['style']}
            target=dm.uid(analysis['revision'],dm.encode(entry))
            analysis.setdefault('text_targets',{})[target]=entry
            hits.append({'kind':'review_text','target_id':target,'text':needle,'paragraph_index':entry['paragraph_index']})
    if 'occurrence' in selector:
        n=selector['occurrence']
        if type(n) is not int or n<1:dm.fail('INVALID_SELECTOR','occurrence는 1 이상의 정수입니다.')
        hits=hits[n-1:n]
    return hits


def compile_text(analysis,edit):
    key=edit.get('target_id')
    if not isinstance(key,str) or key not in analysis.get('text_targets',{}):
        dm.fail('TARGET_MISSING','review_text 검색 결과를 지정하세요.')
    target=analysis['text_targets'][key]
    if edit.get('expected_text')!=target['text']:
        dm.fail('STALE_TARGET','검색한 원문을 정확히 전달하세요.')
    text=edit.get('text')
    if not isinstance(text,str) or len(text)>16000 or any(ord(c)<32 for c in text):
        dm.fail('INVALID_EDIT','줄바꿈·제어 문자 없는 교체 글이 필요합니다.')
    tracking=edit.get('tracking','inherit')
    if tracking not in ('inherit','on_for_request'):
        dm.fail('INVALID_EDIT','tracking은 inherit 또는 on_for_request입니다.')
    return target


def replace_projection(body,target,text):
    import copy
    result=copy.deepcopy(body)
    paras=[p for s in result for p in s[3] if p[0]=='p']
    p=paras[target['paragraph_index']]
    lo,hi=target['start'],target['end']
    i=0;selected=[];offset=0
    for i,t in enumerate(p[2]):
        style,kind,value=t[:3]
        if kind=='text':width=dm.units(value)
        elif kind=='opaque' and value[0] in OBJECT_WIDTH:width=OBJECT_WIDTH[value[0]]
        else:dm.fail('UNVERIFIED_REVIEW','선택 문단의 구조를 검증할 수 없습니다.')
        if lo<=offset and offset+width<=hi:
            if kind!='text':dm.fail('PROTECTED_RANGE','개체 위에는 글을 덮어쓰지 않습니다.')
            selected.append(i)
        offset+=width
    if not selected or ''.join(p[2][i][2] for i in selected)!=target['text']:
        dm.fail('STALE_TARGET','한글 위치와 원문을 확인하지 못했습니다.')
    style=p[2][selected[0]][0]
    p[2][selected[0]:selected[-1]+1]=[[style,'text',c] for c in text]
    return result


def apply_text(hancom,current,analysis,e,ready):
    from .structure import verify
    target=compile_text(analysis,e);h=hancom.hwp
    before=payload(current);expected=replace_projection(before[0],target,e['text'])
    previous=current['tracking_enabled'];requested=e.get('tracking','inherit')=='on_for_request' or previous
    start=(0,target['paragraph_index'],target['start']);end=(0,target['paragraph_index'],target['end'])
    ready();h.Cancel()
    if not h.select_text_by_get_pos(start,end):
        dm.fail('STALE_TARGET','검토할 글자 범위를 선택하지 못했습니다.')
    sel=h.get_selected_pos()
    if not sel[0] or {tuple(map(int,sel[1:4])),tuple(map(int,sel[4:7]))}!={start,end}:
        dm.fail('STALE_TARGET','실제 선택 범위가 요청과 다릅니다.')
    try:
        if requested!=previous:
            h.hwp.IsTrackChange=int(requested)
            verify(tracking_status(hancom)==requested,'요청한 변경 추적 상태를 켜지 못했습니다.')
        ready()
        ok=h.insert_text(e['text']) if e['text'] else h.Run('Delete')
        if not ok:dm.fail('HANCOM_FAILED','검토할 글자 범위를 변경하지 못했습니다.')
    finally:
        if requested!=previous:
            # Check borrowed-window identity before restoring document settings.
            ready()
            h.hwp.IsTrackChange=int(previous)
            verify(tracking_status(hancom)==previous,'기존 변경 추적 설정을 복원하지 못했습니다.')
    h.Cancel();ready();after=snapshot(hancom)
    new={k for k in after['changes'] if k not in current['changes']}
    if requested:
        verify(bool(new),'요청한 변경이 기록되지 않았습니다.')
    else:
        verify(not new,'기록 중지가 설정된 문서에 추적 기록이 생겼습니다.')
    accepted=payload(after,{k:'accept' for k in new})
    if requested:
        rejected=payload(after,{k:'reject' for k in new})
        verify(rejected==before,'새 변경을 취소했을 때 원래 문서로 돌아가지 않습니다.')
    verify(accepted==[expected,*before[1:]],'추적된 편집 결과 또는 기존 검토 내용이 다릅니다.')
    stable_result=payload(after)
    stable_result[3]={k:{a:b for a,b in v.items() if a!='date' or k not in new} for k,v in stable_result[3].items()}
    return {'ok':True,'revision':'review:'+dm.digest(payload(after)),'_review_projection':dm.digest(stable_result),
            'counts':{'review_text':1,'tracked_changes_created':len(new)},
            'verification':{'content':True,'outside_scope':True,'review':True},'warnings':[]}
