"""Scoped paragraph, character, and page formatting for native HWP/HWPX."""
import copy
import math
import re
from . import document as dm
from .structure import atoms,check,invalid,range_for,select,semantic,snapshot,splice_result,table_snapshot,verify

KINDS={'set_character','set_paragraph','set_page','insert_break'}
CHARACTER={'bold','italic','underline','text_color'}
PARAGRAPH={'align','indent_pt','line_spacing_percent','page_break_before','style_name'}
PAGE={'width_mm','height_mm','orientation','left_mm','right_mm','top_mm','bottom_mm','header_mm','footer_mm'}
ALIGN={'left':'Left','center':'Center','right':'Right','justify':'Justify','distribute':'Distribute'}


def number(v,lo,hi,label):
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
        invalid(f'{label}은(는) {lo}~{hi} 범위의 숫자여야 합니다.')
    return v


def color(v):
    if not isinstance(v,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v):
        invalid('색은 #RRGGBB 형식이어야 합니다.')
    return int(v[1:3],16)+256*int(v[3:5],16)+65536*int(v[5:7],16)


def boolean(v):
    if type(v) is not bool:
        invalid('켜기·끄기에는 true 또는 false를 지정하세요.')
    return v


def page_control(doc,target):
    r=range_for(doc,target,'before');p=doc['paragraphs'][r[0]]
    if p['scope']!='body':
        invalid('용지 설정은 구역의 본문 문단을 지정하세요.')
    section=p['path'].split('/')[1]
    hits=[(i,a) for i,q in enumerate(doc['paragraphs']) if q['scope']=='body' and q['path'].split('/')[1]==section
          for a in q['parts'] if a.get('type')=='SECDEF']
    if len(hits)!=1:
        dm.fail('UNMAPPED_LOCATION','지정한 구역의 용지 정의를 확인하지 못했습니다.')
    return r,hits[0][0]


def validate(doc,e):
    k=e['type']
    if k=='insert_break':
        if e.get('break_type') not in ('page','section'):
            invalid('쪽 또는 구역 나누기를 지정하세요.')
        r=range_for(doc,e['target_id'],e.get('position','after'))
        if doc['paragraphs'][r[0]]['scope']!='body':
            invalid('쪽·구역 나누기는 본문에서만 할 수 있습니다.')
        return
    p=e.get('properties')
    if not isinstance(p,dict) or not p:
        invalid('변경할 서식 속성을 지정하세요.')
    allowed={'set_character':CHARACTER,'set_paragraph':PARAGRAPH,'set_page':PAGE}[k]
    if p.keys()-allowed:
        invalid('지원하지 않는 서식 속성이 있습니다.')
    if k=='set_character':
        r=range_for(doc,e['target_id'])
        if r[:2]==r[2:]:
            invalid('글자 서식을 바꿀 범위를 지정하세요.')
        for key,v in p.items():
            if key=='text_color':color(v)
            else:boolean(v)
    elif k=='set_paragraph':
        if 'style_name' in p:
            if len(p)!=1 or not isinstance(p['style_name'],str) or p['style_name'] not in doc.get('style_names',[]):
                invalid('문서에 정의된 스타일 이름 하나를 지정하세요.')
        if 'align' in p and p['align'] not in ALIGN:invalid('지원하지 않는 문단 정렬입니다.')
        if 'indent_pt' in p:number(p['indent_pt'],-300,300,'들여쓰기')
        if 'line_spacing_percent' in p:
            if type(p['line_spacing_percent']) is not int:invalid('줄 간격은 정수 퍼센트입니다.')
            number(p['line_spacing_percent'],50,500,'줄 간격')
        if 'page_break_before' in p:boolean(p['page_break_before'])
        for r in dm.expand(doc,e['target_id']):
            range_for(doc,dm.add_target(doc,r),'before')
    else:
        page_control(doc,e['target_id'])
        for key,v in p.items():
            if key=='orientation':
                if v not in ('portrait','landscape'):invalid('용지 방향을 지정하세요.')
            else:number(v,30 if key in ('width_mm','height_mm') else 0,1000,key)


def preserve(before,after):
    verify(table_snapshot(before)==table_snapshot(after) and before['bookmarks']==after['bookmarks']
           and before.get('structure_metadata')==after.get('structure_metadata'),'표·책갈피·검토 정보가 달라졌습니다.')


def mask_char(a,p,wanted):
    a=semantic(a)
    if a['kind']!='text':return a
    other=copy.deepcopy(a['style']['other'])
    for name in ('bold','italic','underline'):
        if name in p:
            exists=any(n[0]==name.upper() and (name!='underline' or n[1].get('Type')!='None') for n in other[3])
            if wanted:verify(exists==p[name],'요청한 글자 모양이 적용되지 않았습니다.')
            other[3]=[n for n in other[3] if n[0]!=name.upper()]
    if 'text_color' in p:
        if wanted:verify(int(other[1].get('TextColor','0'))==color(p['text_color']),'요청한 글자색이 적용되지 않았습니다.')
        other[1].pop('TextColor',None)
    a['style']=dict(a['style'],other=other)
    return a


def character(hancom,before,e,ready,inspect):
    a,lo,b,hi=range_for(before,e['target_id']);h=hancom.hwp;p=e['properties']
    ready();select(h,before,(a,lo,b,hi))
    act=h.create_action('CharShape');ps=act.CreateSet();act.GetDefault(ps)
    for key,item in [('bold','Bold'),('italic','Italic'),('underline','UnderlineType')]:
        if key in p:ps.SetItem(item,int(p[key]))
    if 'text_color' in p:ps.SetItem('TextColor',color(p['text_color']))
    check(act.Execute(ps),'글자 서식을 바꾸지 못했습니다.')
    h.Cancel();after=inspect(hancom,validate_target=ready);preserve(before,after)
    verify(len(before['paragraphs'])==len(after['paragraphs']),'문단 수가 달라졌습니다.')
    for i,(old,new) in enumerate(zip(before['paragraphs'],after['paragraphs'])):
        if not a<=i<=b:
            verify(snapshot(old)==snapshot(new),'선택 범위 밖 서식이 달라졌습니다.');continue
        verify(snapshot(old)[:-1]==snapshot(new)[:-1],'글자 이외의 문단 속성이 달라졌습니다.')
        def result(q,wanted):
            return [mask_char(x,p,wanted) if (i!=a or x['start']>=lo) and (i!=b or x['end']<=hi) else semantic(x) for x in atoms(q)]
        verify(result(old,False)==result(new,True),'요청하지 않은 글자 속성이 달라졌습니다.')
    return after


def mask_para(p,props,wanted):
    out=snapshot(p)
    if 'style_name' in props:
        if wanted:verify(p['style'].get('Name')==props['style_name'],'요청한 스타일이 적용되지 않았습니다.')
        out[2]=out[3]=None
        out[-1]=[{k:v for k,v in a.items() if k!='style'} for a in out[-1]]
        return out
    shape=out[2]
    for key,prop in [('align','Align'),('page_break_before','PageBreakBefore')]:
        if key in props:
            expect=ALIGN[props[key]] if key=='align' else str(props[key]).lower()
            if wanted:verify(shape[1].get(prop)==expect,'요청한 문단 속성이 적용되지 않았습니다.')
            shape[1].pop(prop,None)
    if props.keys()&{'indent_pt','line_spacing_percent'}:
        margin=next(n[1] for n in shape[3] if n[0]=='PARAMARGIN')
        if 'indent_pt' in props:
            if wanted:verify(int(margin['Indent'])==round(props['indent_pt']*200),'요청한 들여쓰기가 적용되지 않았습니다.')
            margin.pop('Indent')
        if 'line_spacing_percent' in props:
            if wanted:verify(margin.get('LineSpacingType')=='Percent' and int(margin['LineSpacing'])==props['line_spacing_percent'],
                             '요청한 줄 간격이 적용되지 않았습니다.')
            margin.pop('LineSpacing');margin.pop('LineSpacingType',None)
    return out


def paragraph(hancom,before,e,ready,inspect):
    h=hancom.hwp;props=e['properties']
    indices=sorted({r['paragraph'] for r in dm.expand(before,e['target_id'])})
    for i in indices:
        p=before['paragraphs'][i];ready();h.Cancel();check(h.set_pos(*p['native'],0),'문단으로 이동하지 못했습니다.')
        if 'style_name' in props:
            check(h.set_style(props['style_name']),'문단 스타일을 적용하지 못했습니다.');continue
        a=h.create_action('ParagraphShape');s=a.CreateSet();a.GetDefault(s)
        if 'align' in props:s.SetItem('AlignType',h.HAlign(ALIGN[props['align']]))
        if 'indent_pt' in props:s.SetItem('Indentation',round(props['indent_pt']*200))
        if 'line_spacing_percent' in props:
            s.SetItem('LineSpacingType',0);s.SetItem('LineSpacing',props['line_spacing_percent'])
        if 'page_break_before' in props:s.SetItem('PagebreakBefore',int(props['page_break_before']))
        check(a.Execute(s),'문단 속성을 변경하지 못했습니다.')
    after=inspect(hancom,validate_target=ready);preserve(before,after)
    verify(len(before['paragraphs'])==len(after['paragraphs']),'문단 수가 달라졌습니다.')
    for i,(old,new) in enumerate(zip(before['paragraphs'],after['paragraphs'])):
        verify((mask_para(old,props,False)==mask_para(new,props,True) if i in indices else snapshot(old)==snapshot(new)),
               '요청하지 않은 문단 내용·속성이 달라졌습니다.')
    return after


def page(hancom,before,e,ready,inspect):
    h=hancom.hwp;props=e['properties'];where,index=page_control(before,e['target_id'])
    ready();select(h,before,where)
    ps=h.HParameterSet.HSecDef
    h.HAction.GetDefault('PageSetup',ps.HSet)
    names={'width_mm':'PaperWidth','height_mm':'PaperHeight','left_mm':'LeftMargin','right_mm':'RightMargin',
           'top_mm':'TopMargin','bottom_mm':'BottomMargin','header_mm':'HeaderLen','footer_mm':'FooterLen'}
    values={names[k]:round(h.MiliToHwpUnit(v)) for k,v in props.items() if k!='orientation'}
    if 'orientation' in props:values['Landscape']=int(props['orientation']=='landscape')
    def prop(k):return values.get(k,getattr(ps.PageDef,k))
    if prop('LeftMargin')+prop('RightMargin')+ps.PageDef.GutterLen>=prop('PaperWidth') or prop('TopMargin')+prop('BottomMargin')>=prop('PaperHeight'):
        invalid('여백이 용지 크기를 초과합니다.')
    for k,v in values.items():setattr(ps.PageDef,k,v)
    ps.HSet.SetItem('ApplyTo',2)
    check(h.HAction.Execute('PageSetup',ps.HSet),'구역 용지 설정을 변경하지 못했습니다.')
    h.HAction.GetDefault('PageSetup',ps.HSet)
    verify(all(abs(int(getattr(ps.PageDef,k))-v)<=1 for k,v in values.items()),'요청한 용지 설정과 결과가 다릅니다.')
    after=inspect(hancom,validate_target=ready);preserve(before,after)
    verify(len(before['paragraphs'])==len(after['paragraphs']),'구역 설정이 문단 수를 바꿨습니다.')
    def mask(p):
        result=snapshot(p)
        for a in result[-1]:
            if a.get('type')=='SECDEF':
                def visit(n):
                    if n[0] in ('PAGEDEF','PAGEMARGIN','PAGEMARGINS'):
                        keys={'width_mm':'Width','height_mm':'Height','left_mm':'Left','right_mm':'Right','top_mm':'Top',
                              'bottom_mm':'Bottom','header_mm':'Header','footer_mm':'Footer','orientation':'Landscape'}
                        for key in props:n[1].pop(keys[key],None)
                        if 'orientation' in props:
                            for k in ('Width','Height'):n[1].pop(k,None)
                    for c in n[3]:visit(c)
                visit(a['value'])
        return result
    for i,(old,new) in enumerate(zip(before['paragraphs'],after['paragraphs'])):
        verify((mask(old)==mask(new) if i==index else snapshot(old)==snapshot(new)),
               '요청한 구역의 용지 설정 외에 다른 내용이 변경됐습니다.')
    return after


def insert_break(hancom,before,e,ready,inspect):
    span=range_for(before,e['target_id'],e.get('position','after'))
    h=hancom.hwp;kind=e['break_type']
    ready();select(h,before,span)
    check(h.Run('BreakPage' if kind=='page' else 'BreakSection'),'쪽·구역을 나누지 못했습니다.')
    after=inspect(hancom,validate_target=ready)
    i=span[0]+1
    delta=len(after['paragraphs'])-len(before['paragraphs'])
    if delta==0:
        source=before['paragraphs'][span[0]]
        sibling=next((p['index'] for p in before['paragraphs'][span[0]+1:]
                      if p['scope']=='body' and p['path'].rsplit('/',1)[0]==source['path'].rsplit('/',1)[0]),None)
        i=span[0] if span[1]==0 else sibling if span[1]==source['length'] else None
        verify(i is not None,'기존 문단 경계에서 나누기 위치를 확인하지 못했습니다.')
    else:
        verify(delta==1,'쪽·구역 나누기의 문단 구조가 다릅니다.')
    reduced=copy.deepcopy(after)
    q=reduced['paragraphs'][i]
    if kind=='page':
        verify(q['attributes'].get('PageBreak')=='true','쪽 나누기 표시를 확인하지 못했습니다.')
        if delta==0:
            q['attributes']=dict(q['attributes'])
            previous=before['paragraphs'][i]['attributes']
            if 'PageBreak' in previous:q['attributes']['PageBreak']=previous['PageBreak']
            else:q['attributes'].pop('PageBreak',None)
            if 'ColumnBreak' not in previous and q['attributes'].get('ColumnBreak')=='false':
                q['attributes'].pop('ColumnBreak',None)
    else:
        verify(len({p['path'].split('/')[1] for p in after['paragraphs']})==len({p['path'].split('/')[1] for p in before['paragraphs']})+1,
               '새 구역이 만들어지지 않았습니다.')
        controls=[x for x in q['parts'] if x.get('type') in ('SECDEF','COLDEF')]
        verify(any(x.get('type')=='SECDEF' for x in controls),'새 구역 정의를 확인하지 못했습니다.')
        q['parts']=[x for x in q['parts'] if x not in controls]
    if delta:
        splice_result(before,reduced,span,[[],[]])
    else:
        preserve(before,reduced)
        verify(list(map(snapshot,before['paragraphs']))==list(map(snapshot,reduced['paragraphs'])),
               '나누기 표시 외에 기존 내용·서식이 달라졌습니다.')
    return after


def execute(hancom,before,e,ready,inspect):
    validate(before,e)
    return {'set_character':character,'set_paragraph':paragraph,'set_page':page,'insert_break':insert_break}[e['type']](
        hancom,before,e,ready,inspect)
