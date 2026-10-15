import copy
from pathlib import Path
import pytest
from hangul_bookmark import document as d
from hangul_bookmark.service import Service,dumps
from hangul_bookmark.errors import WriterError
from hangul_bookmark.native_edit import apply_selection

def xml(text='same same', extra=''):
    return ('<HWPML><HEAD><MAPPINGTABLE><FONTFACELIST><FONTFACE Lang="Hangul"><FONT Id="0" Name="Font"/></FONTFACE></FONTFACELIST>'
            '<CHARSHAPELIST><CHARSHAPE Id="0" Height="1000" TextColor="7"><FONTID Hangul="0"/><BOLD/></CHARSHAPE></CHARSHAPELIST>'
            '<PARASHAPELIST><PARASHAPE Id="0" HeadingType="None" Level="0"/></PARASHAPELIST>'
            '<STYLELIST><STYLE Id="0" Name="바탕글" CharShape="0" ParaShape="0"/></STYLELIST></MAPPINGTABLE></HEAD>'
            '<BODY><SECTION><P ParaShape="0" Style="0"><TEXT CharShape="0"><CHAR>'+text+'</CHAR></TEXT></P>'+extra+'</SECTION></BODY><DOCSETTING Caret="0"/></HWPML>')

def doc(text='same same',extra=''):
    m=d.model(xml(text,extra))
    for i,p in enumerate(m['paragraphs']):p.update(mapped=True,native=[0,i])
    return m

def hit(m,text='same',n=1):
    return d.locate(m,{'type':'text','text':text,'occurrence':n})[0]['target_id']

def test_duplicate_search_and_range():
    m=doc()
    found=d.locate(m,{'type':'text','text':'same'})
    assert len(found)==2 and found[0]['target_id']!=found[1]['target_id']
    ops=d.compile_edits(m,[{'type':'replace_text','target_id':hit(m,n=2),'expected_text':'same','text':'different'}])
    aa=d.expected_atoms(m,ops)[0]
    assert ''.join(a.get('text','') for a in aa)=='same different'

def test_text_across_character_shapes():
    m=doc('before')
    p=m['paragraphs'][0];p['parts'].append(dict(p['parts'][0],start=6,end=11,text='after'));p['length']=11;p['text']='beforeafter'
    target=hit(m,'foreaf')
    op=d.compile_edits(m,[{'type':'replace_text','target_id':target,'expected_text':'foreaf','text':'X'}])
    assert ''.join(a['text'] for a in d.expected_atoms(m,op)[0])=='beXter'

def test_unicode_offsets():
    m=doc('a😀z');target=hit(m,'😀')
    op=d.compile_edits(m,[{'type':'replace_text','target_id':target,'expected_text':'😀','text':'x'}])[0]
    assert (op['start'],op['end'])==(1,3)
    with pytest.raises(WriterError):d.char_index('😀',1)

def test_format_preserves_equation_spaces():
    eq='<P ParaShape="0" Style="0"><TEXT CharShape="0"><EQUATION BaseUnit="1000"><SCRIPT>x^2 + 1</SCRIPT></EQUATION></TEXT></P>'
    m=doc('same',eq);ops=d.compile_edits(m,[{'type':'set_format','target_id':'all','properties':{'size_pt':11,'equation_size_pt':11}}])
    aa=d.expected_atoms(m,ops)
    assert aa[1][0]['script']=='x^2 + 1'
    assert aa[1][0]['font']=='HancomEQN' and aa[1][0]['size_pt']==11
    assert aa[0][0]['style']['other']==d.atoms(m['paragraphs'][0])[0]['style']['other']

@pytest.mark.parametrize('change',[
 {'type':'set_format','target_id':'all','properties':{'size_pt':0}},
 {'type':'set_format','target_id':'all','properties':{'bold':True}},
 {'type':'set_format','target_id':'all','properties':{'size_pt':True}},
 {'type':'set_format','target_id':'all','properties':{'size_pt':float('nan')}},
 {'type':'replace_text','target_id':'missing','text':'x','expected_text':'same'},
 {'type':'replace_text','target_id':'all','text':'x\ny','expected_text':'same'},
])
def test_invalid_edits(change):
    with pytest.raises(WriterError):d.compile_edits(doc(),[change])

def test_overlap_and_uncertainty():
    m=doc();edit={'type':'replace_text','target_id':hit(m),'expected_text':'same','text':'one'}
    with pytest.raises(WriterError):d.compile_edits(m,[edit,edit])
    with pytest.raises(WriterError):d.compile_edits(m,[dict(edit,uncertain=True)])

def test_unmapped_cannot_write():
    m=doc();m['paragraphs'][0]['mapped']=False
    with pytest.raises(WriterError):d.compile_edits(m,[{'type':'set_format','target_id':'all','properties':{'size_pt':12}}])

def test_verifier_rejects_outside_text_and_format():
    a=doc();b=doc('same CHANGED')
    with pytest.raises(WriterError):d.verify_edit(a,b,[])
    b=copy.deepcopy(a);b['paragraphs'][0]['parts'][0]['style']['other']='changed-bold'
    with pytest.raises(WriterError):d.verify_edit(a,b,[])

def test_revision_ignores_view_not_style():
    assert d.revision(xml().replace('Caret="0"','Caret="99"'))==d.revision(xml())
    assert d.revision(xml().replace('Height="1000"','Height="1100"'))!=d.revision(xml())

def test_table_and_nested_path():
    table='<P><TEXT><TABLE RowCount="1" ColCount="1"><ROW><CELL RowAddr="0" ColAddr="0"><PARALIST><P><TEXT><CHAR>cell</CHAR></TEXT></P></PARALIST></CELL></ROW></TABLE></TEXT></P>'
    m=doc('body',table)
    found=d.locate(m,{'type':'table','table':1,'row':1,'column':1})
    assert len(found)==1 and found[0]['text']=='cell'

def test_excluded_text_not_searchable():
    m=doc('body','<P><TEXT><FOOTNOTE><PARALIST><P><TEXT><CHAR>secret</CHAR></TEXT></P></PARALIST></FOOTNOTE></TEXT></P>')
    assert m['excluded']['FOOTNOTE']==1
    assert not d.locate(m,{'type':'text','text':'secret'})

def test_selection_bounds():
    m=doc('first')
    apply_selection(m,{'selection':[True,0,0,1,0,0,4]})
    a=d.expand(m,m['selection_target'])[0]
    assert (a['start'],a['end'])==(1,4)

def test_heading_needs_boundary():
    m=doc('Heading')
    with pytest.raises(WriterError,match='끝 제목'):d.locate(m,{'type':'heading','text':'Heading'})

class Runner:
    def __init__(self):self.analysis=doc();self.writes=0;self.error=None
    def __call__(self,job):
        op=job['operation']
        if op in ('environment','smoke'):return {'ok':True,'version':[12,0,0,535],'security_module':True}
        if op=='inspect':return {'bookmarks':[],'version':[12,0,0,535],'security_module':True}
        if op=='read_document':return {'ok':True,'document':copy.deepcopy(self.analysis)}
        if op=='apply_edits':
            if self.analysis['revision']!=job['revision']:raise WriterError('STALE_REVISION','changed')
            self.writes+=1
            if self.error:raise WriterError(self.error,'simulated')
            Path(job['path']).write_bytes(b'changed')
            return {'ok':True,'revision':'new-revision','counts':{'text_replacements':1},'verification':{'reopened':True}}
        raise AssertionError(op)

@pytest.fixture
def selected(tmp_path):
    r=Runner();s=Service(tmp_path/'state',r)
    source=tmp_path/'source.hwp';source.write_bytes(b'original')
    info=s.select_document(str(source))
    yield s,r,info,source
    s.close()

def edits(s,info):
    read=s.read_document(info['document_id']);rev=read['revision']
    matches=s.find_targets(info['document_id'],rev,{'type':'text','text':'same','occurrence':2})
    return rev,[{'type':'replace_text','target_id':matches['matches'][0]['target_id'],'expected_text':'same','text':'new'}]

def test_file_edit_dry_run_dedup(selected):
    s,r,info,source=selected;rev,ops=edits(s,info)
    preview=s.apply_edits(info['document_id'],rev,'req',ops,dry_run=True)
    assert preview['dry_run'] and not Path(info['output']).exists() and source.read_bytes()==b'original'
    result=s.apply_edits(info['document_id'],rev,'req',ops)
    assert result['saved'] and Path(result['output']).read_bytes()==b'changed'
    assert s.apply_edits(info['document_id'],rev,'req',ops)['replayed'] and r.writes==2
    assert source.read_bytes()==b'original'

def test_changed_analysis_and_pending_commit(selected):
    s,r,info,source=selected;rev,ops=edits(s,info)
    r.analysis=doc('other')
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'req',ops)
    assert not Path(info['output']).exists()

def test_large_document_paging_no_truncation(selected):
    s,r,info,source=selected;r.analysis=doc('a'*50000)
    first=s.read_document(info['document_id'],limit=2)
    pages=first['blocks'];cursor=first['next_cursor']
    while cursor is not None:
        page=s.read_document(info['document_id'],cursor=cursor,limit=2,revision=first['revision'])
        pages+=page['blocks'];cursor=page['next_cursor']
    assert ''.join(b.get('text','') for b in pages)=='a'*50000

def test_revision_changes_between_pages(selected):
    s,r,info,source=selected
    read=s.read_document(info['document_id']);source.write_bytes(b'changed');r.analysis=doc('changed')
    with pytest.raises(WriterError):s.read_document(info['document_id'],revision=read['revision'])

def test_selection_missing(selected):
    s,_,info,_=selected
    with pytest.raises(WriterError):s.read_document(info['document_id'],scope='selection')


def test_empty_paragraph_format():
    m=doc('')
    ops=d.compile_edits(m,[{'type':'set_format','target_id':'all','properties':{'size_pt':12}}])
    assert d.expected_atoms(m,ops)[0][0]['style']['size_pt']==12

def test_format_content_partial_overlap_rejected():
    m=doc('abcdef')
    text=hit(m,'bcd');style=hit(m,'cde')
    with pytest.raises(WriterError):
        d.compile_edits(m,[{'type':'replace_text','target_id':text,'expected_text':'bcd','text':'X'},
                          {'type':'set_format','target_id':style,'properties':{'size_pt':12}}])

def test_equation_space_change_is_detected():
    eq='<P><TEXT><EQUATION BaseUnit="1000"><SCRIPT>x^2 +1</SCRIPT></EQUATION></TEXT></P>'
    a=doc('a',eq);b=doc('a',eq.replace('x^2 +1','x^2+1'))
    with pytest.raises(WriterError):d.verify_edit(a,b,[])

def test_heading_end_must_exist():
    m=doc('Heading')
    with pytest.raises(WriterError):d.locate(m,{'type':'heading','text':'Heading','end_heading':'missing'})

def test_out_of_scope_bookmark_target_rejected():
    m=doc();m['targets']['bad']={'kind':'control','paragraph':0,'start':0,'end':1}
    with pytest.raises(WriterError):d.compile_edits(m,[{'type':'set_format','target_id':'bad','properties':{'size_pt':12}}])

def test_request_conflict_for_edit(selected):
    s,r,info,_=selected;rev,ops=edits(s,info)
    s.apply_edits(info['document_id'],rev,'same',ops)
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'same',[dict(ops[0],text='other')])

def test_edit_output_collision(selected):
    s,_,info,_=selected;rev,ops=edits(s,info)
    Path(info['output']).write_bytes(b'belongs to someone else')
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'same',ops)
    assert Path(info['output']).read_bytes()==b'belongs to someone else'

def test_cancelled_edit_does_not_touch_native():
    import threading
    from hangul_bookmark.native_edit import apply_native
    class NoNative:
        @property
        def hwp(self):return object()
    event=threading.Event();event.set()
    m=doc();ops=d.compile_edits(m,[{'type':'set_format','target_id':'all','properties':{'size_pt':12}}])
    with pytest.raises(WriterError,match='시간 초과'):apply_native(NoNative(),m,ops,cancelled=event)

def test_guard_rejects_before_reading_other_window():
    from hangul_bookmark.native_edit import inspect
    def changed():raise WriterError('OPEN_DOCUMENT_CHANGED','changed')
    with pytest.raises(WriterError):inspect(object(),validate_target=changed)

class OpenRunner(Runner):
    def __init__(self):super().__init__();self.recovered=False
    def __call__(self,job):
        op=job['operation']
        if op=='open_list':return {'documents':[{'window_id':'one','title':'fixture','file':None,'modified':True,'target':{'id':1}}]}
        if op=='open_inspect':return {'bookmarks':[],'version':[12,0,0,535],'modified':True,'security_module':True}
        if op=='open_read':return {'ok':True,'document':copy.deepcopy(self.analysis)}
        if op=='open_revision':return {'ok':True,'revision':self.analysis['revision']}
        if op=='open_edit':
            self.writes+=1
            if self.error:raise WriterError(self.error,'simulated')
            result={'ok':True,'mode':'open','saved':False,'output':None,'counts':{'text_replacements':1},'revision':'after'}
            Path(job['backup']).write_bytes(b'backup')
            Path(job['receipt']).write_text(dumps(result),encoding='utf-8')
            if self.recovered:raise WriterError('BACKEND_FAILED','lost response')
            return result
        return super().__call__(job)

@pytest.fixture
def opened(tmp_path):
    r=OpenRunner();s=Service(tmp_path/'state',r)
    info=s.select_document(mode='open',window_id='one')
    yield s,r,info
    s.close()

@pytest.mark.parametrize('error',['LIVE_RECOVERY_REQUIRED','HANCOM_TIMEOUT','BACKEND_FAILED'])
def test_open_edit_ambiguous_blocks_retry(opened,error):
    s,r,info=opened;rev,ops=edits(s,info);r.error=error
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'req',ops)
    r.error=None
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'req',ops)
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'new',ops)
    assert r.writes==1

def test_open_edit_known_failure_can_retry(opened):
    s,r,info=opened;rev,ops=edits(s,info);r.error='STALE_REVISION'
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'req',ops)
    r.error=None
    assert s.apply_edits(info['document_id'],rev,'req',ops)['saved'] is False

def test_open_edit_receipt_recovers_counts(opened):
    s,r,info=opened;rev,ops=edits(s,info);r.recovered=True
    with pytest.raises(WriterError):s.apply_edits(info['document_id'],rev,'req',ops)
    replay=s.apply_edits(info['document_id'],rev,'req',ops)
    assert replay['recovered'] and replay['counts']['text_replacements']==1 and r.writes==1

def test_selected_cells_group():
    m=doc('body','<P><TEXT><TABLE RowCount="1" ColCount="1"><ROW><CELL RowAddr="0" ColAddr="0"><PARALIST><P><TEXT><CHAR>cell</CHAR></TEXT></P></PARALIST></CELL></ROW></TABLE></TEXT></P>')
    from hangul_bookmark.native_edit import enrich_selection
    m['tables'][0]['_anchor']=[0,1,0]
    state={'cells':{'anchor':[0,1,0],'addresses':['A1']},'selection':[False]}
    enrich_selection(m,state);apply_selection(m,state)
    assert len(d.expand(m,m['selection_target']))==1

def test_read_keeps_prior_search_handles(selected):
    s,_,info,_=selected;rev,ops=edits(s,info)
    s.read_document(info['document_id'])
    assert s.apply_edits(info['document_id'],rev,'req',ops)['ok']


def test_long_equation_paging(selected):
    s,r,info,_=selected
    value='x+'*12000+'1'
    r.analysis=doc('body','<P><TEXT><EQUATION BaseUnit="1000"><SCRIPT>'+value+'</SCRIPT></EQUATION></TEXT></P>')
    first=s.read_document(info['document_id'],limit=1);pages=list(first['blocks']);cursor=first['next_cursor']
    while cursor is not None:
        page=s.read_document(info['document_id'],cursor=cursor,limit=1,revision=first['revision'])
        pages+=page['blocks'];cursor=page['next_cursor']
    fragments=[b for b in pages if b['kind']=='equation']
    assert ''.join(b['script'] for b in fragments)==value and all(not b['script_complete'] for b in fragments)

def test_partial_equation_format_rejected():
    m=doc('body','<P><TEXT><EQUATION BaseUnit="1000"><SCRIPT>x</SCRIPT></EQUATION></TEXT></P>')
    target=d.add_target(m,{'kind':'range','paragraph':1,'start':0,'end':1})
    with pytest.raises(WriterError):d.compile_edits(m,[{'type':'set_format','target_id':target,'properties':{'equation_size_pt':12}}])

def test_search_paging(selected):
    s,r,info,_=selected;r.analysis=doc('x '*50)
    read=s.read_document(info['document_id'])
    result=s.find_targets(info['document_id'],read['revision'],{'type':'text','text':'x','limit':3})
    assert result['total_matches']==50 and result['count']==3 and result['next_cursor']==3 and result['ambiguous']

def test_private_com_caches_are_isolated():
    import os,subprocess,sys,json
    if sys.platform!='win32':pytest.skip('Windows COM cache')
    code="from hangul_bookmark.com_runtime import prepare;prepare();import win32com;print(win32com.__gen_path__)"
    children=[subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy()) for _ in range(2)]
    paths=[]
    for child in children:
        out,err=child.communicate(timeout=30)
        assert child.returncode==0,err
        paths.append(out.strip())
    assert paths[0]!=paths[1] and all('hangul-com-' in p for p in paths)
    assert all(not Path(p).exists() for p in paths)

def test_erasing_text_preserves_empty_paragraph():
    before=doc("erase");after=doc("")
    target=hit(before,"erase")
    ops=d.compile_edits(before,[{"type":"replace_text","target_id":target,"expected_text":"erase","text":""}])
    d.verify_edit(before,after,ops)
