"""Verify native region edits against the owner and all other document flows."""
from . import document as dm
from .structure import atoms,check,invalid,range_for,select,snapshot,table_snapshot,verify

ACTIONS={'add_footnote','add_endnote','add_header','add_footer','add_memo',
         'replace_text','delete','set_page_number'}
CONTROL={'footnote':'fn','endnote':'en','header':'head','footer':'foot','memo':'%%me','pagenum':'pgnp'}
NUMBERS={'none':(0,'None'),'top_left':(1,'TopLeft'),'top_center':(2,'TopCenter'),
         'top_right':(3,'TopRight'),'bottom_left':(4,'BottomLeft'),
         'bottom_center':(5,'BottomCenter'),'bottom_right':(6,'BottomRight')}


def region_for(doc,key):
    entry=doc['targets'].get(key)
    if not entry or entry.get('kind')!='control':
        invalid('구역 개체 또는 메모의 ID를 지정하세요.')
    p=doc['paragraphs'][entry['paragraph']]
    a=next((a for a in p['parts'] if a['start']==entry['start'] and a['end']==entry['end']),None)
    hit=next((r for r in doc.get('regions',[]) if a and r['target_id']==a['id']),None)
    if not hit or not p['mapped']:
        dm.fail('UNMAPPED_LOCATION','구역 개체의 정확한 위치를 확인하지 못했습니다.')
    return hit,p,a


def children(doc,r):
    return [p for p in doc['paragraphs'] if p['path'].startswith(r['path']+'/')]


def validate(doc,e):
    action=e.get('action')
    if action not in ACTIONS:
        invalid('지원하지 않는 쪽·각주·메모 작업입니다.')
    if action.startswith('add_') or action=='replace_text':
        text=e.get('text')
        if not isinstance(text,str) or not 1<=len(text)<=16000 or any(ord(c)<32 for c in text):
            invalid('줄바꿈 없는 구역 또는 메모 텍스트를 지정하세요.')
    if action in ('replace_text','delete'):
        r,_,_=region_for(doc,e['target_id'])
        if action=='replace_text':
            pp=children(doc,r)
            if r['kind'] not in ('header','footer','footnote','endnote','memo') or len(pp)!=1 or (r['kind']!='memo' and not pp[0]['mapped']):
                dm.fail('UNVERIFIED_REGION','현재 교체 가능한 대상은 검증된 단일 문단 머리말·꼬리말·각주·미주·메모입니다.')
            if any(a['kind']!='text' and a.get('type')!='AUTONUM' for a in pp[0]['parts']):
                dm.fail('PROTECTED_RANGE','구역 안의 다른 개체를 덮어쓰지 않습니다.')
        return
    span=range_for(doc,e['target_id'],None if action=='add_memo' else e.get('position','after'))
    p=doc['paragraphs'][span[0]]
    if action=='add_memo' and (span[0]!=span[2] or span[1]==span[3]):
        invalid('메모를 붙일 한 문단 안의 글자 범위를 지정하세요.')
    if action in ('add_header','add_footer','set_page_number') and p['scope']!='body':
        invalid('구역의 본문을 지정하세요.')
    if action=='set_page_number' and e.get('number_position') not in NUMBERS:
        invalid('지원되는 쪽 번호 위치를 지정하세요.')
    if action in ('add_header','add_footer'):
        sect=int(p['path'].split('/')[1])+1
        if any(x['kind']==action[4:] and x['section']==sect for x in doc.get('regions',[])):
            invalid('이 구역에 이미 같은 머리말·꼬리말이 있습니다. 기존 개체를 지정하세요.')


def shape_without(doc,regions):
    skip=[r['path']+'/' for r in regions]
    parents={}
    for r in regions:
        parents.setdefault(r['paragraph_index'],[]).append(r)
    result=[]
    for p in doc['paragraphs']:
        if any(p['path'].startswith(path) for path in skip):
            continue
        q=p
        if p['index'] in parents:
            objects=parents[p['index']]
            ids={r['target_id'] for r in objects}
            field_ids={r['properties'].get('FieldId') for r in objects if r['kind']=='memo'}
            q=dict(p,parts=[a for a in p['parts'] if a['id'] not in ids and not (
                a.get('type')=='FIELDEND' and a['value'][1].get('FieldId') in field_ids)])
        result.append(snapshot(q))
    return result


def preservation(before,after,old,new):
    verify(shape_without(before,old)==shape_without(after,new) and before['bookmarks']==after['bookmarks']
           and table_snapshot(before)==table_snapshot(after),'지정 구역 밖의 내용·서식·표·책갈피가 달라졌습니다.')


def signature(r):
    # Paragraph indexes shift with the child flow; target IDs include revisions.
    return (r['kind'],r['section'],r['text'],{k:v for k,v in r['properties'].items() if k!='InstId'})


def new_region(before,after,kind,section,expected):
    from collections import Counter
    old=Counter(dm.encode(signature(r)) for r in before.get('regions',[]))
    additions=[]
    for r in after.get('regions',[]):
        sig=dm.encode(signature(r))
        if old[sig]:old[sig]-=1
        else:additions.append(r)
    verify(len(additions)==1 and not any(old.values()),'기존 구역 개체가 달라졌거나 추가한 개체를 특정하지 못했습니다.')
    r=additions[0]
    verify(r['kind']==kind and r['section']==section,'새 구역 개체의 종류 또는 위치가 다릅니다.')
    text=r['text'].removeprefix(' ') if kind in ('footnote','endnote') else r['text']
    verify(text==expected,'새 구역에 입력한 내용이 요청과 다릅니다.')
    return r


def body_position(h):
    h.Cancel();check(h.set_pos(0,0,0),'구역 편집을 끝내지 못했습니다.')


def execute(hancom,before,e,ready,inspect):
    from .native_edit import controls
    validate(before,e);h=hancom.hwp;action=e['action']
    old=[];new=[];ready()
    if action in ('replace_text','delete'):
        reg,p,a=region_for(before,e['target_id']);old=[reg]
        if action=='delete':
            c=controls(h).get((*p['native'],a['start']))
            if c is None or c.CtrlID!=CONTROL[reg['kind']]:
                dm.fail('STALE_TARGET','삭제할 구역 개체의 종류나 위치가 다릅니다.')
            check(h.delete_ctrl(c),'지정한 구역 개체를 삭제하지 못했습니다.')
            after=inspect(hancom,validate_target=ready)
        else:
            q=children(before,reg)[0];text_parts=[x for x in q['parts'] if x['kind']=='text']
            lo=text_parts[0]['start'] if text_parts else q['length']
            if reg['kind']=='memo':
                h.Cancel();check(h.set_pos(*p['native'],a['end']),'메모의 본문 범위로 이동하지 못했습니다.')
                # 2022 returns false even when the caret enters the memo.
                h.Run('EditFieldMemo')
                pos=tuple(map(int,h.get_pos()))
                verify(pos[0]!=p['native'][0],'지정 메모 내부로 이동하지 못했습니다.')
                h.MoveParaEnd()
                verify(tuple(map(int,h.get_pos()))==(*pos[:2],q['length']),'메모 길이가 문서 구조와 다릅니다.')
                if q['length']:
                    check(h.select_text_by_get_pos((*pos[:2],0),(*pos[:2],q['length'])),'메모 글 범위를 선택하지 못했습니다.')
                    verify(h.get_text_file('UNICODE','saveblock:true')==reg['text'],'실제 메모의 기존 글이 다릅니다.')
            else:
                select(h,before,(q['index'],lo,q['index'],q['length']))
            prefix=' ' if reg['kind'] in ('footnote','endnote') and reg['text'].startswith(' ') else ''
            check(h.insert_text(prefix+e['text']),'구역의 글을 교체하지 못했습니다.')
            if reg['kind']=='memo':
                h.Run('Close')
            body_position(h);after=inspect(hancom,validate_target=ready)
            matches=[r for r in after['regions'] if r['kind']==reg['kind'] and r['path']==reg['path']]
            verify(len(matches)==1 and matches[0]['text']==prefix+e['text'],'지정 구역의 교체 결과를 확인하지 못했습니다.')
            if reg['kind']=='memo':verify(matches[0]['properties'].get('FieldId')==reg['properties'].get('FieldId'),'기존 메모 관계가 달라졌습니다.')
            new=matches
    else:
        span=range_for(before,e['target_id'],None if action=='add_memo' else e.get('position','after'))
        p=before['paragraphs'][span[0]];section=int(p['path'].split('/')[1])+1
        select(h,before,span)
        if action=='set_page_number':
            number,expected=NUMBERS[e['number_position']]
            old=[r for r in before['regions'] if r['kind']=='pagenum' and r['section']==section]
            verify(len(old)<=1,'한 구역 안의 쪽 번호 설정을 하나로 특정하지 못했습니다.')
            a=h.create_action('PageNumPos');s=a.CreateSet();a.GetDefault(s)
            s.SetItem('DrawPos',number)
            check(a.Execute(s),'쪽 번호 위치를 설정하지 못했습니다.')
            after=inspect(hancom,validate_target=ready)
            new=[r for r in after['regions'] if r['kind']=='pagenum' and r['section']==section]
            if number:
                verify(len(new)==1 and new[0]['properties'].get('Pos')==expected,'요청한 쪽 번호 위치를 확인하지 못했습니다.')
            else:
                verify(not new or all(r['properties'].get('Pos')==expected for r in new),'쪽 번호가 제거되지 않았습니다.')
        else:
            kind=action[4:]
            if kind in ('header','footer'):
                a=h.create_action('HeaderFooter');s=a.CreateSet();a.GetDefault(s)
                s.SetItem('HeaderFooterCtrlType',int(kind=='footer'));s.SetItem('HeaderFooterStyle',0)
                check(a.Execute(s),'머리말·꼬리말을 만들지 못했습니다.')
            else:
                check(h.Run({'footnote':'InsertFootnote','endnote':'InsertEndnote','memo':'InsertFieldMemo'}[kind]),
                      '각주·미주·메모를 만들지 못했습니다.')
            verify(int(h.get_pos()[0])!=int(p['native'][0]),'새 구역 안으로 이동하지 못했습니다.')
            check(h.insert_text(e['text']),'새 구역에 글을 입력하지 못했습니다.')
            body_position(h);after=inspect(hancom,validate_target=ready)
            new=[new_region(before,after,kind,section,e['text'])]
            owner=after['paragraphs'][new[0]['paragraph_index']]
            part=next(a for a in owner['parts'] if a['id']==new[0]['target_id'])
            if kind in ('footnote','endnote','memo'):
                verify(owner['native']==p['native'] and part['start']==span[1],'추가한 개체의 본문 기준점이 다릅니다.')
            if kind=='memo':
                end=[a for a in owner['parts'] if a.get('type')=='FIELDEND' and
                     a['value'][1].get('FieldId')==new[0]['properties'].get('FieldId')]
                verify(len(end)==1 and end[0]['start']==span[3]+8,'메모가 선택한 글 범위를 벗어났습니다.')
    preservation(before,after,old,new)
    return after
