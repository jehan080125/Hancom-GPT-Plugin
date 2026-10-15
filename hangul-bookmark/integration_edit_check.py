"""Disposable 0.3.0 native file/live acceptance tests; never select a user file."""
import argparse
import json
from pathlib import Path
import launch
from hangul_bookmark.backend import Hancom,finalize_sta
from hangul_bookmark.service import Service,digest
from hangul_bookmark import native_edit as ne,document as dm

def make_fixture(h,path):
    w=h.hwp
    w.insert_text('제목');w.Run('BreakPara')
    w.insert_text('같은 문장 같은 문장');w.Run('BreakPara')
    w.insert_text('수식 ');h.equation('x^2 +1',1000);w.insert_text(' 유지');w.Run('BreakPara')
    w.create_table(rows=2,cols=2,header=False)
    positions=[]
    for i,text in enumerate(('셀 A','셀 B','셀 C','셀 D')):
        w.insert_text(text);positions.append(w.get_pos())
        if i<3:w.Run('TableRightCell')
    w.set_pos(*positions[2]);w.create_table(rows=1,cols=1,header=False);w.insert_text('중첩 셀')
    w.MoveDocEnd();w.Run('BreakPara');w.insert_text('끝 제목')
    h.save(path)

def read_all(s,id,**kwargs):
    first=s.read_document(id,**kwargs);blocks=list(first['blocks']);cursor=first['next_cursor']
    while cursor is not None:
        page=s.read_document(id,cursor=cursor,revision=first['revision'],**kwargs)
        blocks+=page['blocks'];cursor=page['next_cursor']
    return first,blocks

def changes(s,id,read):
    rev=read['revision']
    text=s.find_targets(id,rev,{'type':'text','text':'같은 문장','occurrence':2})['matches'][0]
    eq=s.find_targets(id,rev,{'type':'equation'})['matches'][0]
    return [
      {'type':'replace_text','target_id':text['target_id'],'expected_text':'같은 문장','text':'고친 문장'},
      {'type':'replace_equation','target_id':eq['target_id'],'expected_script':'x^2 +1','script':'y^{3}+2','format':'latex'},
      {'type':'set_format','target_id':'all','properties':{'font_name':'함초롬돋움','size_pt':11,'equation_size_pt':11}},
    ]


def edge_cases(out):
    owner=Hancom(visible=False)
    try:
        owner.open(out/'source.hwp');w=owner.hwp
        w.get_into_nth_table(0);w.TableCellBlock();w.TableCellBlockRow()
        doc=ne.inspect(owner)
        assert ne.selected_cells(w)==['A1','B1']
        assert len(dm.expand(doc,doc['selection_target']))==2
        w.Cancel();w.MoveDocEnd();pos=w.get_pos();w.InsertFootnote();w.insert_text('각주 보존');w.set_pos(*pos)
        before=ne.inspect(owner);assert before['excluded']['FOOTNOTE']==1
        ops=dm.compile_edits(before,[{'type':'set_format','target_id':'all','properties':{'size_pt':12,'equation_size_pt':12}}])
        ne.apply_native(owner,before,ops);dm.verify_edit(before,ne.inspect(owner),ops)
        owner.save(out/'excluded-footnote.hwp')
        try:ne.validate_fonts([{'type':'set_format','properties':{'font_name':'__NOT_INSTALLED__'}}])
        except Exception:pass
        else:raise AssertionError('missing font not blocked')
        print('edge: cells, footnote, empty paragraphs and font check passed',flush=True)
        w.clear(1);w.insert_text('제목');w.Run('BreakPara')
        w.insert_text('앞 ');w.set_font(Bold=True,TextColor=255);w.insert_text('강조')
        w.set_font(Bold=False,TextColor=0);w.insert_text(' 문장 끝')
        for script in ('2+2=5','sqrt {9}=+-3','2+2=4'):
            w.Run('BreakPara');owner.equation(script,1000)
        w.Run('BreakPara');w.insert_text('끝 제목')
        before=ne.inspect(owner);eqs=dm.locate(before,{'type':'equation'})
        target=dm.locate(before,{'type':'text','text':'강조 문장'})[0]['target_id']
        area=dm.locate(before,{'type':'heading','text':'제목','end_heading':'끝 제목'})[0]['target_id']
        edits=[{'type':'replace_text','target_id':target,'expected_text':'강조 문장','text':'수정'},
               {'type':'replace_equation','target_id':eqs[0]['target_id'],'expected_script':'2+2=5','format':'latex','script':'2+2=4'},
               {'type':'replace_equation','target_id':eqs[1]['target_id'],'expected_script':'sqrt {9}=+-3','format':'latex','script':r'\sqrt{9}=3'},
               {'type':'set_format','target_id':area,'properties':{'size_pt':11,'equation_size_pt':11,'equation_font':'HancomEQN'}}]
        ops=dm.compile_edits(before,edits);ne.apply_native(owner,before,ops);after=ne.inspect(owner);dm.verify_edit(before,after,ops)
        assert dm.atoms(before['paragraphs'][0])==dm.atoms(after['paragraphs'][0])
        assert [a['script'] for p in after['paragraphs'] for a in p['parts'] if a['kind']=='equation']==['2+2=4','sqrt {9}=3','2+2=4']
        owner.save(out/'mixed-style-math.hwp')
        return [{'mode':'native-edge','ok':True,'cells_restored':True,'footnote_preserved':True,'missing_font_rejected':True},
                {'mode':'review-examples','ok':True,'mixed_styles_preserved':True,'heading_excluded':True,'corrected_examples':2,'correct_example_preserved':1,
                 'note':'이 예제는 판정한 수식의 읽기·수정 경로 확인이며 일반적인 수학 검토 정확도 측정이 아닙니다.'}]
    finally:owner.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);results=[]
    for ext in ('.hwp','.hwpx'):
        owner=Hancom(visible=False)
        try:make_fixture(owner,out/('source'+ext))
        finally:owner.close()
        s=Service(out/('state-file'+ext[1:]))
        try:
            path=out/('source'+ext);original=digest(path);doc=s.select_document(str(path));id=doc['document_id']
            read,blocks=read_all(s,id,limit=2)
            assert read['tables'][1]['number']==2 and not read['unmapped_paragraphs']
            assert any(b.get('text')=='중첩 셀' for b in blocks)
            assert s.find_targets(id,read['revision'],{'type':'text','text':'같은 문장'})['ambiguous']
            edits=changes(s,id,read)
            preview=s.apply_edits(id,read['revision'],'edit-1',edits,dry_run=True)
            assert preview['dry_run'] and not Path(doc['output']).exists() and digest(path)==original
            result=s.apply_edits(id,read['revision'],'edit-1',edits)
            assert result['saved'] and s.apply_edits(id,read['revision'],'edit-1',edits)['replayed']
            assert digest(path)==original
            updated,bb=read_all(s,id)
            assert any('고친 문장' in b.get('text','') for b in bb)
            assert next(b for b in bb if b['kind']=='equation')['script']=='y^{3} +2'
            assert all(b['style']['size_pt']==11 for b in bb if b['kind']=='text')
            assert next(b for b in bb if b['kind']=='equation')['font']=='HancomEQN'
            results.append({'mode':'file','format':ext,'ok':True,'result':result})
        finally:s.close()
        owner=Hancom(visible=True);other=Hancom(visible=True);s=Service(out/('state-live'+ext[1:]))
        try:
            path=out/('live'+ext);make_fixture(owner,path);owner.open(path);disk=digest(path)
            owner.hwp.MoveDocEnd();owner.hwp.insert_text(' 저장 전 변경')
            before=ne.inspect(owner);p=next(p for p in before['paragraphs'] if p['text']=='같은 문장 같은 문장')
            owner.hwp.select_text_by_get_pos((*p['native'],6),(*p['native'],11))
            selected_before=ne.capture(owner.hwp)
            other.hwp.insert_text('다른 창 보존');other_xml=other.xml()
            owner.hwp.XHwpDocuments.Active_XHwpDocument.SetActive_XHwpDocument()
            items=s.runner({'operation':'open_list'})['documents']
            native_id=int(owner.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID)
            target=next(i for i in items if i['target']['native_id']==native_id and i['target']['pid']==owner.pid)
            info=s.select_document(mode='open',window_id=target['window_id']);id=info['document_id']
            read,blocks=read_all(s,id,scope='selection')
            assert ''.join(b.get('text','') for b in blocks)=='같은 문장'
            assert ne.capture(owner.hwp)['selection']==selected_before['selection']
            edits=[{'type':'replace_text','target_id':blocks[0]['target_id'],'expected_text':'같은 문장','text':'선택 수정'},
                   {'type':'set_format','target_id':'all','properties':{'size_pt':12,'equation_size_pt':12}}]
            preview=s.apply_edits(id,read['revision'],'live-1',edits,dry_run=True)
            assert preview['dry_run'] and dm.revision(owner.xml())==read['revision']
            result=s.apply_edits(id,read['revision'],'live-1',edits)
            assert result['saved'] is False and digest(path)==disk
            assert s.apply_edits(id,read['revision'],'live-1',edits)['replayed']
            after=ne.inspect(owner)
            assert '선택 수정' in ''.join(p['text'] for p in after['paragraphs'])
            assert '저장 전 변경' in ''.join(p['text'] for p in after['paragraphs'])
            assert dm.revision(other.xml())==dm.revision(other_xml)
            # Selection of an existing equation is captured without recreating it.
            eq=next((p,a) for p in after['paragraphs'] for a in p['parts'] if a['kind']=='equation')
            owner.hwp.set_pos(*eq[0]['native'],eq[1]['start']);owner.hwp.FindCtrl()
            info2=s.select_document(mode='open',window_id=target['window_id'])
            eqread,eqblocks=read_all(s,info2['document_id'],scope='selection')
            assert len(eqblocks)==1 and eqblocks[0]['kind']=='equation'
            s.close()
            assert '선택 수정' in ''.join(p['text'] for p in ne.inspect(owner)['paragraphs'])
            results.append({'mode':'open','format':ext,'ok':True,'selection':True,'selected_equation':True,'result':result})
        finally:
            s.close();owner.close();other.close()
    results.extend(edge_cases(out))
    finalize_sta()
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(results),'results':results},ensure_ascii=False))
if __name__=='__main__':main()
