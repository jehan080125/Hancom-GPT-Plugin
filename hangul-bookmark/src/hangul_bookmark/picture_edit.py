"""Picture changes are bound to the exact standalone embedded control."""
import base64
import copy
from pathlib import Path
import tempfile

from . import document as dm,xmlcheck
from .format_edit import boolean,number,preserve
from .structure import atoms,check,invalid,lines_for,object_type,part_at,remove_object,select,semantic,snapshot,splice_result,verify,write_lines

KINDS={'set_picture','crop_picture','caption_picture'}
ALIGN={'left':(0,'Left'),'center':(1,'Center'),'right':(2,'Right')}
WRAP={'square':0,'top_bottom':1,'behind':2,'front':3,'tight':4,'through':5}


def find(doc,key):
    entry=doc['targets'].get(key)
    if not entry or entry.get('kind')!='control':
        invalid('read_document 또는 find_targets의 그림 ID가 필요합니다.')
    p=doc['paragraphs'][entry['paragraph']]
    a=part_at(p,entry)
    if object_type(a)!='PICTURE' or not p.get('mapped') or not a['image'].get('embedded') or not a['image'].get('asset_hash'):
        dm.fail('UNVERIFIED_IMAGE','정확한 위치가 확인된 내장 사진을 지정하세요.')
    return p,a


def node(value,name):
    if value[0]==name:return value
    return next((found for child in value[3] if (found:=node(child,name)) is not None),None)


def validate(doc,e):
    p,a=find(doc,e['target_id']);kind=e['type']
    if kind=='set_picture':
        props=e.get('properties')
        if not isinstance(props,dict) or not props or props.keys()-{'width_mm','height_mm','inline','align','wrap'}:
            invalid('지원되는 사진 크기 또는 배치 속성을 지정하세요.')
        for key,v in props.items():
            if key=='inline':boolean(v)
            elif key=='align':
                if v not in ALIGN or props.get('inline') is not False:
                    invalid('사진 정렬은 inline=false와 left, center, right 중 하나를 지정하세요.')
            elif key=='wrap':
                if v not in WRAP or props.get('inline') is not False:
                    invalid('글 배치 방식에는 inline=false와 지원되는 wrap 값을 지정하세요.')
            else:number(v,0.1,2000,key)
    elif kind=='crop_picture':
        crop=e.get('crop')
        if not isinstance(crop,list) or len(crop)!=4 or any(type(x) is not int for x in crop):
            invalid('자르기 영역은 원본 픽셀 단위 [왼쪽, 위, 오른쪽, 아래]입니다.')
        if not 0<=crop[0]<crop[2] or not 0<=crop[1]<crop[3]:
            invalid('자르기 영역을 확인하세요.')
        info=a['image']
        if node(a['value'],'CAPTION') or info['has_effects'] or info['rotation'].get('Angle','0')!='0' or \
                info['shape'].get('HorzFlip','false')=='true' or info['shape'].get('VertFlip','false')=='true':
            dm.fail('UNVERIFIED_IMAGE','기존 캡션·효과·회전·뒤집기가 있는 사진의 자르기는 검증되지 않았습니다.')
    else:
        text=e.get('text')
        if not isinstance(text,str) or not 1<=len(text)<=2000 or any(ord(c)<32 for c in text):
            invalid('줄바꿈 없는 캡션 글을 지정하세요.')
        if node(a['value'],'CAPTION') is not None:
            dm.fail('UNVERIFIED_IMAGE','이미 캡션이 있는 사진은 이 작업으로 덮어쓰지 않습니다.')


def set_shape(hancom,before,e,ready,inspect):
    from .native_edit import controls
    h=hancom.hwp;p,a=find(before,e['target_id']);props=e['properties']
    anchor=(*p['native'],a['start'])
    ctrl=controls(h).get(anchor)
    if ctrl is None or ctrl.CtrlID!='gso':
        dm.fail('STALE_TARGET','사진 개체의 위치를 다시 찾지 못했습니다.')
    ready();ps=ctrl.Properties
    width,height=int(ps.Item('Width')),int(ps.Item('Height'))
    requested={}
    if props.keys()&{'width_mm','height_mm'}:
        verify(width>0 and height>0,'기존 사진 크기를 확인하지 못했습니다.')
        w=round(h.MiliToHwpUnit(props['width_mm'])) if 'width_mm' in props else None
        ht=round(h.MiliToHwpUnit(props['height_mm'])) if 'height_mm' in props else None
        requested['Width']=w if w is not None else round(ht*width/height)
        requested['Height']=ht if ht is not None else round(w*height/width)
    if 'inline' in props:requested['TreatAsChar']=int(props['inline'])
    if 'align' in props:requested['HorzAlign']=ALIGN[props['align']][0]
    if 'wrap' in props:requested['TextWrap']=WRAP[props['wrap']]
    for key,v in requested.items():ps.SetItem(key,v)
    ctrl.Properties=ps
    actual=ctrl.Properties
    verify(all(int(actual.Item(k))==v for k,v in requested.items()),'요청한 크기·배치가 적용되지 않았습니다.')
    after=inspect(hancom,validate_target=ready);preserve(before,after)
    verify(len(before['paragraphs'])==len(after['paragraphs']),'사진 변경으로 문단 수가 달라졌습니다.')
    def mask(q):
        result=snapshot(q)
        j=next(i for i,x in enumerate(atoms(q)) if x['start']==a['start'] and x.get('type')=='PICTURE')
        value=result[-1][j]['value']
        for tag,attrs in [('SIZE',('Width','Height') if 'Width' in requested else ()),
                          ('POSITION',('TreatAsChar',) if 'inline' in props else ()),
                          ('POSITION',('HorzAlign',) if 'align' in props else ()),
                          ('SHAPEOBJECT',('TextWrap',) if 'wrap' in props else ()),
                          ('SHAPECOMPONENT',('CurWidth','CurHeight') if 'Width' in requested else ()),
                          ('ROTATIONINFO',('CenterX','CenterY') if 'Width' in requested else ()),
                          ('SCAMATRIX',('E1','E5') if 'Width' in requested else ())]:
            n=node(value,tag)
            if n:
                for key in attrs:n[1].pop(key,None)
        return result
    for i,(old,new) in enumerate(zip(before['paragraphs'],after['paragraphs'])):
        verify(mask(old)==mask(new) if i==p['index'] else snapshot(old)==snapshot(new),
               '사진 크기·배치 외의 내용 또는 속성이 달라졌습니다.')
    return after


def crop(hancom,before,e,ready,inspect):
    from PIL import Image
    p,a=find(before,e['target_id']);info=a['image']
    root=xmlcheck.parse(hancom.xml())
    n=next((n for n in root.iter() if xmlcheck.tag(n)=='BINDATA' and n.get('Id')==info['bin_id']),None)
    verify(n is not None,'사진 원본을 읽지 못했습니다.')
    data=base64.b64decode(''.join((n.text or '').split()),validate=True)
    from hashlib import sha256
    verify(sha256(data).hexdigest()==info['asset_hash'],'사진 원본이 바뀌었습니다.')
    with tempfile.TemporaryDirectory(prefix='hangul-crop-') as tmp:
        path=Path(tmp)/'source.png'
        path.write_bytes(data)
        with Image.open(path) as im:
            l,t,r,b=e['crop']
            if r>im.width or b>im.height or im.width*im.height>40_000_000:
                invalid('자르기 영역이 원본 픽셀 범위를 벗어납니다.')
        # Keep the original document and its backup intact. The edited copy
        # embeds a cropped raster; the unaffected objects retain their bytes.
        lines=[[{'type':'image','path':str(path),'crop':e['crop'],'dpi':96.0}]]
        i=p['index'];span=(i,a['start'],i,a['end'])
        ready();remove_object(hancom,before,before['targets'][e['target_id']])
        select(hancom.hwp,before,(i,a['start'],i,a['start']))
        write_lines(hancom,lines,ready)
        after=inspect(hancom,validate_target=ready)
        splice_result(before,after,span,lines)
        return after


def caption(hancom,before,e,ready,inspect):
    from .native_edit import controls,capture
    h=hancom.hwp;p,a=find(before,e['target_id']);anchor=(*p['native'],a['start'])
    ctrl=controls(h).get(anchor)
    if ctrl is None or ctrl.CtrlID!='gso':
        dm.fail('STALE_TARGET','캡션을 붙일 사진을 찾지 못했습니다.')
    ready();h.Cancel();check(h.set_pos(*anchor),'사진으로 이동하지 못했습니다.');h.FindCtrl()
    selected=capture(h).get('control')
    verify(selected=={'kind':'gso','position':list(anchor)},'다른 개체가 선택되었습니다.')
    check(h.Run('ShapeObjAttachCaption'),'사진 캡션을 만들지 못했습니다.')
    verify(h.get_pos()[0]!=anchor[0],'사진 캡션 내부로 이동하지 못했습니다.')
    h.MoveParaEnd()
    check(h.insert_text(e['text']),'사진 캡션을 입력하지 못했습니다.')
    h.Cancel();check(h.set_pos(0,0,0),'캡션 편집을 끝내지 못했습니다.')
    after=inspect(hancom,validate_target=ready);preserve(before,after)
    path=after.get('picture_paths',{})
    q=next(q for q in after['paragraphs'] if q['native']==p['native'])
    part=next(x for x in q['parts'] if x.get('type')=='PICTURE' and x['start']==a['start'])
    cap=node(part['value'],'CAPTION')
    verify(cap is not None,'사진에 캡션이 생기지 않았습니다.')
    para=node(cap,'P')
    runs=[n for run in para[3] if run[0]=='TEXT' for n in run[3]] if para else []
    numbers=[i for i,n in enumerate(runs) if n[0]=='AUTONUM' and n[1].get('NumberType')=='Figure']
    verify(len(numbers)==1,'그림 번호 뒤의 캡션 위치를 확인하지 못했습니다.')
    suffix=runs[numbers[0]+1:]
    verify(all(n[0]=='CHAR' for n in suffix) and ''.join(n[2] for n in suffix)==' '+e['text'],
           '캡션 글이 요청과 다릅니다.')
    reduced=copy.deepcopy(after);target_path=path.get(part['id'])
    verify(bool(target_path),'캡션 소유 사진을 확인하지 못했습니다.')
    reduced['paragraphs']=[x for x in reduced['paragraphs'] if not x['path'].startswith(target_path+'/')]
    target=next(x for x in reduced['paragraphs'] if x['native']==p['native'])
    candidate=next(x for x in target['parts'] if x['id']==part['id'])
    def strip(n):
        n[3]=[x for x in n[3] if x[0]!='CAPTION']
        for c in n[3]:strip(c)
    strip(candidate['value'])
    verify(list(map(snapshot,before['paragraphs']))==list(map(snapshot,reduced['paragraphs'])),
           '캡션 외의 사진이나 문서 내용이 달라졌습니다.')
    return after


def execute(hancom,before,e,ready,inspect):
    validate(before,e)
    return {'set_picture':set_shape,'crop_picture':crop,'caption_picture':caption}[e['type']](hancom,before,e,ready,inspect)
