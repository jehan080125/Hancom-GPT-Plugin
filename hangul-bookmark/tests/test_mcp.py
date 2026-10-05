"""Real stdio handshake and tool invocation; no Hancom document modification."""
import asyncio
import json
import os
from pathlib import Path
import sys
import hangul_bookmark  # Bootstrap private dependency/.pth paths for a standalone run.

def test_stdio():
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    root=Path(__file__).resolve().parents[1]
    async def run():
        env=os.environ.copy()
        async with Client(StdioServerParameters(command=sys.executable,args=[str(root/'launch.py'),'--state',str(root/'runtime'/'test-state')],env=env)) as client:
            listing=await client.list_tools()
            assert {t.name for t in listing.tools}=={'check_environment','select_document','select_bookmark','preview_content','insert_content'}
            result=await client.call_tool('preview_content',{'blocks':[{'type':'equation','format':'latex','script':r'\frac{1}{2}'}]})
            assert not result.is_error
            data = result.structured_content or json.loads(result.content[0].text)
            assert data['ok']
            assert data['blocks'][0]['script']=='{1} over {2}'
    asyncio.run(run())
