"""Format a selected table fragment without opening the property dialog."""
import copy
from xml.etree import ElementTree as ET

from . import document as dm,xmlcheck
from .format_edit import color,number
from .structure import check,import_object_fragment,invalid,verify
from .table_edit import area,body_outside,data,other_nested,outside_tables,same_table,table_for

PROPERTIES={'width_mm','height_mm','background','border_color','border_style','vertical_align'}


def validate(doc,e):
    t=table_for(doc,e['target_id']);cells=data(doc,t)
    bounds=e.get('range',[1,1,t['rows'],t['columns']])
    if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) is not int for v in bounds):
        invalid('표 서식 범위에는 [위 행, 왼쪽 열, 아래 행, 오른쪽 열]을 지정하세요.')
    r,c,b,d=bounds
    if not (1<=r<=b<=t['rows'] and 1<=c<=d<=t['columns']):
        invalid('셀 범위가 표를 벗어납니다.')
    chosen=area(cells,bounds);props=e.get('properties')
    if not isinstance(props,dict) or not props or props.keys()-PROPERTIES:
        invalid('지원되는 셀 서식을 지정하세요.')
    for k,v in props.items():
        if k in ('width_mm','height_mm'):number(v,0.5,500,k)
        elif k in ('background','border_color'):color(v)
        elif k=='border_style' and v not in ('solid','none'):invalid('테두리 종류는 solid 또는 none입니다.')
        elif k=='vertical_align' and v not in ('top','center','bottom'):invalid('셀 세로 정렬은 top, center 또는 bottom입니다.')
    return t,cells,set(chosen)


def fragment_cells(table):
    return {(int(c.get('RowAddr','0'))+1,int(c.get('ColAddr','0'))+1):c
            for row in table if xmlcheck.tag(row)=='ROW' for c in row if xmlcheck.tag(c)=='CELL'}


def set_border(definition,props):
    if 'background' in props:
        for c in list(definition):
            if xmlcheck.tag(c)=='FILLBRUSH':definition.remove(c)
        fill=ET.SubElement(definition,'FILLBRUSH')
        ET.SubElement(fill,'WINDOWBRUSH',FaceColor=str(color(props['background'])),HatchColor='0',Alpha='0')
    for edge in ('LEFTBORDER','TOPBORDER','RIGHTBORDER','BOTTOMBORDER'):
        if not props.keys()&{'border_color','border_style'}:break
        n=next((c for c in definition if xmlcheck.tag(c)==edge),None)
        if n is None:n=ET.SubElement(definition,edge,Type='Solid',Width='0.12 mm',Color='0')
        if 'border_color' in props:n.set('Color',str(color(props['border_color'])))
        if 'border_style' in props:n.set('Type',props['border_style'].capitalize())


def execute(hancom,before,e,ready,inspect):
    from .native_edit import capture,controls
    h=hancom.hwp;t,old,chosen=validate(before,e);props=e['properties']
    anchor=tuple(t['_anchor']);ctrl=controls(h).get(anchor)
    if ctrl is None or ctrl.CtrlID!='tbl':
        dm.fail('STALE_TARGET','서식을 바꿀 표를 찾지 못했습니다.')
    ready();h.Cancel();check(h.set_pos(*anchor),'표의 위치로 이동하지 못했습니다.')
    h.FindCtrl();verify(capture(h).get('control')=={'kind':'tbl','position':list(anchor)},'다른 개체가 선택되었습니다.')
    fragment=h.get_text_file('HWPML2X','saveblock:true')
    root=xmlcheck.parse(fragment)
    table=next((n for n in root.iter() if xmlcheck.tag(n)=='TABLE'),None)
    verify(table is not None,'선택한 표를 조각으로 내보내지 못했습니다.')
    cells=fragment_cells(table)
    verify(set(cells)==set(old),'표 조각의 셀 구성이 원본과 다릅니다.')
    maps=next((n for n in root.iter() if xmlcheck.tag(n)=='BORDERFILLLIST'),None)
    styles={n.get('Id'):n for n in maps or [] if xmlcheck.tag(n)=='BORDERFILL'}
    newid=max((int(k) for k in styles),default=0)+1
    remap={};expected={}
    for key,c in cells.items():
        if key in chosen:
            if 'width_mm' in props:c.set('Width',str(round(h.MiliToHwpUnit(props['width_mm']))))
            if 'height_mm' in props:c.set('Height',str(round(h.MiliToHwpUnit(props['height_mm']))))
            if 'vertical_align' in props:
                pl=next((n for n in c if xmlcheck.tag(n)=='PARALIST'),None)
                verify(pl is not None,'셀의 문단 목록을 확인하지 못했습니다.')
                pl.set('VertAlign',props['vertical_align'].capitalize())
            if props.keys()&{'background','border_color','border_style'}:
                k=c.get('BorderFill')
                verify(k in styles and maps is not None,'기존 셀 테두리·배경을 확인하지 못했습니다.')
                if k not in remap:
                    n=copy.deepcopy(styles[k]);set_border(n,props)
                    newkey=str(newid);newid+=1;n.set('Id',newkey)
                    maps.append(n);styles[newkey]=n;remap[k]=newkey
                    maps.set('Count',str(len(maps)))
                c.set('BorderFill',remap[k])
        pl=next((n for n in c if xmlcheck.tag(n)=='PARALIST'),None)
        expected[key]={'cell':{k:v for k,v in c.attrib.items() if k!='BorderFill'},
                       'border':dm.canonical(styles[c.get('BorderFill')],('Id',)) if c.get('BorderFill') in styles else None,
                       'vertical':pl.get('VertAlign','Top') if pl is not None else None}
    ready();check(h.delete_ctrl(ctrl),'지정 표 조각을 교체하지 못했습니다.')
    h.Cancel();check(h.set_pos(*anchor),'표를 다시 넣을 위치를 찾지 못했습니다.')
    import_object_fragment(h,ET.tostring(root,encoding='utf-16').decode('utf-16'),'HWPML2X')
    h.Cancel();after=inspect(hancom,validate_target=ready);newt=same_table(after,t)
    verify((newt['rows'],newt['columns'])==(t['rows'],t['columns']),'표의 행·열 수가 바뀌었습니다.')
    new=data(after,newt)
    verify(set(new)==set(old),'표의 셀 구성이 달라졌습니다.')
    for k in old:
        verify(old[k]['span']==new[k]['span'] and old[k]['payload']==new[k]['payload'],'표 서식 변경으로 셀 내용·병합 상태가 달라졌습니다.')
    for c,pl in newt['cell_attributes']:
        k=(int(c.get('RowAddr','0'))+1,int(c.get('ColAddr','0'))+1)
        want=expected[k];actual={q:v for q,v in c.items() if q!='BorderFill'}
        verify(actual==want['cell'],'요청한 셀 크기 또는 기타 속성이 다릅니다.')
        verify(pl.get('VertAlign','Top')==want['vertical'],'요청한 셀 세로 정렬이 다릅니다.')
        border=after['border_definitions'].get(c.get('BorderFill'))
        verify(border==want['border'],'요청한 셀 테두리·배경이 다릅니다.')
    verify(body_outside(before,t)==body_outside(after,newt) and outside_tables(before,t)==outside_tables(after,newt)
           and other_nested(before,t)==other_nested(after,newt) and before['bookmarks']==after['bookmarks'],
           '지정한 표 바깥의 내용·서식·책갈피가 달라졌습니다.')
    return after
