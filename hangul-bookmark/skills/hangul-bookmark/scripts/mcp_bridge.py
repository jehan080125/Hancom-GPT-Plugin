"""Call the installed nine MCP tools in one persistent session from a JSON job."""
import argparse
import base64
import hashlib
import asyncio
import json
import os
from pathlib import Path
import site

TOOLS={'check_environment','select_document','select_bookmark','preview_content','insert_content','read_document','find_targets','apply_edits','read_image'}

def resolve(value, results):
    if isinstance(value,dict):
        if set(value)=={'$ref'}:
            parts=value['$ref'].split('.')
            current=results[parts[0]]
            for part in parts[1:]: current=current[int(part)] if isinstance(current,list) else current[part]
            return current
        return {k:resolve(v,results) for k,v in value.items()}
    if isinstance(value,list): return [resolve(v,results) for v in value]
    return value

async def run(job,config,report,root):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    env=os.environ.copy(); env.update(config.get('env',{}))
    results={}
    async with Client(StdioServerParameters(command=config['command'],args=config['args'],env=env,cwd=root)) as client:
        for step in job:
            arguments=resolve(step.get('arguments',{}),results)
            # Record the pending tool before calling it. Never retry on exceptions:
            # insertion may have taken effect even when the response is lost.
            report.write_text(json.dumps({'completed':results,'pending':step['id'],'tool':step['tool'],'arguments':arguments},ensure_ascii=False,indent=2),encoding='utf-8')
            response=await client.call_tool(step['tool'],arguments)
            data=response.structured_content or json.loads(response.content[0].text)
            image_paths=[]
            for index,block in enumerate(response.content):
                if block.type=='image':
                    folder=report.parent/(report.stem+'-images');folder.mkdir(exist_ok=True)
                    name=hashlib.sha256(step['id'].encode()).hexdigest()[:20]+'-'+str(index)+'.png'
                    path=folder/name;path.write_bytes(base64.b64decode(block.data,validate=True))
                    image_paths.append(str(path.resolve()))
            if image_paths:data['image_paths']=image_paths
            results[step['id']]=data
            report.write_text(json.dumps({'completed':results,'pending':None},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'step':step['id'],'result':data},ensure_ascii=False),flush=True)
            if response.is_error or not data.get('ok'): return 1
    return 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[3]
    config=json.loads((root/'mcp.json').read_text('utf-8'))['mcpServers']['hangul-bookmark']
    site.addsitedir(config['env']['HANGUL_DEPS'])
    job=json.loads(args.job.read_text('utf-8-sig'))
    if not isinstance(job,list) or not job or any(s.get('tool') not in TOOLS or not isinstance(s.get('id'),str) for s in job):
        parser.error('Job must be a nonempty list of named steps using the nine plugin tools')
    if len({s['id'] for s in job})!=len(job): parser.error('Step IDs must be unique')
    for s in job:
        if s['tool'] in ('insert_content','apply_edits') and not s.get('arguments',{}).get('request_id'):
            parser.error('Mutation requires a persistent request_id')
    if args.result.exists(): parser.error('Result already exists; inspect it before any retry')
    args.result.parent.mkdir(parents=True,exist_ok=True)
    raise SystemExit(asyncio.run(run(job,config,args.result.resolve(),root)))

if __name__=='__main__': main()
