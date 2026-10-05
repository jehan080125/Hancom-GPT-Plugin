"""Five-purpose stdio MCP interface; no arbitrary COM/code tool."""
import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from .errors import WriterError
from .service import Service

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    # COM cache initialization can print diagnostics. Finish it before MCP takes
    # ownership of stdout; never redirect global stdout in a background worker.
    if sys.platform == 'win32':
        with contextlib.redirect_stdout(sys.stderr):
            import win32com.client.gencache
            import pyhwpx
    state = args.state or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'HangulBookmark'
    service = Service(state)
    if args.check or args.smoke:
        try: result = service.check_environment(run_smoke=args.smoke)
        except WriterError as e: result = e.result()
        finally: service.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get('ok') else 1)
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
    server = MCPServer('hangul-bookmark')
    def invoke(fn, *a, **kw):
        try: return fn(*a, **kw)
        except WriterError as e: return e.result()
        except OSError as e: return {'ok': False, 'error': 'FILE_ERROR', 'message': str(e)}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def check_environment(run_smoke: bool = True) -> dict:
        """Check installed Hancom version/APIs; temporary-document smoke test cached per build."""
        return invoke(service.check_environment, run_smoke)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def select_document(path: str | None = None, mode: str = 'file', window_id: str | None = None, list_only: bool = False) -> dict:
        """mode=file: choose file/copy. mode=open: explicitly select a running Hancom document (one auto, multiple local chooser). list_only returns open windows with window_id. Open mode edits that window without saving; never closes it."""
        return invoke(service.select_document, path, mode, window_id, list_only)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def select_bookmark(document_id: str, name: str | None = None) -> dict:
        """Select bookmark by exact name, or show a local list dialog."""
        return invoke(service.select_bookmark, document_id, name)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def preview_content(blocks: list[dict]) -> dict:
        """Validate/convert text, paragraph_break, equation and image blocks without document writes."""
        return invoke(service.preview_content, blocks)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def insert_content(document_id: str, request_id: str, blocks: list[dict], bookmark: str | None = None) -> dict:
        """Insert at bookmark: file mode writes verified copy; open mode edits selected live window, saved=false, user must save. Unique request_id prevents duplicate retry. Blocks: text{text}; paragraph_break; equation{script,format:hwp|latex,display:inline|block}; image{path,crop:[left,top,right,bottom],dpi}. uncertain:true is rejected."""
        return invoke(service.insert_content, document_id, request_id, blocks, bookmark)
    try: server.run(transport='stdio')
    finally: service.close()
