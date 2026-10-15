import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from . import __version__, content
from .errors import WriterError

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def dumps(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)

@contextlib.contextmanager
def guard_file(path):
    """Windows: deny external writes but allow atomic replacement of the file."""
    handle = None
    if sys.platform == 'win32':
        import win32file, win32con
        try:
            handle = win32file.CreateFile(str(path), win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_DELETE, None,
                win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
        except Exception: raise WriterError('FILE_LOCKED', '대상 파일이 다른 프로그램에서 편집 중입니다. 저장하고 닫은 후 다시 시도하세요.') from None
    def release():
        nonlocal handle
        if handle: handle.Close(); handle = None
    try: yield release
    finally:
        if handle: handle.Close()

class Runner:
    def __init__(self, state): self.state = state; self.live_worker = None

    def close(self):
        if self.live_worker: self.live_worker.close()

    def __call__(self, job):
        if job['operation'].startswith('open_'):
            from .live_worker import LiveWorker
            if self.live_worker is None: self.live_worker = LiveWorker()
            return self.live_worker(job)
        with tempfile.TemporaryDirectory(prefix='job-', dir=self.state) as temp:
            env = os.environ.copy(); env['HANGUL_PID_FILE'] = str(Path(temp) / 'pid')
            env['HANGUL_COM_CACHE_DIR'] = temp
            env['PYTHONIOENCODING'] = 'utf-8'
            # The launcher adds local dependency directories to PYTHONPATH.
            src = str(Path(__file__).resolve().parents[1])
            env['PYTHONPATH'] = src + os.pathsep + env.get('PYTHONPATH', '')
            p = subprocess.Popen([sys.executable, '-m', 'hangul_bookmark.backend'], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                stdout, stderr = p.communicate(dumps(job), timeout=120)
            except subprocess.TimeoutExpired:
                p.kill(); p.communicate()
                pidfile = Path(temp) / 'pid'
                if pidfile.exists() and sys.platform == 'win32' and not job['operation'].startswith('open_'):
                    import win32api, win32con
                    try:
                        handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, int(pidfile.read_text()))
                        win32api.TerminateProcess(handle, 1); handle.Close()
                    except Exception: pass
                message = ('열린 문서 작업이 시간 초과됐습니다. 사용자 창은 닫지 않았습니다. 요청을 반복하지 말고 창과 복원용 사본을 확인하세요.'
                           if job['operation'].startswith('open_') else '한글 작업이 120초 안에 끝나지 않았습니다. 승인 창이나 한글 상태를 확인하세요. 수정본은 교체하지 않았습니다.')
                raise WriterError('HANCOM_TIMEOUT', message) from None
            try: result = json.loads(stdout)
            except ValueError:
                raise WriterError('BACKEND_FAILED', '한글 연결 프로그램 실행 실패: ' + stderr[-1200:]) from None
            if not result.get('ok'): raise WriterError(result.get('error', 'HANCOM_FAILED'), result.get('message', '한글 작업 실패'))
            return result

from .editing import EditingService

class Service(EditingService):
    def __init__(self, state, runner=None, dialogs=None):
        self.state = Path(state).resolve(); self.state.mkdir(parents=True, exist_ok=True)
        self.runner = runner or Runner(self.state)
        if dialogs is None:
            from . import dialogs
        self.dialogs = dialogs
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.state / 'state.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (doc TEXT, id TEXT, hash TEXT, status TEXT, data TEXT, PRIMARY KEY(doc,id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS analyses (doc TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        close = getattr(self.runner, 'close', None)
        if close: close()
        self.db.close()

    def _load(self, document_id):
        row = self.db.execute('SELECT data FROM documents WHERE id=?', (document_id,)).fetchone()
        if not row: raise WriterError('DOCUMENT_MISSING', '파일을 먼저 선택하세요.')
        return json.loads(row[0])

    def _put(self, doc):
        self.db.execute('INSERT OR REPLACE INTO documents VALUES (?,?)', (doc['document_id'], dumps(doc)))

    def check_environment(self, run_smoke=True):
        with self.lock:
            env = self.runner({'operation': 'environment'})
            code_hash = hashlib.sha256(''.join(digest(Path(__file__).with_name(f)) for f in ('backend.py', 'live.py', 'xmlcheck.py', 'latex.py', 'content.py', 'adapters.py', 'document.py', 'native_edit.py', 'editing.py', 'com_runtime.py')).encode()).hexdigest()
            fingerprint = dumps({'version': env['version'], 'application': env.get('application'), 'connector': __version__, 'code': code_hash, 'module': env['security_module']})
            cache = self.state / 'compatibility.json'
            previous = json.loads(cache.read_text('utf-8')) if cache.exists() else {}
            if not run_smoke: return env
            if previous.get('fingerprint') == fingerprint and previous.get('ok'):
                return dict(previous['report'], cached=True)
            with tempfile.TemporaryDirectory(prefix='smoke-', dir=self.state) as directory:
                report = self.runner({'operation': 'smoke', 'directory': directory})
            report.update(application=env.get('application'), adapter=env.get('adapter'))
            if not env['security_module']:
                report['environment_warnings'] = ['한컴 보안 모듈이 로드되지 않았습니다. 파일 접근 승인 창이 표시되면 직접 승인하세요.']
            record = {'ok': True, 'fingerprint': fingerprint, 'report': report}
            tmp = cache.with_suffix('.tmp'); tmp.write_text(dumps(record), encoding='utf-8'); os.replace(tmp, cache)
            return report

    def select_document(self, path=None, mode='file', window_id=None, list_only=False):
        with self.lock:
            if mode == 'open': return self._select_open(window_id, list_only, path)
            if mode != 'file' or window_id is not None or list_only:
                raise WriterError('INVALID_SELECTION', 'mode는 file 또는 open이며 열린 창 선택 옵션은 open에서만 사용합니다.')
            path = path or self.dialogs.choose_file()
            if not path: return {'ok': True, 'cancelled': True}
            self.check_environment()
            source = Path(path).expanduser().resolve()
            if source.suffix.lower() not in ('.hwp', '.hwpx') or not source.is_file():
                raise WriterError('INVALID_FILE', '.hwp 또는 .hwpx 파일을 선택하세요.')
            with guard_file(source):
                original_hash = digest(source)
                with tempfile.TemporaryDirectory(prefix='inspect-', dir=self.state) as tmp:
                    copy = Path(tmp) / source.name; shutil.copyfile(source, copy)
                    report = self.runner({'operation': 'inspect', 'path': str(copy)})
                if digest(source) != original_hash: raise WriterError('EXTERNAL_CHANGE', '파일 선택 중 원본이 변경되었습니다.')
            index = 1
            while True:
                extra = '' if index == 1 else f'_{index}'
                output = source.with_name(source.stem + '_수정본' + extra + source.suffix)
                if not output.exists(): break
                index += 1
            doc = {'document_id': str(uuid.uuid4()), 'source': str(source), 'source_hash': original_hash,
                   'active': str(source), 'active_hash': original_hash, 'output': str(output), 'bookmark': None,
                   'bookmarks': report['bookmarks'], 'version': report['version']}
            with self.db: self._put(doc)
            return {'ok': True, **doc, 'security_module': report['security_module']}

    def _select_open(self, window_id, list_only, path):
        if path is not None: raise WriterError('INVALID_SELECTION', '열린 문서 선택에는 파일 경로 대신 window_id를 사용하세요.')
        items = self.runner({'operation': 'open_list'})['documents']
        public = [{k: v for k, v in d.items() if k != 'target'} for d in items]
        if list_only: return {'ok': True, 'mode': 'open', 'documents': public}
        if not items: raise WriterError('NO_OPEN_DOCUMENT', '열려 있는 한글 문서가 없습니다. 문서를 열고 다시 선택하세요.')
        if window_id is None:
            window_id = items[0]['window_id'] if len(items) == 1 else self.dialogs.choose_open_document(public)
            if window_id is None: return {'ok': True, 'cancelled': True}
        selected = next((d for d in items if d['window_id'] == window_id), None)
        if selected is None: raise WriterError('OPEN_DOCUMENT_CLOSED', '선택한 열린 문서를 찾지 못했습니다. 목록을 다시 확인하세요.')
        self.check_environment()
        report = self.runner({'operation': 'open_inspect', 'target': selected['target']})
        doc = {'document_id': str(uuid.uuid4()), 'mode': 'open', 'target': selected['target'],
               'window_id': window_id, 'title': selected['title'], 'file': selected['file'],
               'active': selected['file'], 'output': None, 'bookmark': None,
               'bookmarks': report['bookmarks'], 'version': report['version'], 'saved': False, 'selection': report.get('selection')}
        with self.db: self._put(doc)
        return {'ok': True, **{k: v for k, v in doc.items() if k != 'target'},
                'modified': report['modified'], 'security_module': report['security_module']}

    def select_bookmark(self, document_id, name=None):
        with self.lock:
            doc = self._load(document_id)
            if doc.get('mode') == 'open':
                report = self.runner({'operation': 'open_inspect', 'target': doc['target']})
                doc['bookmarks'] = report['bookmarks']
            valid = [b['name'] for b in doc['bookmarks'] if b['scope'] != 'unsupported' and not b['ambiguous']]
            if not valid: raise WriterError('BOOKMARK_MISSING', '본문 또는 표 셀에 책갈피를 미리 만들어 주세요.')
            name = name or self.dialogs.choose_bookmark(valid)
            if name is None: return {'ok': True, 'cancelled': True}
            if name not in valid: raise WriterError('BOOKMARK_MISSING', '사용할 수 없는 책갈피입니다: ' + name)
            doc['bookmark'] = name
            with self.db: self._put(doc)
            return {'ok': True, 'document_id': document_id, 'bookmark': name, 'file': doc['active'], 'output': doc['output']}

    def preview_content(self, blocks):
        if not isinstance(blocks, list) or not blocks or len(blocks) > 2000:
            raise WriterError('INVALID_CONTENT', '1~2,000개의 내용 블록을 전달하세요.')
        normalized, issues = [], []
        for index, block in enumerate(blocks):
            try: normalized.extend(content.normalize([block]))
            except WriterError as e: issues.append({'index': index, 'original': block, **e.result()})
        return {'ok': not issues, 'blocks': normalized, 'issues': issues, 'counts': content.counts(normalized), 'writes_document': False}

    def _recover(self, doc, request_id, payload_hash):
        row = self.db.execute('SELECT hash,status,data FROM requests WHERE doc=? AND id=?', (doc['document_id'], request_id)).fetchone()
        if not row: return None
        if row[0] != payload_hash: raise WriterError('REQUEST_CONFLICT', '같은 요청 ID를 다른 내용이나 책갈피에 재사용할 수 없습니다.')
        data = json.loads(row[2])
        if row[1] == 'done': return dict(data['result'], replayed=True)
        if row[1] == 'live_pending':
            path = Path(data['receipt'])
            if path.exists():
                result = json.loads(path.read_text('utf-8'))
                if result.get('ok'):
                    result.update(document_id=doc['document_id'], request_id=request_id)
                    result.setdefault('bookmark',data.get('bookmark'))
                    result.setdefault('counts',data.get('counts',{}))
                    with self.db:
                        self.db.execute('UPDATE requests SET status=?,data=? WHERE doc=? AND id=?', ('done', dumps({'result': result}), doc['document_id'], request_id))
                    return dict(result, replayed=True, recovered=True)
            raise WriterError('LIVE_RECOVERY_REQUIRED', '이 열린 문서 요청의 완료를 확정할 수 없습니다. 중복 작성을 막기 위해 재삽입하지 않습니다. 창과 복원용 사본을 확인하세요: ' + data['backup'])
        target = Path(data['output'])
        if target.exists() and digest(target) == data['expected_hash']:
            doc['active'] = str(target); doc['active_hash'] = data['expected_hash']
            with self.db:
                self._put(doc)
                self.db.execute('UPDATE requests SET status=? WHERE doc=? AND id=?', ('done', doc['document_id'], request_id))
            return dict(data['result'], replayed=True, recovered=True)
        raise WriterError('RECOVERY_REQUIRED', '이 요청의 저장 완료 여부를 확인할 수 없습니다. 문서를 확인하고 새로 선택하세요.')

    def insert_content(self, document_id, request_id, blocks, bookmark=None):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise WriterError('INVALID_REQUEST', '1~128자의 고유 request_id가 필요합니다.')
        normalized = content.normalize(blocks)
        for b in normalized:
            if b['type'] == 'image': b['sha256'] = digest(b['path'])
        with self.lock:
            doc = self._load(document_id)
            name = bookmark or doc['bookmark']
            if not name: raise WriterError('BOOKMARK_MISSING', '책갈피를 먼저 선택하세요.')
            payload_hash = hashlib.sha256(dumps({'bookmark': name, 'blocks': normalized}).encode('utf-8')).hexdigest()
            replay = self._recover(doc, request_id, payload_hash)
            if replay: return replay
            if doc.get('mode') == 'open':
                return self._insert_open(doc, request_id, normalized, name, payload_hash)
            self.check_environment()
            valid = [b['name'] for b in doc['bookmarks'] if b['scope'] != 'unsupported' and not b['ambiguous']]
            if name not in valid: raise WriterError('BOOKMARK_MISSING', '선택한 문서에 해당 책갈피가 없습니다.')
            # Resolve earlier pending commits before a new request can mutate this document.
            pending = self.db.execute('SELECT id,hash FROM requests WHERE doc=? AND status=?', (document_id, 'pending')).fetchall()
            for rid, ph in pending: self._recover(doc, rid, ph)
            source, active, output = Path(doc['source']), Path(doc['active']), Path(doc['output'])
            if not source.exists() or digest(source) != doc['source_hash']:
                raise WriterError('EXTERNAL_CHANGE', '원본이 변경되었습니다. 파일을 다시 선택하세요.')
            if not active.exists() or digest(active) != doc['active_hash']:
                raise WriterError('EXTERNAL_CHANGE', '수정본이 외부에서 변경되었습니다. 파일을 다시 선택하세요.')
            with tempfile.TemporaryDirectory(prefix='.hangul-job-', dir=output.parent) as temp:
                stage = Path(temp) / output.name
                with guard_file(active) as release:
                    shutil.copyfile(active, stage)
                    report = self.runner({'operation': 'write', 'path': str(stage), 'bookmark': name, 'blocks': normalized})
                    if digest(active) != doc['active_hash']: raise WriterError('EXTERNAL_CHANGE', '작업 중 대상 문서가 변경되었습니다.')
                    if digest(source) != doc['source_hash']: raise WriterError('EXTERNAL_CHANGE', '작업 중 원본이 변경되었습니다.')
                    for b in normalized:
                        if b['type'] == 'image' and digest(b['path']) != b['sha256']:
                            raise WriterError('EXTERNAL_CHANGE', '작업 중 입력 이미지가 변경되었습니다.')
                    expected = digest(stage)
                    result = {'ok': True, 'document_id': document_id, 'request_id': request_id,
                              'output': str(output), 'bookmark': name, 'counts': content.counts(normalized), **report}
                    journal = {'output': str(output), 'expected_hash': expected, 'result': result}
                    with self.db:
                        self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', (document_id, request_id, payload_hash, 'pending', dumps(journal)))
                    try:
                        # MoveFileEx cannot replace a destination held without write sharing.
                        # Hold the write guard throughout COM work; release only at commit.
                        release()
                        if digest(active) != doc['active_hash']: raise WriterError('EXTERNAL_CHANGE', '저장 직전 대상 문서가 변경되었습니다.')
                        if active == source:
                            # Windows rename fails if another process created this output name.
                            if output.exists(): raise WriterError('OUTPUT_COLLISION', '저장 예정 파일이 생겼습니다. 파일을 다시 선택하세요.')
                            os.rename(stage, output)
                        else: os.replace(stage, output)
                    except Exception:
                        with self.db: self.db.execute('DELETE FROM requests WHERE doc=? AND id=?', (document_id, request_id))
                        raise
                    doc['active'], doc['active_hash'], doc['bookmark'] = str(output), expected, name
                    with self.db:
                        self._put(doc)
                        self.db.execute('UPDATE requests SET status=? WHERE doc=? AND id=?', ('done', document_id, request_id))
                    return result

    def _insert_open(self, doc, request_id, blocks, name, payload_hash):
        # A missing receipt is ambiguous after a crash: never blindly reinsert.
        if self.db.execute('SELECT 1 FROM requests WHERE doc=? AND status=?', (doc['document_id'], 'live_pending')).fetchone():
            raise WriterError('LIVE_RECOVERY_REQUIRED', '이 문서에 확인되지 않은 열린 창 작업이 있습니다. 결과와 복원용 사본을 먼저 확인하세요.')
        self.check_environment()
        root = self.state / 'live-backups' / doc['document_id']
        root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(request_id.encode()).hexdigest()
        backup, receipt = root / (key + '.hwp'), root / (key + '.json')
        journal = {'backup': str(backup), 'receipt': str(receipt), 'bookmark': name, 'counts': content.counts(blocks)}
        with self.db:
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)', (doc['document_id'], request_id, payload_hash, 'live_pending', dumps(journal)))
        with tempfile.TemporaryDirectory(prefix='live-stage-', dir=self.state) as temp:
            try:
                report = self.runner({'operation': 'open_write', 'target': doc['target'], 'bookmark': name,
                                      'blocks': blocks, 'backup': str(backup), 'receipt': str(receipt),
                                      'stage': str(Path(temp) / 'preflight.hwp')})
            except WriterError as e:
                if e.code not in ('HANCOM_TIMEOUT', 'BACKEND_FAILED', 'LIVE_RECOVERY_REQUIRED'):
                    with self.db: self.db.execute('DELETE FROM requests WHERE doc=? AND id=?', (doc['document_id'], request_id))
                raise
        result = {**report, 'document_id': doc['document_id'], 'request_id': request_id, 'bookmark': name, 'counts': content.counts(blocks)}
        with self.db:
            doc['bookmark'] = name; self._put(doc)
            self.db.execute('UPDATE requests SET status=?,data=? WHERE doc=? AND id=?', ('done', dumps({'result': result}), doc['document_id'], request_id))
        return result
