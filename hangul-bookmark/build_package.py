"""Create source package; runtime dependencies installed by setup.ps1 are excluded."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parent
target=root.parent/'hangul-bookmark-package.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob('*'):
        rel=p.relative_to(root)
        if not p.is_file() or set(rel.parts)&{'__pycache__','runtime','reports','.pytest_cache','.git'} or p.suffix.lower() in {'.pyc','.dll','.hwp','.hwpx','.zip','.sqlite','.sqlite3','.db','.log'} or '.sqlite' in p.name: continue
        if rel.as_posix() in ('.mcp.json','mcp.json'): continue  # setup emits host-specific wiring
        z.write(p,'hangul-bookmark/'+rel.as_posix())
    z.write(root.parent/'.agents/plugins/marketplace.json','.agents/plugins/marketplace.json')
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
print(target)
