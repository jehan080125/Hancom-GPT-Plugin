"""Disposable native embedded-image/MCP acceptance; never select a user document."""
import argparse
import asyncio
import base64
import io
import json
import os
import sys
from pathlib import Path
import launch
from PIL import Image,ImageDraw
from hangul_bookmark.backend import Hancom,finalize_sta
from hangul_bookmark.service import Service,digest
from hangul_bookmark import document as dm,native_edit as ne
from integration_edit_check import read_all

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--root',type=Path);args=ap.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    image=Image.new('RGB',(900,280),'white');draw=ImageDraw.Draw(image)
    draw.text((35,40),'E = mc^2',fill='black',font_size=55)
    draw.text((35,145),'2 + 2 = 4',fill='black',font_size=55)
    image.save(out/'source.png')
    reports=[]
    owner=Hancom(visible=True)
    try:
        w=owner.hwp
        w.insert_text('Body photo ');w.insert_picture(str(out/'source.png'),embedded=True)
        w.Run('BreakPara');w.create_table(rows=1,cols=1,header=False);w.insert_text('Cell photo ')
        w.insert_picture(str(out/'source.png'),embedded=True)
        w.Run('BreakPara');w.create_table(rows=1,cols=1,header=False);w.insert_text('Nested photo ')
        w.insert_picture(str(out/'source.png'),embedded=True)
        for ext in ('.hwp','.hwpx'):owner.save(out/('source'+ext))
        owner.close();owner=None
        for ext in ('.hwp','.hwpx'):
            path=out/('source'+ext);before_hash=digest(path)
            for mode in ('file','open'):
                print('testing '+ext+' '+mode,flush=True)
                if mode=='open':
                    owner=Hancom(visible=True);owner.open(path);w=owner.hwp
                    w.MoveDocBegin();w.MoveSelParaEnd()
                    selection=tuple(w.get_selected_pos());before_xml=dm.revision(owner.xml())
                s=Service(out/('state-'+ext[1:]+'-'+mode))
                try:
                    if mode=='open':
                        listed=s.runner({'operation':'open_list'})
                        native_id=int(w.XHwpDocuments.Active_XHwpDocument.DocumentID)
                        match=next(x for x in listed['documents'] if x['target']['native_id']==native_id and x['target']['pid']==owner.pid)
                        selected=s.select_document(mode='open',window_id=match['window_id'])
                    else:selected=s.select_document(str(path))
                    id=selected['document_id'];read,blocks=read_all(s,id)
                    pictures=[b for b in blocks if b['kind']=='image']
                    assert len(pictures)==3 and pictures[-1]['scope']=='table' and len(pictures[-1]['cell_path'])==4
                    for n,picture in enumerate(pictures):
                        result=s.read_image(id,read['revision'],picture['target_id'])
                        raw=base64.b64decode(result['image_base64'])
                        assert Image.open(io.BytesIO(raw)).size==(900,280)
                        (out/(mode+ext[1:]+'-'+str(n)+'.png')).write_bytes(raw)
                    result=s.read_image(id,read['revision'],pictures[0]['target_id'],crop=[0,0,1,.5],max_edge=512)
                    assert result['returned_pixels'][0]==512
                    if mode=='open':
                        assert tuple(w.get_selected_pos())==selection
                        assert dm.revision(owner.xml())==before_xml
                        w.Cancel();w.MoveDocEnd();w.insert_text('unsaved')
                        try:s.read_image(id,read['revision'],pictures[0]['target_id'])
                        except Exception as e:assert getattr(e,'code',None)=='STALE_REVISION'
                        else:raise AssertionError('stale read allowed')
                        assert digest(path)==before_hash
                        w.Undo()
                    assert digest(path)==before_hash
                    reports.append({'format':ext,'mode':mode,'images':3,'nested_table':True,'unchanged':True,'ok':True})
                finally:
                    s.close()
                    if mode=='open':owner.close();owner=None
                (out/'results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
        root=(args.root or Path(__file__).resolve().parent).resolve()
        async def mcp_check():
            from mcp import Client
            from mcp.client.stdio import StdioServerParameters
            env=os.environ.copy()
            async with Client(StdioServerParameters(command=sys.executable,args=[str(root/'launch.py'),'--state',str(out/'mcp-state')],env=env,cwd=root)) as client:
                listing=await client.list_tools();assert len(listing.tools)==9 and any(t.name=='read_image' for t in listing.tools)
                async def call(name,arguments):
                    r=await client.call_tool(name,arguments)
                    assert not r.is_error,(name,r)
                    return r,r.structured_content or json.loads(r.content[0].text)
                _,selected=await call('select_document',{'path':str(out/'source.hwp')})
                _,read=await call('read_document',{'document_id':selected['document_id'],'limit':100})
                pic=next(b for b in read['blocks'] if b['kind']=='image')
                r,result=await call('read_image',{'document_id':selected['document_id'],'revision':read['revision'],'target_id':pic['target_id']})
                content=next(c for c in r.content if c.type=='image')
                assert content.mime_type=='image/png' and 'image_base64' not in result
                (out/'mcp-image.png').write_bytes(base64.b64decode(content.data))
                bad=await client.call_tool('read_image',{'document_id':selected['document_id'],'revision':'old','target_id':pic['target_id']})
                assert bad.is_error
                reports.append({'mode':'fresh-stdio','tools':9,'actual_image_content':True,'ok':True})
        asyncio.run(mcp_check())
        (out/'results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(reports,ensure_ascii=False),flush=True)
    finally:
        if owner:owner.close()
        finalize_sta()

if __name__=='__main__':main()
