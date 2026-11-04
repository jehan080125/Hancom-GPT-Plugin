"""Native table operations with independent cell-grid and content checks."""
from collections import defaultdict
from . import document as dm
from .structure import check, verify, invalid, positive, stable, snapshot, coords, atoms, semantic

ACTIONS={'insert_rows','insert_columns','delete_rows','delete_columns','clear_cells','merge_cells','split_cell'}


def table_for(doc,key):
    entry=doc['targets'].get(key)
    if not entry or entry.get('kind')!='control':
        invalid('find_targets의 table_object 결과를 지정하세요.')
    p=doc['paragraphs'][entry['paragraph']]
    table=next((t for t in doc['tables'] if t['xml_target_id']==key),None)
    if table is None:
        # IDs are revision-bound; a carried handle may differ from the new ID.
        table=next((t for t in doc['tables'] if t.get('_anchor')==[*p['native'],entry['start']]),None)
    if table is None or not table.get('_anchor') or not p.get('mapped'):
        dm.fail('UNMAPPED_LOCATION','실제 표 개체를 확인하지 못했습니다.')
    return table


def context(p,t):
    return next((i for i,x in enumerate(p['cell_path']) if x.get('table')==t['number']),None)


def data(doc,t):
    cells={}
    for p in doc['paragraphs']:
        i=context(p,t)
        if i is None:
            continue
        c=p['cell_path'][i+1]
        key=(c['row'],c['column'])
        record=cells.setdefault(key,{'span':(c['row_span'],c['column_span']),'payload':[],'first':None})
        if record['first'] is None and len(p['cell_path'])==i+2 and p.get('mapped'):
            record['first']=[*p['native'],0]
        q=snapshot(p)
        q[1]=q[1][:i+1]+q[1][i+2:]
        record['payload'].append(q)
    return cells


def area(cells,bounds):
    top,left,bottom,right=bounds
    selected=[]
    for (r,c),v in sorted(cells.items()):
        rr,cc=v['span'];end_r,end_c=r+rr-1,c+cc-1
        if r>bottom or c>right or end_r<top or end_c<left:
            continue
        if r<top or c<left or end_r>bottom or end_c>right:
            dm.fail('PARTIAL_MERGED_CELL','범위가 병합 셀의 일부만 포함합니다.')
        selected.append((r,c))
    if sum(cells[k]['span'][0]*cells[k]['span'][1] for k in selected)!=(bottom-top+1)*(right-left+1):
        invalid('완전한 셀 직사각형을 지정하세요.')
    return selected


def compile_change(doc,e):
    t=table_for(doc,e['target_id']);cells=data(doc,t)
    action=e.get('action')
    if action not in ACTIONS:
        invalid('지원하지 않는 표 변경입니다.')
    rows,cols=t['rows'],t['columns']
    if action in ('clear_cells','merge_cells','split_cell'):
        bounds=e.get('range')
        if not isinstance(bounds,list) or len(bounds)!=4:
            invalid('range에 [위 행, 왼쪽 열, 아래 행, 오른쪽 열]을 지정하세요.')
        top,left,bottom,right=bounds
        for n,limit in zip(bounds,(rows,cols,rows,cols)):
            positive(n,limit,'셀 주소')
        if top>bottom or left>right:
            invalid('셀 범위의 순서를 확인하세요.')
        selected=area(cells,bounds)
        if action=='merge_cells' and len(selected)<2:
            invalid('서로 다른 셀을 두 개 이상 지정하세요.')
        if action=='split_cell':
            if len(selected)!=1 or cells[selected[0]]['span']==(1,1):
                invalid('분할할 병합 셀 하나의 전체 영역을 지정하세요.')
        return t,cells,selected
    axis=0 if action.endswith('rows') else 1
    size=(rows,cols)[axis];adding=action.startswith('insert')
    at=positive(e.get('index'),size+adding,'행·열 번호')
    count=positive(e.get('count',1),100,'행·열 수')
    if adding:
        if (size+count)*(cols if axis==0 else rows)>1000:
            invalid('확장한 표는 1,000셀 이내여야 합니다.')
        for key,v in cells.items():
            if key[axis]<at<key[axis]+v['span'][axis]:
                dm.fail('PARTIAL_MERGED_CELL','추가 위치가 병합 셀을 가릅니다.')
        # The other axis can contain merged cells; select an actual cell
        # anchored at the insertion edge, not an inferred coordinate.
        edge=min(at,size)
        if not any(k[axis]==edge and cells[k]['first'] for k in cells):
            dm.fail('UNMAPPED_LOCATION','행·열의 삽입 기준 셀을 찾지 못했습니다.')
    else:
        if count>=size or at+count-1>size:
            invalid('표에 행과 열을 각각 하나 이상 남겨야 합니다. 표 전체는 개체 삭제를 사용하세요.')
        bounds=[at,1,at+count-1,cols] if axis==0 else [1,at,rows,at+count-1]
        area(cells,bounds)
    return t,cells,None


def begin(h,p):
    if not p:
        dm.fail('UNMAPPED_LOCATION','셀 시작 위치가 확인되지 않았습니다.')
    h.Cancel()
    check(h.set_pos(*p),'지정 셀로 이동하지 못했습니다.')


def select_cells(h,cells,keys,t):
    from .native_edit import cell_address,restore_cells
    first,last=keys[0],keys[-1]
    restore_cells(h,{'first':cells[first]['first'],'last_address':cell_address(*last),
                     'addresses':[cell_address(*k) for k in keys]})
    ctrl=h.ParentCtrl;anchor=ctrl.GetAnchorPos(0)
    verify(ctrl.CtrlID=='tbl' and [int(anchor.Item(k)) for k in ('List','Para','Pos')]==t['_anchor'],
           '선택한 셀이 다른 표에 있습니다.')


def empty_payload(payload):
    return len(payload)==1 and all(a['kind']=='empty' for a in payload[0][-1])


def body_outside(doc,t):
    return [snapshot(p) for p in doc['paragraphs'] if context(p,t) is None]


def outside_tables(doc,t):
    return [stable(x.get('direct_geometry')) for x in doc['tables'] if not any(
        p.get('table')==t['number'] for p in x['path'])]


def other_nested(doc,t):
    return [stable(x.get('direct_geometry')) for x in doc['tables'] if x is not t and any(
        p.get('table')==t['number'] for p in x['path'])]


def same_table(doc,t):
    result=next((x for x in doc['tables'] if x.get('_anchor')==t['_anchor']),None)
    verify(result is not None,'편집한 표의 위치를 다시 확인하지 못했습니다.')
    return result


def execute(hancom,before,e,ready,inspect):
    h=hancom.hwp
    t,cells,selected=compile_change(before,e)
    expected={key:(v['span'],v['payload']) for key,v in cells.items()}
    rows,cols=t['rows'],t['columns']
    action=e['action'];added=set();emptied=set()
    nested=other_nested(before,t)
    ready()
    if action in ('clear_cells','merge_cells','split_cell'):
        if action=='clear_cells':
            # Deleting a block with nested tables also removes their
            # controls; leave such blocks to explicit object deletion.
            if any(any(len(p[1])>len(t['path']) for p in cells[k]['payload']) for k in selected):
                invalid('중첩 표가 있는 셀은 중첩 표부터 명시적으로 삭제하세요.')
            from .native_edit import cell_address
            from .structure import select
            for k in reversed(selected):
                if empty_payload(cells[k]['payload']):
                    continue
                ready();begin(h,cells[k]['first'])
                verify(h.get_cell_addr().upper()==cell_address(*k),'다른 셀이 선택됐습니다.')
                indices=[p['index'] for p in before['paragraphs'] if context(p,t) is not None and
                         (p['cell_path'][context(p,t)+1]['row'],p['cell_path'][context(p,t)+1]['column'])==k]
                first,last=indices[0],indices[-1]
                select(h,before,(first,0,last,before['paragraphs'][last]['length']))
                check(h.Run('Delete'),'셀 내용을 지우지 못했습니다.')
            emptied=set(selected)
        elif action=='merge_cells':
            if any(any(len(p[1])>len(t['path']) for p in cells[k]['payload']) for k in selected):
                invalid('중첩 표를 포함한 셀의 병합은 지원하지 않습니다.')
            select_cells(h,cells,selected,t)
            check(h.TableMergeCell(),'선택 셀을 병합하지 못했습니다.')
            top,left,bottom,right=e['range']
            keep=[p for k in selected for p in expected.pop(k)[1] if any(a['kind']!='empty' for a in p[-1])]
            expected[top,left]=((bottom-top+1,right-left+1),keep)
            if not keep:emptied.add((top,left))
        else:
            key=selected[0];r,c=key;rs,cs=cells[key]['span']
            select_cells(h,cells,selected,t)
            check(h.TableSplitCell(Rows=rs if rs>1 else 0,Cols=cs if cs>1 else 0),'병합 셀을 분할하지 못했습니다.')
            expected[key]=((1,1),expected[key][1])
            added={(i,j) for i in range(r,r+rs) for j in range(c,c+cs)}-{key}
    else:
        axis=0 if action.endswith('rows') else 1
        size=(rows,cols)[axis];at=e['index'];count=e.get('count',1)
        if action.startswith('insert'):
            edge=min(at,size)
            k=next(k for k in sorted(cells) if k[axis]==edge and cells[k]['first'])
            begin(h,cells[k]['first'])
            act=h.create_action('TableInsertRowColumn');ps=act.CreateSet();act.GetDefault(ps)
            ps.SetItem('Side',(2 if axis==0 else 0)+int(at>size));ps.SetItem('Count',count)
            check(act.Execute(ps),'행·열을 추가하지 못했습니다.')
            def shifted(key):
                return tuple(x+(count if i==axis and x>=at else 0) for i,x in enumerate(key))
            expected={shifted(k):v for k,v in expected.items()}
            rows+=count if axis==0 else 0;cols+=count if axis==1 else 0
            covered={(r,c) for (rr,cc),(span,_) in expected.items()
                     for r in range(rr,rr+span[0]) for c in range(cc,cc+span[1])}
            added={(r,c) for r in range(1,rows+1) for c in range(1,cols+1)}-covered
        else:
            # A single-row/column native action cannot partially remove a
            # multi-span cell even when the whole requested range covers it.
            removed=[k for k in cells if at<=k[axis]<at+count]
            if any(cells[k]['span'][axis]>1 for k in removed):
                dm.fail('PARTIAL_MERGED_CELL','삭제할 방향으로 병합된 셀을 먼저 분할하세요.')
            if any(any(len(p[1])>len(t['path']) for p in cells[k]['payload']) for k in removed):
                invalid('중첩 표가 있는 행·열은 중첩 표부터 명시적으로 삭제하세요.')
            current=before;ct=t
            for i in range(at+count-1,at-1,-1):
                ready()
                current_cells=data(current,ct)
                k=next(k for k in sorted(current_cells) if k[axis]==i and current_cells[k]['first'])
                begin(h,current_cells[k]['first'])
                check(h.Run('TableDeleteRow' if axis==0 else 'TableDeleteColumn'),'지정한 행·열을 삭제하지 못했습니다.')
                current=inspect(hancom,validate_target=ready);ct=same_table(current,t)
            expected={tuple(x-(count if j==axis and x>=at+count else 0) for j,x in enumerate(k)):v
                      for k,v in expected.items() if k not in removed}
            rows-=count if axis==0 else 0;cols-=count if axis==1 else 0
    h.Cancel();after=inspect(hancom,validate_target=ready);new_t=same_table(after,t)
    new=data(after,new_t)
    verify((rows,cols)==(new_t['rows'],new_t['columns']),'표의 행·열 개수가 요청과 다릅니다.')
    verify(set(new)==set(expected)|added,'표의 셀 주소가 요청과 다릅니다.')
    for k,(span,payload) in expected.items():
        item=new[k]
        verify(item['span']==span,'셀의 병합 범위가 요청과 다릅니다.')
        if k in emptied:
            verify(empty_payload(item['payload']),'지정한 셀의 내용이 남았습니다.')
        else:
            verify(payload==item['payload'],'셀의 기존 내용·순서·서식이 달라졌습니다.')
    for k in added:
        verify(new[k]['span']==(1,1) and empty_payload(new[k]['payload']),'추가한 셀의 구조 또는 내용이 다릅니다.')
    verify(body_outside(before,t)==body_outside(after,new_t) and
           outside_tables(before,t)==outside_tables(after,new_t) and nested==other_nested(after,new_t) and
           before['bookmarks']==after['bookmarks'] and before.get('structure_metadata')==after.get('structure_metadata'),
           '지정 표 바깥의 내용·표·책갈피가 달라졌습니다.')
    return after
