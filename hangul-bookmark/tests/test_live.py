import json
from pathlib import Path
import pytest
from hangul_bookmark.service import Service, dumps
from hangul_bookmark.backend import Hancom
from hangul_bookmark.errors import WriterError
from hangul_bookmark.live import native_bytes, signature

class Runner:
    def __init__(self): self.writes=0; self.fail=None; self.closed=False
    def __call__(self,job):
        op=job['operation']
        if op in ('environment','smoke'): return {'ok':True,'version':[12,0,0,535],'security_module':True}
        if op=='open_list':
            return {'documents':[{'window_id':str(i),'title':f'Doc {i}','file':None,'modified':True,'target':{'id':i}} for i in range(2)]}
        if op=='open_inspect':
            if self.closed: raise WriterError('OPEN_DOCUMENT_CLOSED','closed')
            return {'bookmarks':[{'name':'B','scope':'body','ambiguous':False}],'version':[12,0,0,535],'modified':True,'security_module':True}
        assert op=='open_write'
        self.writes+=1
        if self.fail: raise WriterError(self.fail,'failure')
        Path(job['backup']).write_bytes(b'native backup')
        result={'ok':True,'mode':'open','saved':False,'output':None,'backup':job['backup'],'verification':{'in_memory':True}}
        Path(job['receipt']).write_text(dumps(result),'utf-8')
        return result

class Dialogs:
    @staticmethod
    def choose_open_document(items): return None

@pytest.fixture
def opened(tmp_path):
    r=Runner();s=Service(tmp_path,r,Dialogs)
    d=s.select_document(mode='open',window_id='1');s.select_bookmark(d['document_id'],'B')
    yield s,r,d
    s.close()

def insert(s,d): return s.insert_content(d['document_id'],'same',[{'type':'text','text':'text'}])

def test_choose_open_and_cancel(opened):
    s,r,d=opened
    assert d['mode']=='open' and d['saved'] is False and 'target' not in d
    assert s.select_document(mode='open')['cancelled']
    assert len(s.select_document(mode='open',list_only=True)['documents'])==2
    assert s._load(d['document_id'])['target']=={'id':1}
    with pytest.raises(WriterError):s.select_document(path='file.hwp',mode='open')
    with pytest.raises(WriterError):s.select_document(mode='other')
    with pytest.raises(WriterError):s.select_document(mode='open',window_id='closed')

def test_live_dedup_no_file_commit(opened):
    s,r,d=opened
    result=insert(s,d);assert not result['saved'] and result['output'] is None
    assert insert(s,d)['replayed'] and r.writes==1
    with pytest.raises(WriterError):s.insert_content(d['document_id'],'same',[{'type':'text','text':'different'}])

def test_safe_failure_can_retry(opened):
    s,r,d=opened;r.fail='BOOKMARK_MISSING'
    with pytest.raises(WriterError):insert(s,d)
    r.fail=None;assert insert(s,d)['ok']

@pytest.mark.parametrize('code',['LIVE_RECOVERY_REQUIRED','HANCOM_TIMEOUT','BACKEND_FAILED'])
def test_ambiguous_failure_never_reinserts(opened,code):
    s,r,d=opened;r.fail=code
    with pytest.raises(WriterError):insert(s,d)
    r.fail=None
    with pytest.raises(WriterError,match='재삽입'):insert(s,d)
    with pytest.raises(WriterError):s.insert_content(d['document_id'],'another',[{'type':'text','text':'text'}])
    assert r.writes==1

def test_live_receipt_recovers_after_process_exit(opened):
    s,r,d=opened;result=insert(s,d)
    receipt=next((s.state/'live-backups'/d['document_id']).glob('*.json'))
    journal={'receipt':str(receipt),'backup':result['backup'],'bookmark':'B','counts':result['counts']}
    with s.db:s.db.execute('UPDATE requests SET status=?,data=?',('live_pending',dumps(journal)))
    replay=insert(s,d);assert replay['recovered'] and replay['replayed'] and r.writes==1

def test_closed_document_does_not_write(opened):
    s,r,d=opened;r.closed=True
    with pytest.raises(WriterError):s.select_bookmark(d['document_id'],'B')
    assert r.writes==0

def test_borrowed_window_never_clear_or_quit():
    class Borrowed:
        def clear(self,*a):raise AssertionError('user document cleared')
        def quit(self):raise AssertionError('user window closed')
    h=object.__new__(Hancom);h.owned=False;h.hwp=Borrowed();h.close()
    assert h.hwp is None

def test_invalid_native_backup_rejected():
    with pytest.raises(WriterError):native_bytes('not a document')

def test_export_metadata_does_not_hide_real_edit():
    xml='<HWPML><HEAD><DOCSUMMARY><DATE>{date}</DATE></DOCSUMMARY><MAPPINGTABLE><STYLE Name="{style}"/></MAPPINGTABLE></HEAD><BODY><CHAR>{text}</CHAR></BODY><DOCSETTING CaretPos="{pos}"/></HWPML>'
    first=xml.format(date='1',style='A',text='original',pos='0')
    harmless=xml.format(date='2',style='A',text='original',pos='1')
    edit=xml.format(date='2',style='B',text='changed',pos='1')
    assert signature(first)==signature(harmless)
    assert signature(first)!=signature(edit)

def test_timeout_cancels_future_live_input(monkeypatch):
    import concurrent.futures
    from hangul_bookmark.live_worker import LiveWorker
    class Future:
        def result(self,timeout): raise concurrent.futures.TimeoutError()
    class Jobs:
        def put(self,item): self.item=item
    monkeypatch.setattr(concurrent.futures,'Future',Future)
    w=object.__new__(LiveWorker);w.busy=False;w.jobs=Jobs()
    with pytest.raises(WriterError):w({'operation':'open_write'})
    assert w.jobs.item[0]['_cancelled'].is_set()
    with pytest.raises(WriterError):w({'operation':'open_write'})

def test_owned_shared_process_is_never_closed():
    class Shared:
        @property
        def XHwpDocuments(self): raise AssertionError('shared documents touched')
    h=object.__new__(Hancom);h.owned=True;h.exclusive_process=False;h.hwp=Shared()
    h.close();assert h.hwp is None
