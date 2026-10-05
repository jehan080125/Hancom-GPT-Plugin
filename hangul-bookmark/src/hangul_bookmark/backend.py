"""All COM operations run on this dedicated process's main STA thread."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from .errors import WriterError
from . import xmlcheck
from .adapters import probe

def check(ok, message):
    if not ok: raise WriterError('HANCOM_FAILED', message)

_sta = threading.local()

def initialize_sta():
    if not getattr(_sta, 'ready', False):
        import pythoncom
        pythoncom.CoInitialize()
        _sta.ready = True

def finalize_sta():
    if getattr(_sta, 'ready', False):
        import pythoncom
        _sta.ready = False
        pythoncom.CoUninitialize()

class Hancom:
    def __init__(self, visible=True, com=None):
        if sys.platform != 'win32': raise WriterError('WINDOWS_REQUIRED', 'Windows용 한글 2022 이상이 필요합니다.')
        import pythoncom
        initialize_sta()
        from pyhwpx import Hwp
        class BoundHwp(Hwp):
            # This wrapper did not run Hwp.__init__; manage its STA lifetime here.
            def __del__(self): pass
        from win32com.client import DispatchEx, gencache
        import psutil
        existing_pids = {p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'hwp.exe'}
        self.owned = com is None
        # Hwp(new=True) still uses EnsureDispatch(ProgID), which may attach to a
        # registered instance. DispatchEx explicitly creates a COM object instead.
        self.hwp = object.__new__(BoundHwp)
        self.hwp.hwp = gencache.EnsureDispatch(DispatchEx('HWPFrame.HwpObject') if self.owned else com)
        self.hwp.on_quit = False
        self.hwp.htf_fonts = {}
        if self.owned: self.hwp.XHwpWindows.Active_XHwpWindow.Visible = visible
        self.exclusive_process = False
        self.module = bool(self.hwp.hwp.RegisterModule('FilePathCheckDLL', 'HangulBookmark'))
        self.version = self.hwp.Version
        self.adapter = probe(self.hwp.hwp, self.version)
        self.application = {'com_version': self.version}
        if self.version[0] < 12:
            self.close(); raise WriterError('UNSUPPORTED_VERSION', '연결된 한글이 2022보다 오래되었습니다: ' + str(self.version))
        # Record our own window's PID so the supervisor can close only our process on timeout.
        import win32process
        try:
            hwnd = self.hwp.XHwpWindows.Active_XHwpWindow.WindowHandle
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            self.pid = pid
            self.created_document_id = int(self.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID)
            self.exclusive_process = self.owned and pid not in existing_pids
            import psutil, win32api
            exe = psutil.Process(pid).exe()
            info = win32api.GetFileVersionInfo(exe, '\\')
            ms, ls = info['FileVersionMS'], info['FileVersionLS']
            self.application.update(executable=exe, file_version=[ms >> 16, ms & 65535, ls >> 16, ls & 65535])
            if self.exclusive_process and os.environ.get('HANGUL_PID_FILE'): Path(os.environ['HANGUL_PID_FILE']).write_text(str(pid))
        except Exception: pass

    def close(self):
        h = getattr(self, 'hwp', None)
        if h:
            if getattr(self, 'owned', True):
                if getattr(self, 'exclusive_process', False):
                    # Only a freshly created private process with its original
                    # single document may be cleared and quit by this connector.
                    if h.XHwpDocuments.Count == 1:
                        d = h.XHwpDocuments.Item(0)
                        if int(d.DocumentID) == self.created_document_id:
                            d.Clear(1)
                            h.quit()
                # A shared process may contain user windows. Release the reference
                # instead of clearing/closing its active document or quitting it.
            self.hwp = None
            h.hwp = None
            del h

    def xml(self):
        return self.hwp.get_text_file('HWPML2X', option='')

    def open(self, path):
        self.require_file_access()
        check(self.hwp.open(str(path), arg='lock:false;suspendpassword:true'), '문서를 열지 못했습니다.')

    def save(self, path):
        self.require_file_access()
        fmt = 'HWPX' if Path(path).suffix.lower() == '.hwpx' else 'HWP'
        check(self.hwp.save_as(str(path), format=fmt, arg='lock:false;backup:false'), '문서 저장에 실패했습니다.')

    def require_file_access(self):
        if not self.module and os.environ.get('HANGUL_ALLOW_MANUAL_APPROVAL') != '1':
            raise WriterError('SECURITY_MODULE_REQUIRED', '승인 창 반복을 막기 위해 작업을 중단했습니다. HangulBookmark 보안 모듈이 로드되지 않습니다. 한글 연결/업데이트 후 다시 검사하세요. 직접 승인 시험은 HANGUL_ALLOW_MANUAL_APPROVAL=1을 설정한 경우에만 가능합니다.')

    def bookmark(self, name, command):
        a = self.hwp.create_action('Bookmark'); p = a.CreateSet(); a.GetDefault(p)
        p.SetItem('Name', name); p.SetItem('Command', command)
        check(a.Execute(p), '책갈피 이동/생성에 실패했습니다: ' + name)

    def goto(self, name):
        entries = [b for b in xmlcheck.bookmarks(self.xml()) if b['name'] == name]
        if len(entries) != 1 or entries[0]['ambiguous']: raise WriterError('BOOKMARK_MISSING', '책갈피가 없거나 이름이 중복됩니다: ' + name)
        if entries[0]['scope'] == 'unsupported': raise WriterError('UNSUPPORTED_LOCATION', '본문과 표 셀의 책갈피만 지원합니다.')
        self.bookmark(name, 1)
        selection = self.hwp.get_selected_pos()
        if selection[0]:
            start = tuple(int(x) for x in selection[1:4])
            self.hwp.Cancel(); check(self.hwp.set_pos(*start), '범위 책갈피 시작으로 이동하지 못했습니다.')
        else:
            self.hwp.Cancel()
        return self.hwp.get_pos()

    def equation(self, script, size):
        a = self.hwp.create_action('EquationCreate'); p = a.CreateSet(); a.GetDefault(p)
        p.SetItem('String', script); p.SetItem('BaseUnit', size)
        check(a.Execute(p), '수식 개체를 생성하지 못했습니다.')

    def inspect(self, path):
        self.open(path)
        return {'bookmarks': xmlcheck.bookmarks(self.xml()), 'version': self.version, 'security_module': self.module}

    def write(self, path, name, blocks):
        self.open(path)
        before, start, warnings = self.insert_at_bookmark(name, blocks, Path(path).parent)
        self.save(path)
        h = self.hwp
        h.clear(1); self.open(path)
        after = xmlcheck.snapshot(self.xml())
        xmlcheck.verify(before, after, blocks, name)
        check(tuple(self.goto(name)) == tuple(start), '책갈피 시작 위치가 변경되었습니다.')
        return {'version': self.version, 'security_module': self.module, 'warnings': warnings,
                'verification': {'reopened': True, 'equations': True, 'text': True, 'table_structure': True, 'bookmark_start': True}}

    def insert_at_bookmark(self, name, blocks, directory, cancelled=None, validate_target=None):
        """Shared native insertion; never opens, saves, clears or closes a document."""
        if validate_target: validate_target()
        before = xmlcheck.snapshot(self.xml())
        entry = next((b for b in before['bookmarks'] if b['name'] == name), None)
        start = self.goto(name)
        h = self.hwp
        charshape, parashape = h.get_charshape(), h.get_parashape()
        size = int(h.CharShape.Item('Height'))
        warnings = []
        in_cell = h.is_cell()
        if in_cell:
            margins = h.get_cell_margin()
            ps = h.HParameterSet.HShapeObject
            h.HAction.GetDefault('TablePropertyDialog', ps.HSet)
            width = h.HwpUnitToMili(ps.ShapeTableCell.Width) - margins['left'] - margins['right']
            warnings.append('표 셀의 고정 높이 및 시각적 넘침은 한글에서 확인해야 합니다. 셀 구조와 너비는 보존 검사를 수행했습니다.')
        else:
            ps = h.HParameterSet.HSecDef; h.HAction.GetDefault('PageSetup', ps.HSet)
            width = h.HwpUnitToMili(ps.PageDef.PaperWidth - ps.PageDef.LeftMargin - ps.PageDef.RightMargin - ps.PageDef.GutterLen)
            # Use column width for multicolumn sections when exposed by the API.
            try:
                cp = h.hwp.CreateSet('ColDef'); ca = h.create_action('MultiColumn'); ca.GetDefault(cp)
                n = int(cp.Item('Count') or 1)
                if n > 1: width = (width - h.HwpUnitToMili(int(cp.Item('SameGap') or 0)) * (n - 1)) / n
            except Exception: pass
        if width <= 0: raise WriterError('INVALID_LOCATION', '삽입 영역의 너비를 확인하지 못했습니다.')
        with tempfile.TemporaryDirectory(prefix='images-', dir=directory) as tmp:
            for i, b in enumerate(blocks):
                if validate_target: validate_target()
                if cancelled is not None and cancelled.is_set():
                    raise WriterError('HANCOM_TIMEOUT', '시간 초과로 추가 입력을 중단했습니다.')
                kind = b['type']
                if kind == 'text': check(h.insert_text(b['text']), '본문 입력 실패')
                elif kind == 'paragraph_break':
                    check(h.Run('BreakPara'), '문단 나누기 실패'); h.set_parashape(parashape)
                elif kind == 'equation':
                    if b['display'] == 'block' and h.get_pos()[2] > 0:
                        check(h.Run('BreakPara'), '수식 앞 문단 생성 실패')
                    self.equation(b['script'], size)
                    if b['display'] == 'block': check(h.Run('BreakPara'), '수식 뒤 문단 생성 실패')
                elif kind == 'image':
                    from PIL import Image
                    target = Path(tmp) / f'{i}.png'
                    with Image.open(b['path']) as im:
                        crop = im.crop(b['crop']); crop.save(target)
                        w, ht = crop.size
                    wmm = min(width, w / b['dpi'] * 25.4)
                    ctrl = h.insert_picture(str(target), embedded=True, sizeoption=1, width=wmm, height=wmm * ht / w)
                    check(ctrl, '그림 입력 실패')
                    prop = ctrl.Properties
                    prop.SetItem('Width', round(h.MiliToHwpUnit(wmm)))
                    prop.SetItem('Height', round(h.MiliToHwpUnit(wmm * ht / w)))
                    prop.SetItem('TreatAsChar', True); ctrl.Properties = prop
                    check(int(ctrl.Properties.Item('Width')) <= round(h.MiliToHwpUnit(width)) + 1, '그림 너비가 삽입 영역을 넘습니다.')
                if validate_target: validate_target()
                h.set_charshape(charshape); h.set_parashape(parashape)
            # Keep a point bookmark at the beginning instead of following newly inserted content.
            # Range bookmarks already include their original range and are not recreated.
            if validate_target: validate_target()
            self.goto(name)
            current = h.get_pos()
            if tuple(current) != tuple(start):
                if entry and entry['kind'] == 'range':
                    self.bookmark(name, 1)
                    selection = h.get_selected_pos()
                    check(selection[0], '범위 책갈피의 끝 위치를 확인하지 못했습니다.')
                    end = tuple(int(x) for x in selection[4:7])
                    h.Cancel(); check(h.select_text_by_get_pos(start, end), '범위 책갈피를 복원하지 못했습니다.')
                    self.bookmark(name, 0); h.Cancel()
                else:
                    h.set_pos(*start); self.bookmark(name, 0)
        after = xmlcheck.snapshot(self.xml())
        xmlcheck.verify(before, after, blocks, name)
        check(tuple(self.goto(name)) == tuple(start), '책갈피 시작 위치가 변경되었습니다.')
        return before, start, warnings

    def smoke(self, directory):
        output = []
        for suffix in ('.hwp', '.hwpx'):
            h = self.hwp; h.clear(1)
            check(h.insert_text('원문 앞 '), '시험 본문 입력 실패')
            self.bookmark('입력위치', 0)
            check(h.insert_text(' 원문 뒤'), '시험 본문 입력 실패')
            path = Path(directory) / ('smoke' + suffix)
            self.save(path); h.clear(1)
            blocks = [{'type': 'text', 'text': '새 내용 '}, {'type': 'equation', 'script': '{1} over {2}', 'display': 'inline'}]
            report = self.write(path, '입력위치', blocks)
            first = xmlcheck.snapshot(self.xml())
            h.clear(1)
            self.write(path, '입력위치', [{'type': 'text', 'text': '두 번째 ' }])
            second = xmlcheck.snapshot(self.xml())
            check(second['text'].find('두 번째 ') < second['text'].find('새 내용 '), '반복 삽입 순서가 다릅니다.')
            output.append({'format': suffix, 'ok': True, **report})
        return {'ok': True, 'version': self.version, 'security_module': self.module, 'smoke': output}

def main():
    job = json.load(sys.stdin)
    result = None; backend = None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            op = job['operation']
            if op.startswith('open_'):
                initialize_sta()
                from .live import handle
                result = handle(job)
            else:
                backend = Hancom(visible=job.get('visible', True))
            if op.startswith('open_'): pass
            elif op == 'environment':
                result = {'ok': True, 'version': backend.version, 'security_module': backend.module,
                          'adapter': backend.adapter, 'application': backend.application,
                          'smoke_tested': False}
            elif op == 'inspect': result = {'ok': True, **backend.inspect(job['path'])}
            elif op == 'write': result = {'ok': True, **backend.write(job['path'], job['bookmark'], job['blocks'])}
            elif op == 'smoke': result = backend.smoke(job['directory'])
            else: raise WriterError('INVALID_OPERATION', '허용되지 않은 작업입니다.')
    except WriterError as e: result = e.result()
    except Exception as e: result = {'ok': False, 'error': 'HANCOM_FAILED', 'message': str(e)}
    finally:
        if backend:
            with contextlib.redirect_stdout(sys.stderr):
                try: backend.close()
                except Exception: pass
        elif job['operation'].startswith('open_'):
            from .live import disconnect_all
            disconnect_all()
        finalize_sta()
    print(json.dumps(result, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()
