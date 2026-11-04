import copy
import zipfile

import pytest

from hangul_bookmark import document as dm, review, structure
from hangul_bookmark.errors import WriterError
from hangul_bookmark.table_edit import area,compile_change
from test_document import doc, hit


def test_insert_rebases_unchanged_unicode_suffix():
    before=doc('앞😀뒤')
    target=hit(before,'뒤')
    after=doc('앞😀새글뒤')
    block={'type':'text','text':'새글'}
    change=((0,3,0,3),[[block]])
    structure.splice_result(before,after,*change)
    structure.bind_targets(before,after,change)
    assert after['targets'][target]['start']==5


def test_splice_does_not_hide_wrong_object_or_neighbor():
    before=doc('앞😀뒤','<P><TEXT><CHAR>유지</CHAR></TEXT></P>')
    line=[[{'type':'equation','script':'{1} over {2}','display':'inline'}]]
    fake=doc('앞😀뒤','<P><TEXT><EQUATION><SCRIPT>{1} over {2}</SCRIPT></EQUATION><CHAR>유지</CHAR></TEXT></P>')
    with pytest.raises(WriterError,match='대상 밖'):
        structure.splice_result(before,fake,(0,3,0,3),line)


def test_matching_unique_duplicate_survivor_cannot_receive_deleted_id():
    before=doc('same','<P ParaShape="0" Style="0"><TEXT CharShape="0"><CHAR>same</CHAR></TEXT></P>')
    old=before['paragraphs'][0]['id']
    after=doc('same')
    structure.bind_targets(before,after)
    assert old not in after['targets']


def test_range_cannot_bisect_utf16_or_cross_cell():
    before=doc('A😀B')
    key=dm.add_target(before,{'kind':'range','paragraph':0,'start':2,'end':3})
    with pytest.raises(WriterError):
        dm.compile_edits(before,[{'type':'delete_range','target_id':key}])


def test_delete_object_requires_exact_type_handle():
    before=doc('body','<P><TEXT><EQUATION><SCRIPT>x</SCRIPT></EQUATION></TEXT></P>')
    with pytest.raises(WriterError):
        dm.compile_edits(before,[{'type':'delete_object','target_id':before['paragraphs'][1]['id']}])
    eq=dm.locate(before,{'type':'equation'})[0]['target_id']
    assert dm.compile_edits(before,[{'type':'delete_object','target_id':eq}])[0]['type']=='structural_batch'


def test_clearing_and_deleting_merged_cells_are_distinct():
    cells={(1,1):{'span':(1,2)},(2,1):{'span':(1,1)},(2,2):{'span':(1,1)}}
    assert area(cells,[1,1,1,2])==[(1,1)]
    with pytest.raises(WriterError,match='병합 셀의 일부'):
        area(cells,[1,2,2,2])


def test_image_input_is_pinned_for_scratch_and_live(tmp_path):
    source=tmp_path/'input.png';source.write_bytes(b'first')
    edits=[{'type':'insert_table','cells':[[[{'type':'image','path':str(source)}]]]}]
    pinned=structure.pin_assets(edits,tmp_path)
    source.write_bytes(b'second')
    from pathlib import Path
    assert Path(pinned[0]['cells'][0][0][0]['path']).read_bytes()==b'first'
    assert edits[0]['cells'][0][0][0]['path']==str(source)


def package(tmp_path,section=None):
    path=tmp_path/'source.hwpx'
    section=section or ('<sec><p id="1"><run charPrIDRef="0"><t>before '
        '<deleteBegin TcId="2"/>old<deleteEnd TcId="2" paraend="0"/>'
        '<insertBegin TcId="3"/>new<insertEnd TcId="3" paraend="0"/> after'
        '</t></run></p></sec>')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('Contents/header.xml','<head><trackChanges><trackChange id="2" type="Delete" authorID="1"/><trackChange id="3" type="Insert" authorID="1"/></trackChanges><trackChangeAuthors><trackChangeAuthor id="1" name="Reviewer"/></trackChangeAuthors></head>')
        z.writestr('Contents/section0.xml',section)
    return review.read_package(path,False)


def words(body):
    return ''.join(t[2] for t in body[0][3][0][2] if t[1]=='text')


def test_review_decisions_preserve_other_marks_and_text(tmp_path):
    d=package(tmp_path)
    assert words(review.projection(d,{'2':'accept'}))=='before new after'
    assert [t[3]['TcId'] for t in review.projection(d,{'2':'accept'})[0][3][0][2] if t[1]=='mark']==['3','3']
    assert words(review.projection(d,{'2':'reject','3':'reject'}))=='before old after'
    assert review.locations(d)['3']['text']=='new'


def test_review_cannot_apply_unpaired_change(tmp_path):
    d=package(tmp_path,'<sec><p><run><t><insertBegin TcId="3"/>abc</t></run></p></sec>')
    with pytest.raises(WriterError):
        review.projection(d,{'3':'accept'})


def test_review_all_requires_explicit_selection():
    d={'changes':[{'target_id':'t','change_id':'1','mapped':True,'change_type':'Insert'}]}
    with pytest.raises(WriterError):
        review.compile_actions(d,[{'type':'review_change','target_id':'all','action':'accept'}])
    assert review.compile_actions(d,[{'type':'review_change','target_id':'all','all_changes':True,'action':'accept'}])==[('1','accept')]


@pytest.mark.parametrize('existing_definition',[False,True])
def test_object_fragment_removes_only_new_column_definition(monkeypatch,existing_definition):
    from types import SimpleNamespace
    from hangul_bookmark import native_edit

    start=(2,0,4)
    old=SimpleNamespace(CtrlID='cold')
    new=SimpleNamespace(CtrlID='cold')
    maps=iter([{start:old} if existing_definition else {},{start:old if existing_definition else new}])
    monkeypatch.setattr(native_edit,'controls',lambda _:next(maps))

    class Document:
        position=start
        deleted=None

        def get_pos(self):
            return self.position

        def set_text_file(self,data,fmt,option):
            self.position=(2,0,20)
            return True

        def delete_ctrl(self,ctrl):
            self.deleted=ctrl
            return True

        def set_pos(self,*pos):
            self.position=pos
            return True

    h=Document()
    structure.import_object_fragment(h,'fragment','HWP')
    assert h.deleted is (None if existing_definition else new)
    assert h.position==(2,0,20 if existing_definition else 12)


@pytest.mark.parametrize('inline',[True,False])
def test_only_inline_stacking_number_can_be_renumbered(inline):
    position=['POSITION',{'TreatAsChar':str(inline).lower()},'',[]]
    old=['SHAPEOBJECT',{'ZOrder':'1','Lock':'false'},'',[position]]
    new=copy.deepcopy(old)
    new[1]['ZOrder']='5'
    assert (structure.stable(old)==structure.stable(new))==inline
