"""Bookmark-based Hancom writer. Imports do not launch Hancom."""
__version__ = "0.3.0"
import os
import site
import sys
from pathlib import Path
if os.environ.get('HANGUL_DEPS'):
    deps = Path(os.environ['HANGUL_DEPS'])
    site.addsitedir(str(deps))
    sys.path[:0] = [str(p) for p in (deps, deps/'win32', deps/'win32/lib', deps/'Pythonwin')]
