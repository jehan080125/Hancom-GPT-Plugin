"""Emit absolute local MCP wiring; called after dependency installation."""
import argparse
import json
from pathlib import Path
import sys
import os
parser=argparse.ArgumentParser()
parser.add_argument('--deps',type=Path)
parser.add_argument('--state',type=Path,help='Optional writable local state/work directory')
args=parser.parse_args()
root=Path(__file__).resolve().parent
deps=(args.deps or root/'runtime/deps').resolve()
# Agent Plugins reject absolute executable paths. Select the configured Python
# through PATH while keeping the executable name bare.
entry={'command':Path(sys.executable).name,'args':['./launch.py'],
       'env':{'HANGUL_DEPS':str(deps),'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')}}
if args.state:
    entry['args'].extend(['--state',str(args.state.resolve())])
(root/'.mcp.json').write_text(json.dumps({'mcpServers':{'hangul-bookmark':entry}},ensure_ascii=False,indent=2),encoding='utf-8')
entry=dict(entry,type='stdio')
(root/'mcp.json').write_text(json.dumps({'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'hangul-bookmark':entry}},ensure_ascii=False,indent=2),encoding='utf-8')
print('MCP wiring configured: '+str(root))
