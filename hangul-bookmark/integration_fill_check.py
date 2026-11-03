"""Disposable native empty-paragraph fill check; never choose a user document."""
import argparse
import json
from pathlib import Path
import launch
from hangul_bookmark.backend import Hancom,finalize_sta
from hangul_bookmark import native_edit as ne,document as dm
from hangul_bookmark.service import digest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    results=[]
    try:
        for ext in ('.hwp','.hwpx'):
            h=Hancom(visible=False)
            try:
                w=h.hwp
                w.insert_text('보존 문장');w.Run('BreakPara');w.Run('BreakPara')
                w.create_table(rows=1,cols=2,header=False)
                source=out/('source'+ext);target=out/('filled'+ext)
                h.save(source);old_hash=digest(source);h.open(source)
                before=ne.inspect(h)
                blanks=[p for p in before['paragraphs'] if not p['parts'] and p['length']==0 and p['scope']!='excluded']
                body=next(p for p in blanks if p['scope']=='body')
                cells=[p for p in blanks if p['scope']=='table']
                assert len(cells)==2
                edits=[{'type':'insert_blocks','target_id':body['id'],'expected_text':'','blocks':[
                    {'type':'text','text':'새 풀이 '},
                    {'type':'equation','format':'latex','script':'x^{2}+1'},
                    {'type':'paragraph_break'},
                    {'type':'text','text':'검증 완료'}]}]
                for i,p in enumerate(cells):
                    edits.append({'type':'insert_blocks','target_id':p['id'],'expected_text':'',
                                  'blocks':[{'type':'text','text':'셀 '+str(i+1)}]})
                ops=dm.compile_edits(before,edits)
                result=ne.apply_native(h,before,ops)
                h.save(target);h.open(target);after=ne.inspect(h);dm.verify_edit(before,after,ops)
                assert digest(source)==old_hash and not after['bookmarks']
                texts=[p['text'] for p in after['paragraphs']]
                assert all(t in texts for t in ('보존 문장','검증 완료','셀 1','셀 2'))
                result.update(format=ext,version=list(h.version),ok=True,source_preserved=True,bookmarks_created=False)
                results.append(result)
                (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'format':ext,'ok':True,'version':list(h.version),'counts':result['counts']},ensure_ascii=False),flush=True)
            finally:h.close()
    finally:finalize_sta()


if __name__=='__main__':main()
