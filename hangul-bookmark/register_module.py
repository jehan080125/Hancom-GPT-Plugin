"""Explicit opt-in: current-user Hancom module registration only."""
import os
from pathlib import Path
import winreg
root = Path(__file__).resolve().parent
deps = Path(os.environ.get('HANGUL_DEPS', root / 'runtime' / 'deps'))
candidates = list((root / 'security').glob('FilePathCheckerModule.dll')) or list((deps / 'pyhwpx').rglob('FilePathCheckerModule.dll'))
if len(candidates) != 1: raise SystemExit('FilePathCheckerModule.dll을 찾지 못했습니다.')
dll = str(candidates[0].resolve())
for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
    for key in (r'Software\HNC\HwpAutomation\Modules', r'Software\HNC\HwpUserAction\Modules'):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE | view) as handle:
            winreg.SetValueEx(handle, 'HangulBookmark', 0, winreg.REG_SZ, dll)
print('HangulBookmark 등록: ' + dll)
