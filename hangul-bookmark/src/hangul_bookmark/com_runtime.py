"""Isolate generated pywin32 wrappers per connector process, before client import."""
import atexit
import contextlib
import os
from pathlib import Path
import pickle
import sys
import tempfile
import threading

_lock=threading.RLock()
_cache=None

def prepare():
    global _cache
    if sys.platform!='win32':return
    with _lock:
        if _cache is not None:return
        import win32com
        _cache=tempfile.TemporaryDirectory(prefix='hangul-com-',dir=os.environ.get('HANGUL_COM_CACHE_DIR'))
        root=Path(_cache.name)
        # Seed an empty cache so gencache does not Rebuild while
        # win32com.client is still partially initialized.
        with (root/'dicts.dat').open('wb') as f:
            pickle.dump(1,f);pickle.dump({},f)
        (root/'__init__.py').write_text('# Private generated COM wrappers.\n',encoding='utf-8')
        win32com.__gen_path__=str(root)
        win32com.gen_py.__path__=[str(root)]
        atexit.register(_cache.cleanup)
