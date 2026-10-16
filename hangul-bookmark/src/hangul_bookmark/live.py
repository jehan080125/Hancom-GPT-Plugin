"""Explicit ROT selection. Borrowed user windows are never saved, cleared or quit."""
import base64
import hashlib
import json
import os
import threading
from pathlib import Path
from .backend import Hancom, check
from .errors import WriterError
from . import xmlcheck

_connections = threading.local()

def disconnect_all():
    for h, _ in getattr(_connections, 'items', {}).values(): h.close()
    _connections.items = {}

def applications():
    import pythoncom
    from win32com.client import gencache
    context = pythoncom.CreateBindCtx(0)
    rot = pythoncom.GetRunningObjectTable()
    for moniker in rot.EnumRunning():
        try:
            name = moniker.GetDisplayName(context, moniker)
            if name.startswith('!HwpObject.'):
                com = rot.GetObject(moniker).QueryInterface(pythoncom.IID_IDispatch)
                yield name, gencache.EnsureDispatch(com)
        except Exception: continue

def process(com):
    import psutil, win32process
    pid = win32process.GetWindowThreadProcessId(com.XHwpWindows.Active_XHwpWindow.WindowHandle)[1]
    return pid, psutil.Process(pid).create_time()

def list_documents():
    items = []
    for name, com in applications():
        try:
            if not any(com.XHwpWindows.Item(i).Visible for i in range(com.XHwpWindows.Count)): continue
            pid, created = process(com)
            for i in range(com.XHwpDocuments.Count):
                d = com.XHwpDocuments.Item(i)
                path = str(d.FullName or '')
                token = {'rot': name, 'pid': pid, 'created': created, 'native_id': int(d.DocumentID), 'path': path}
                window_id = hashlib.sha256(json.dumps(token, sort_keys=True).encode()).hexdigest()[:24]
                items.append({'window_id': window_id, 'target': token, 'file': path or None,
                              'title': Path(path).name if path else f'저장 전 문서 {d.DocumentID}',
                              'modified': bool(d.Modified), 'mode': 'open'})
        except Exception: continue
    return items

def attach(target):
    if not hasattr(_connections, 'items'): _connections.items = {}
    key = json.dumps(target, sort_keys=True)
    if key in _connections.items:
        h, d = _connections.items[key]
        try:
            if int(d.DocumentID) != target['native_id'] or str(d.FullName or '') != target['path']:
                raise WriterError('OPEN_DOCUMENT_CHANGED', '열린 문서의 파일 연결이 변경됐습니다. 다시 선택하세요.')
            d.SetActive_XHwpDocument()
            if int(h.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID) != target['native_id']:
                raise WriterError('OPEN_DOCUMENT_CLOSED', '선택한 문서가 더 이상 활성화될 수 없습니다. 다시 선택하세요.')
            return h, d
        except WriterError: raise
        except Exception: raise WriterError('OPEN_DOCUMENT_CLOSED', '선택한 열린 문서가 닫혔습니다.') from None
    for name, com in applications():
        if name != target['rot']: continue
        try:
            pid, created = process(com)
            if pid != target['pid'] or created != target['created']: break
            for i in range(com.XHwpDocuments.Count):
                d = com.XHwpDocuments.Item(i)
                if int(d.DocumentID) == target['native_id']:
                    if str(d.FullName or '') != target['path']:
                        raise WriterError('OPEN_DOCUMENT_CHANGED', '열린 문서의 파일 연결이 바뀌었습니다. 문서를 다시 선택하세요.')
                    d.SetActive_XHwpDocument()
                    if int(com.XHwpDocuments.Active_XHwpDocument.DocumentID) != target['native_id']:
                        raise WriterError('OPEN_DOCUMENT_CLOSED', '선택한 문서가 닫혔습니다.')
                    h = Hancom(com=com)
                    _connections.items[key] = (h, d)
                    return h, d
        except WriterError: raise
        except Exception: break
    raise WriterError('OPEN_DOCUMENT_CLOSED', '선택한 한글 문서가 닫혔거나 다시 열렸습니다. 열린 문서를 다시 선택하세요.')

def signature(xml):
    # Exports update summary timestamps and caret/view settings without editing
    # the body. Preserve all body/style/binary data when detecting live edits.
    import xml.etree.ElementTree as ET
    root = xmlcheck.parse(xml)
    for parent in root.iter():
        for child in list(parent):
            if xmlcheck.tag(child) in ('DOCSUMMARY', 'DOCSETTING'):
                parent.remove(child)
    return hashlib.sha256(ET.tostring(root, encoding='utf-8')).hexdigest()

def receipt(path, data):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def native_bytes(data):
    try: binary = base64.b64decode(data)
    except (ValueError, TypeError): raise WriterError('BACKUP_FAILED', '열린 문서의 복원용 사본을 만들지 못했습니다.') from None
    if not binary.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise WriterError('BACKUP_FAILED', '네이티브 HWP 사본의 형식이 올바르지 않습니다.')
    return binary

def inspect(target):
    h, d = attach(target)
    from .native_edit import capture
    selection=capture(h.hwp)
    try:
        if int(d.EditMode) != 1:
            raise WriterError('READ_ONLY_DOCUMENT', '읽기 전용·배포용·양식 모드 문서는 직접 작성할 수 없습니다.')
        from .document import revision
        xml=h.xml();selection['revision']=revision(xml)
        return {'ok': True, 'bookmarks': xmlcheck.bookmarks(xml), 'version': h.version,
                'security_module': h.module, 'modified': bool(d.Modified), 'file': target['path'] or None, 'selection': selection}
    finally: pass  # Keep the exact borrowed connection alive across tool calls.

def write(job):
    h, d = attach(job['target'])
    changed = False
    try:
        # Text/equations operate in memory. Only picture import accesses a path
        # in the borrowed instance; its approval must be available before editing.
        if any(b['type'] == 'image' for b in job['blocks']): h.require_file_access()
        if int(d.EditMode) != 1: raise WriterError('READ_ONLY_DOCUMENT', '편집 가능한 일반 문서만 직접 작성합니다.')
        # Capture unsaved text, equations, figures and formatting, not the disk file.
        baseline_xml = h.xml()
        before = xmlcheck.snapshot(baseline_xml)
        valid = [b['name'] for b in before['bookmarks'] if not b['ambiguous'] and b['scope'] != 'unsupported']
        if job['bookmark'] not in valid: raise WriterError('BOOKMARK_MISSING', '열린 문서에 사용할 책갈피가 없습니다.')
        backup = Path(job['backup'])
        backup.write_bytes(native_bytes(h.hwp.get_text_file('HWP', '')))
        original_position = h.hwp.get_pos()
        # Verify the exact snapshot + all blocks in an owned window first.
        stage = Path(job['stage'])
        stage.write_bytes(backup.read_bytes())
        trial = Hancom(visible=False)
        try:
            trial.open(stage)
            check(xmlcheck.snapshot(trial.xml()) == before, '메모리 사본이 현재 열린 문서와 다릅니다.')
            trial.write(stage, job['bookmark'], job['blocks'])
        finally:
            trial.close()
            # Timeout cleanup must never use a user's borrowed PID.
            if os.environ.get('HANGUL_PID_FILE'): Path(os.environ['HANGUL_PID_FILE']).unlink(missing_ok=True)
        d.SetActive_XHwpDocument()
        if int(h.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID) != job['target']['native_id'] or str(d.FullName or '') != job['target']['path']:
            raise WriterError('OPEN_DOCUMENT_CHANGED', '작업 중 문서 연결이 변경됐습니다.')
        current_xml = h.xml()
        if signature(current_xml) != signature(baseline_xml):
            raise WriterError('EXTERNAL_CHANGE', '시험 중 열린 문서가 수정됐습니다. 다시 요청하세요.')
        for block in job['blocks']:
            if block['type'] == 'image' and hashlib.sha256(Path(block['path']).read_bytes()).hexdigest() != block['sha256']:
                raise WriterError('EXTERNAL_CHANGE', '시험 중 입력 이미지가 변경됐습니다.')
        cancelled = job.get('_cancelled')
        if cancelled is not None and cancelled.is_set():
            raise WriterError('HANCOM_TIMEOUT', '시간 초과 후 열린 창에 입력하지 않았습니다. 복원용 사본만 생성됐을 수 있습니다.')
        # In-place native operations keep the user's document and file connection.
        def validate_target():
            check(int(h.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID) == job['target']['native_id'], '사용자가 활성 문서를 변경하여 입력을 중단했습니다.')
            check(str(d.FullName or '') == job['target']['path'], '작업 중 문서의 파일 연결이 변경됐습니다.')
        changed = True
        _, _, warnings = h.insert_at_bookmark(job['bookmark'], job['blocks'], backup.parent, cancelled, validate_target)
        check(int(h.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID) == job['target']['native_id'], '작성 중 활성 문서가 바뀌었습니다.')
        check(str(d.FullName or '') == job['target']['path'], '작성 중 파일 연결이 바뀌었습니다.')
        d.Modified = 1
        result = {'ok': True, 'mode': 'open', 'saved': False, 'file': job['target']['path'] or None,
                  'output': None, 'backup': str(backup), 'version': h.version, 'security_module': h.module,
                  'warnings': warnings, 'verification': {'in_memory': True, 'reopened': False,
                  'equations': True, 'text': True, 'table_structure': True, 'bookmark_start': True}}
        receipt(job['receipt'], result)
        return result
    except Exception as e:
        if changed:
            # Undo can coalesce with the user's earlier typing. Never undo it blindly.
            error = WriterError('LIVE_RECOVERY_REQUIRED', '열린 창에 일부 내용이 들어갔을 수 있습니다. 자동 저장하지 않았습니다. 반복 작성하지 말고 복원용 사본을 확인하세요: ' + str(job['backup']))
            receipt(job['receipt'], {**error.result(), 'backup': job['backup'], 'detail': str(e)})
            raise error from e
        if 'original_position' in locals():
            try: h.hwp.set_pos(*original_position)
            except Exception: pass
        raise
    finally: pass  # Released by the persistent STA worker, never Quit/Clear.


def read_document(job):
    from . import native_edit
    h,d=attach(job['target'])
    guard=edit_guard(h,d,job)
    guard()
    return {'ok':True,'document':native_edit.inspect(h,selection=job.get('selection') or {},validate_target=guard)}

def edit_guard(h,d,job):
    def guard():
        if int(h.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID)!=job['target']['native_id'] or str(d.FullName or '')!=job['target']['path']:
            raise WriterError('OPEN_DOCUMENT_CHANGED','활성 문서나 파일 연결이 바뀌었습니다. 다시 선택하세요.')
        event=job.get('_cancelled')
        if event is not None and event.is_set():raise WriterError('HANCOM_TIMEOUT','시간 초과 후 추가 작업을 중단했습니다.')
    return guard

def edit(job):
    from . import native_edit,document as dm
    h,d=attach(job['target']);guard=edit_guard(h,d,job)
    changed=False;original=None
    try:
        guard()
        if int(d.EditMode)!=1:raise WriterError('READ_ONLY_DOCUMENT','일반 편집 문서만 수정할 수 있습니다.')
        original=native_edit.capture(h.hwp)
        before=native_edit.inspect(h,validate_target=guard)
        if before['revision']!=job['revision']:raise WriterError('STALE_REVISION','분석 이후 문서가 변경됐습니다. 다시 읽으세요.')
        native_edit.enrich_selection(before,original)
        before['targets']=job['targets'];ops=dm.compile_edits(before,job['edits'])
        native_edit.validate_fonts(ops)
        backup=Path(job['backup']);backup.write_bytes(native_bytes(h.hwp.get_text_file('HWP','')))
        stage=Path(job['stage']);stage.write_bytes(backup.read_bytes())
        trial=Hancom(visible=False)
        try:
            trial_report=native_edit.execute(trial,dict(job,path=str(stage)))
        finally:
            trial.close()
            if os.environ.get('HANGUL_PID_FILE'):Path(os.environ['HANGUL_PID_FILE']).unlink(missing_ok=True)
        guard()
        if dm.revision(h.xml())!=job['revision']:raise WriterError('EXTERNAL_CHANGE','임시 시험 중 문서가 수정됐습니다. 다시 읽으세요.')
        if job.get('dry_run'):
            native_edit.restore(h.hwp,original)
            return dict(trial_report,mode='open',saved=False,output=None,dry_run=True,edits=job['edits'],backup=None)
        guard();changed=True
        report=native_edit.apply_native(h,before,ops,job.get('_cancelled'),guard)
        guard();d.Modified=1
        result=dict(report,ok=True,mode='open',saved=False,output=None,backup=str(backup),file=job['target']['path'] or None,version=h.version)
        report['verification']['in_memory']=True;report['verification']['reopened']=False
        receipt(job['receipt'],result)
        return result
    except Exception as e:
        if changed:
            error=WriterError('LIVE_RECOVERY_REQUIRED','열린 문서가 일부 수정됐을 수 있습니다. 저장하지 않았습니다. 반복 요청하지 말고 작업 전 백업을 확인하세요: '+job['backup'])
            receipt(job['receipt'],dict(error.result(),backup=job['backup'],detail=str(e)))
            raise error from e
        if original is not None:
            try:guard();native_edit.restore(h.hwp,original)
            except Exception:pass
        raise


def handle(job):
    if job['operation'] == 'open_list': return {'ok': True, 'documents': list_documents()}
    if job['operation'] == 'open_inspect': return inspect(job['target'])
    if job['operation'] == 'open_write': return write(job)
    if job['operation'] == 'open_revision':
        from .document import revision
        h,d=attach(job['target']);edit_guard(h,d,job)()
        return {'ok':True,'revision':revision(h.xml())}
    if job['operation'] == 'open_image':
        from .images import read_native
        h,d=attach(job['target']);return read_native(h,job,edit_guard(h,d,job))
    if job['operation'] == 'open_read': return read_document(job)
    if job['operation'] == 'open_edit': return edit(job)
    raise WriterError('INVALID_OPERATION', '허용되지 않은 열린 문서 작업입니다.')
