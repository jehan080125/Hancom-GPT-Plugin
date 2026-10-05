"""Bootstrap a private dependency directory, never the user's global Python."""
import os
from pathlib import Path
import site
import sys

root = Path(__file__).resolve().parent
deps = Path(os.environ.get('HANGUL_DEPS', root / 'runtime' / 'deps'))
if deps.exists():
    site.addsitedir(str(deps))
    os.environ['HANGUL_DEPS'] = str(deps)
    paths = [deps, deps / 'win32', deps / 'win32' / 'lib', deps / 'Pythonwin']
    sys.path[:0] = [str(p) for p in paths]
    os.environ['PYTHONPATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get('PYTHONPATH', '')
sys.path.insert(0, str(root / 'src'))
if __name__ == '__main__':
    from hangul_bookmark.server import main
    main()
