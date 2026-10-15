"""Fresh MCP-client acceptance test with disposable file and owned live windows."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import launch
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from hangul_bookmark.backend import Hancom,finalize_sta
from hangul_bookmark.service import digest
from hangul_bookmark import native_edit as ne,live
from integration_edit_check import make_fixture

async def run(root,out):
    config=json.loads((root/'mcp.json').read_text('utf-8'))['mcpServers']['hangul-bookmark']
    args=list(config['args'])
    if '--state' in args:args[args.index('--state')+1]=str(out/'state')
    else:args+=['--state',str(out/'state')]
    env=os.environ.copy();env.update(config.get('env',{}))
    source=out/'source.hwp'
    creator=Hancom(visible=False)
    try:make_fixture(creator,source)
    finally:creator.close()
    original=digest(source);owner=None
    async with Client(StdioServerParameters(command=config['command'],args=args,env=env,cwd=root)) as client:
        listing=await client.list_tools()
        assert {t.name for t in listing.tools}=={'check_environment','select_document','select_bookmark','preview_content','insert_content','read_document','find_targets','apply_edits'}
        async def call(name,**kw):
            result=await client.call_tool(name,kw)
            data=result.structured_content or json.loads(result.content[0].text)
            assert data.get('ok') and not result.is_error,(name,data)
            return data
        async def read(id,scope='all'):
            first=await call('read_document',document_id=id,scope=scope)
            all_blocks=list(first['blocks']);cursor=first['next_cursor']
            while cursor is not None:
                page=await call('read_document',document_id=id,scope=scope,revision=first['revision'],cursor=cursor)
                all_blocks+=page['blocks'];cursor=page['next_cursor']
            return first,all_blocks
        environment=await call('check_environment',run_smoke=True)
        assert all(x['ok'] for x in environment['edit_smoke'])
        doc=await call('select_document',path=str(source))
        first,blocks=await read(doc['document_id']);rev=first['revision']
        found=await call('find_targets',document_id=doc['document_id'],revision=rev,selector={'type':'text','text':'같은 문장','occurrence':2})
        eq=next(b for b in blocks if b['kind']=='equation')
        edits=[{'type':'replace_text','target_id':found['matches'][0]['target_id'],'expected_text':'같은 문장','text':'MCP 수정'},
               {'type':'replace_equation','target_id':eq['target_id'],'expected_script':eq['script'],'format':'latex','script':'z^{2}+1'},
               {'type':'set_format','target_id':'all','properties':{'size_pt':13,'equation_size_pt':13}}]
        result=await call('apply_edits',document_id=doc['document_id'],revision=rev,request_id='mcp-file',edits=edits)
        assert result['saved'] and digest(source)==original
        replay=await call('apply_edits',document_id=doc['document_id'],revision=rev,request_id='mcp-file',edits=edits)
        assert replay['replayed']
        print('MCP file edit passed',flush=True)
        path=out/'live.hwp';shutil.copyfile(source,path)
        owner=Hancom(visible=True)
        try:
            owner.open(path);owner.hwp.MoveDocEnd();owner.hwp.insert_text(' 저장 전 변경')
            before=ne.inspect(owner);p=next(p for p in before['paragraphs'] if p['text']=='같은 문장 같은 문장')
            owner.hwp.select_text_by_get_pos((*p['native'],6),(*p['native'],11))
            target=next(t for t in live.list_documents() if t['target']['pid']==owner.pid and t['target']['native_id']==int(owner.hwp.XHwpDocuments.Active_XHwpDocument.DocumentID))
            doc=await call('select_document',mode='open',window_id=target['window_id'])
            first,blocks=await read(doc['document_id'],scope='selection')
            assert ''.join(b.get('text','') for b in blocks)=='같은 문장'
            edits=[{'type':'replace_text','target_id':blocks[0]['target_id'],'expected_text':'같은 문장','text':'MCP 수정'},
                   {'type':'set_format','target_id':first['selection_target_id'],'properties':{'size_pt':11}}]
            result=await call('apply_edits',document_id=doc['document_id'],revision=first['revision'],request_id='mcp-live',edits=edits)
            assert not result['saved'] and digest(path)==original
            after=ne.inspect(owner)
            assert 'MCP 수정' in ''.join(p['text'] for p in after['paragraphs'])
            # Cell selection is captured separately and restored after reading.
            owner.hwp.get_into_nth_table(0);owner.hwp.TableCellBlock();owner.hwp.TableCellBlockRow()
            doc2=await call('select_document',mode='open',window_id=target['window_id'])
            selected,bb=await read(doc2['document_id'],scope='selection')
            assert len([b for b in bb if b['kind']=='text'])==2 and ne.selected_cells(owner.hwp)==['A1','B1']
            result2=await call('apply_edits',document_id=doc2['document_id'],revision=selected['revision'],request_id='mcp-cells',
                               edits=[{'type':'set_format','target_id':selected['selection_target_id'],'properties':{'size_pt':12}}])
            assert not result2['saved'] and digest(path)==original
            summary={'ok':True,'tools':8,'installed_version':json.loads((root/'plugin.json').read_text('utf-8'))['version'],
                     'version':environment['version'],'file':True,'open':True,'multi_cell_selection':True,'disk_preserved':True,
                     'fresh_mcp_client':True,'edit_smoke':environment['edit_smoke']}
        except Exception:
            owner.close();owner=None;raise
    if owner:
        try:assert 'MCP 수정' in ''.join(p['text'] for p in ne.inspect(owner)['paragraphs'])
        finally:owner.close()
    finalize_sta()
    (out/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    asyncio.run(run(args.root.resolve(),out))
if __name__=='__main__':main()
