"""Generate disposable native documents; never use a user's original as a fixture."""
import argparse
import json
from pathlib import Path
import traceback
import launch  # bootstrap private Python libraries and src path
from hangul_bookmark.backend import Hancom
from hangul_bookmark.content import normalize
from hangul_bookmark.service import Service, digest
from PIL import Image, ImageDraw

def main():
    parser=argparse.ArgumentParser(description='한글 실제 시험: 임시 본문/표/범위 문서 생성, 수식·그림 작성 및 재열기')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'runtime'/'integration')
    args=parser.parse_args()
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()): raise SystemExit('비어 있는 시험 출력 폴더를 지정하세요.')
    im=Image.new('RGB',(400,240),'white')
    ImageDraw.Draw(im).line((20,200,180,30,370,180),fill='black',width=3); im.save(out/'graph.png')
    results=[]; h=Hancom()
    try:
        for ext in ('.hwp','.hwpx'):
            for location in ('body','table','range'):
                try:
                    h.hwp.clear(1)
                    if location=='table': h.hwp.create_table(rows=2,cols=2,header=False)
                    h.hwp.insert_text('앞 '); start=h.hwp.get_pos()
                    if location=='range':
                        h.hwp.insert_text('기존 범위'); end=h.hwp.get_pos()
                        h.hwp.select_text_by_get_pos(start,end); h.bookmark('목표',0)
                        h.hwp.Cancel(); h.hwp.MoveLineEnd()
                    else: h.bookmark('목표',0)
                    h.hwp.insert_text(' 뒤'); path=out/(location+ext); h.save(path); h.hwp.clear(1)
                    blocks=normalize([
                        {'type':'text','text':'새 본문 '},
                        {'type':'equation','format':'latex','script':r'\frac{1}{2}+x_{i}^{2}+\sqrt{x}+\sum_{i=1}^{n}i+\int_0^1 x dx','display':'inline'},
                        {'type':'paragraph_break'},
                        {'type':'equation','format':'latex','script':r'\begin{pmatrix}1&2\\3&4\end{pmatrix}','display':'block'},
                        {'type':'image','path':str(out/'graph.png'),'crop':[0,0,400,240]}])
                    h.write(path,'목표',blocks); h.hwp.clear(1)
                    result=h.write(path,'목표',[{'type':'text','text':'반복 '}])
                    results.append({'file':str(path),'location':location,'ok':True,'result':result})
                except Exception as e:
                    results.append({'format':ext,'location':location,'ok':False,'error':str(e),'traceback':traceback.format_exc()})
    finally: h.close()
    svc=Service(out/'state')
    try:
        for ext in ('.hwp','.hwpx'):
            source=out/('body'+ext); old=digest(source)
            doc=svc.select_document(str(source)); svc.select_bookmark(doc['document_id'],'목표')
            blocks=[{'type':'text','text':'서비스 시험 '},{'type':'equation','format':'latex','script':r'\frac{3}{4}','display':'inline'}]
            svc.insert_content(doc['document_id'],'request-1',blocks)
            repeated=svc.insert_content(doc['document_id'],'request-1',blocks)
            result=svc.insert_content(doc['document_id'],'request-2',[{'type':'text','text':'다음 시험 '}])
            assert repeated['replayed'] and digest(source)==old
            results.append({'format':ext,'transaction':True,'ok':True,'original_unchanged':True,'dedup':True,'result':result})
    finally: svc.close()
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(r['ok'] for r in results) else 1

if __name__=='__main__': raise SystemExit(main())
