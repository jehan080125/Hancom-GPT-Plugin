import json
from pathlib import Path
import pytest
from hangul_bookmark.content import normalize
from hangul_bookmark.latex import convert
from hangul_bookmark.errors import WriterError
from hangul_bookmark.service import Service, digest, dumps
from hangul_bookmark import xmlcheck

@pytest.mark.parametrize('latex,script', [
    (r'\frac{a}{b}', '{a} over {b}'),
    (r'\sqrt[3]{x}', 'root {3} of {x}'),
    (r'x_{i}^{2}', 'x_{i}^{2}'),
    (r'\begin{pmatrix}a&b\\c&d\end{pmatrix}', 'LEFT ( matrix {a & b # c & d} RIGHT )'),
])
def test_math(latex,script): assert convert(latex)==script

@pytest.mark.parametrize('s',[r'\newcommand{\x}{x}',r'\unknown{x}',r'\frac{a}',r'\begin{matrix}a&b\\c\end{matrix}','{x'])
def test_rejected_math(s):
    with pytest.raises(WriterError): convert(s)

def test_uncertainty_and_order():
    assert normalize([{'type':'text','text':'가\n나'}]) == [{'type':'text','text':'가'},{'type':'paragraph_break'},{'type':'text','text':'나'}]
    with pytest.raises(WriterError): normalize([{'type':'text','text':'?','uncertain':True}])

def test_image_crop(tmp_path):
    from PIL import Image
    f=tmp_path/'image.png'; Image.new('RGB',(20,10)).save(f)
    assert normalize([{'type':'image','path':str(f),'crop':[1,2,10,9]}])[0]['crop']==[1,2,10,9]
    with pytest.raises(WriterError): normalize([{'type':'image','path':str(f),'crop':[1,2,50,9]}])

class FakeRunner:
    def __init__(self): self.calls=0; self.fail=False
    def __call__(self,job):
        if job['operation'] in ('environment','smoke'): return {'ok':True,'version':[12,0,0,535],'security_module':False}
        if job['operation']=='inspect': return {'ok':True,'bookmarks':[{'name':'B','scope':'body','ambiguous':False}],'version':[12,0,0,535],'security_module':False}
        self.calls+=1
        f=Path(job['path']); f.write_bytes(f.read_bytes()+b'inserted')
        if self.fail: raise WriterError('HANCOM_FAILED','simulated failure after scratch write')
        return {'ok':True,'verification':{'reopened':True}}

class Dialogs:
    @staticmethod
    def choose_file(): return None

@pytest.fixture
def selected(tmp_path):
    source=tmp_path/'original.hwp'; source.write_bytes(b'original')
    runner=FakeRunner(); svc=Service(tmp_path/'state',runner,Dialogs)
    doc=svc.select_document(str(source)); svc.select_bookmark(doc['document_id'],'B')
    yield svc,doc,source,runner
    svc.close()

def insert(svc,doc,rid='one'): return svc.insert_content(doc['document_id'],rid,[{'type':'text','text':'안녕'}])

def test_original_retry_and_continue(selected):
    svc,doc,source,runner=selected
    a=insert(svc,doc); assert source.read_bytes()==b'original'
    assert Path(a['output']).read_bytes()==b'originalinserted'
    assert insert(svc,doc)['replayed']; assert runner.calls==1
    insert(svc,doc,'two'); assert Path(a['output']).read_bytes()==b'originalinsertedinserted'
    with pytest.raises(WriterError): svc.insert_content(doc['document_id'],'one',[{'type':'text','text':'다름'}])

def test_failure_preserves_last_success(selected):
    svc,doc,source,runner=selected
    result=insert(svc,doc); old=digest(result['output']); runner.fail=True
    with pytest.raises(WriterError): insert(svc,doc,'failure')
    assert digest(result['output'])==old; assert source.read_bytes()==b'original'

def test_external_change_and_collision(selected):
    svc,doc,source,runner=selected
    Path(doc['output']).write_bytes(b'other owner')
    with pytest.raises(WriterError,match='저장 예정'): insert(svc,doc)
    assert Path(doc['output']).read_bytes()==b'other owner'
    source.write_bytes(b'changed')
    with pytest.raises(WriterError,match='원본'): insert(svc,doc,'new')

def test_missing_bookmark_and_cancel(selected):
    svc,doc,source,runner=selected
    assert svc.select_document()['cancelled']
    with pytest.raises(WriterError): svc.select_bookmark(doc['document_id'],'missing')
    assert runner.calls==0

def test_preview_marks_uncertainty_without_write(selected):
    svc,doc,source,runner=selected
    result=svc.preview_content([{'type':'text','text':'읽힘'}, {'type':'text','text':'?','uncertain':True,'reason':'기호 불명'}])
    assert not result['ok']; assert result['issues'][0]['index']==1
    assert runner.calls==0 and source.read_bytes()==b'original'

def test_file_lock(selected):
    import sys
    if sys.platform!='win32': pytest.skip('Windows sharing test')
    import win32file, win32con
    svc,doc,source,runner=selected
    handle=win32file.CreateFile(str(source),win32con.GENERIC_READ|win32con.GENERIC_WRITE,win32con.FILE_SHARE_READ,None,win32con.OPEN_EXISTING,0,None)
    try:
        with pytest.raises(WriterError,match='편집 중'): insert(svc,doc)
        assert not Path(doc['output']).exists()
    finally: handle.Close()

def test_restart_dedup(selected):
    svc,doc,source,runner=selected
    insert(svc,doc)
    other=Service(svc.state,runner,Dialogs)
    try: assert insert(other,doc)['replayed']; assert runner.calls==1
    finally: other.close()

def test_pending_commit_recovery(selected):
    svc,doc,source,runner=selected
    result=insert(svc,doc)
    svc.db.execute("UPDATE requests SET status='pending'"); svc.db.commit()
    assert insert(svc,doc)['recovered']; assert runner.calls==1

def test_verifier_detects_wrong_location():
    def snap(text): return xmlcheck.snapshot('<HWPML><BODY><P><CHAR>'+text+'</CHAR></P></BODY></HWPML>')
    before=snap('abc'); before['anchors']['B']=1
    xmlcheck.verify(before,snap('aXbc'),[{'type':'text','text':'X'}],'B')
    with pytest.raises(WriterError): xmlcheck.verify(before,snap('abcX'),[{'type':'text','text':'X'}],'B')
