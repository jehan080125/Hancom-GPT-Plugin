"""Run structural workflows against disposable HWP/HWPX files and windows."""
import argparse
import json
from pathlib import Path

import launch
from PIL import Image
from hangul_bookmark.backend import Hancom,finalize_sta
from hangul_bookmark.service import Service,digest


def text(value):
    return {'type':'text','text':value}


def eq(value):
    return {'type':'equation','format':'latex','script':value}


def make_fixture(hancom,path):
    h=hancom.hwp
    h.insert_text('보존할 제목')
    h.BreakPara()
    h.insert_text('본문 편집 위치입니다.')
    h.BreakPara()
    h.insert_text('표 입력 위치')
    h.BreakPara()
    h.insert_text('삭제할 수식 ')
    hancom.equation('x^{2} +1',1000)
    hancom.save(path)


def core(service,doc,first,second,mode,original_hash):
    did=doc['document_id'];source=Path(doc.get('source') or doc['file'])
    def read():
        return service.read_document(did,limit=100)
    def target(d,selector):
        found=service.find_targets(did,d['revision'],selector)
        assert len(found['matches'])==1,selector
        return found['matches'][0]['target_id']
    d=read()
    edits=[
        {'type':'insert_at','target_id':target(d,{'type':'text','text':'본문'}),'blocks':[text(' 중간 '),{'type':'image','path':str(first)}]},
        {'type':'delete_object','target_id':target(d,{'type':'equation'})},
        {'type':'insert_table','target_id':target(d,{'type':'text','text':'표 입력 위치'}),'rows':2,'columns':2,
         'cells':[[[text('셀 A')],[eq(r'\frac{1}{2}')]],[[{'type':'image','path':str(first)}],[text('셀 D')]]]},
    ]
    r=service.apply_edits(did,d['revision'],'core',edits)
    assert r['saved']==(mode=='file') and digest(source)==original_hash
    assert r['verification']['outside_scope']
    replay=service.apply_edits(did,d['revision'],'core',edits)
    assert replay['replayed']
    d=read()
    assert len(d['tables'])==1
    assert any(b['kind']=='equation' and 'over' in b['script'] for b in d['blocks'])
    pics=[b for b in d['blocks'] if b['kind']=='image']
    assert len(pics)==2 and sum(p['scope']=='body' for p in pics)==1
    edits=[{'type':'replace_range','target_id':next(p['target_id'] for p in pics if p['scope']=='body'),
            'blocks':[{'type':'image','path':str(second)}]}]
    picture=service.apply_edits(did,d['revision'],'replace-photo',edits)
    assert picture['saved']==(mode=='file') and digest(source)==original_hash
    d=read()
    table=target(d,{'type':'table_object','table':1})
    merged=service.apply_edits(did,d['revision'],'merge-table',[{'type':'table_change','target_id':table,
        'action':'merge_cells','range':[1,1,1,2]}])
    assert merged['verification']['outside_scope'] and digest(source)==original_hash
    d=read()
    assert any(b['cell_path'] and b['cell_path'][-1].get('column_span')==2 for b in d['blocks'])
    return {'core':True,'photo_replaced':True,'table_merged':True,'source_preserved':True,
            'saved':r['saved'],'reopened':r['verification']['reopened']}


def review(service,doc,mode,original_hash):
    did=doc['document_id'];source=Path(doc.get('source') or doc['file'])
    def read():
        return service.read_document(did,scope='review',limit=100)
    before=read()
    assert not before['tracking_enabled'] and not before['blocks']
    search=service.find_targets(did,before['revision'],{'type':'review_text','text':'보존할 제목'})
    assert len(search['matches'])==1
    edit={'type':'review_text','target_id':search['matches'][0]['target_id'],
          'expected_text':'보존할 제목','text':'새 제목','tracking':'on_for_request'}
    created=service.apply_edits(did,before['revision'],'track-title',[edit])
    assert created['saved']==(mode=='file') and created['counts']['tracked_changes_created']==2
    current=read()
    assert not current['tracking_enabled'] and len(current['blocks'])==2
    by_type={b['change_type']:b for b in current['blocks']}
    assert by_type['Delete']['text']=='보존할 제목' and by_type['Insert']['text']=='새 제목'
    accept={'type':'review_change','target_id':by_type['Delete']['target_id'],'action':'accept'}
    accepted=service.apply_edits(did,current['revision'],'accept-delete',[accept])
    assert accepted['verification']['review']
    current=read()
    assert len(current['blocks'])==1 and current['blocks'][0]['text']=='새 제목'
    reject={'type':'review_change','target_id':current['blocks'][0]['target_id'],'action':'reject'}
    rejected=service.apply_edits(did,current['revision'],'reject-insert',[reject])
    assert rejected['verification']['review'] and not read()['blocks']
    assert digest(source)==original_hash
    return {'track_restored':True,'accept_one':True,'reject_one':True,'source_preserved':True,
            'saved':rejected['saved'],'reopened':rejected['verification']['reopened']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--file-only',action='store_true')
    parser.add_argument('--scenario',choices=('core','review'),default='core')
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    first=out/'first.png';second=out/'second.png'
    Image.new('RGB',(120,80),'green').save(first)
    Image.new('RGB',(80,120),'blue').save(second)
    results=[]
    for extension in ('.hwp','.hwpx'):
        for mode in ('file',) if args.file_only else ('file','open'):
            path=out/(mode+'-original'+extension)
            fixture=None;service=None
            try:
                fixture=Hancom(visible=mode=='open');make_fixture(fixture,path)
                original=digest(path)
                service=Service(out/('state-'+mode+extension))
                if mode=='file':
                    fixture.close();fixture=None
                    doc=service.select_document(str(path))
                else:
                    fixture.open(path)
                    windows=service.select_document(mode='open',list_only=True)['documents']
                    matches=[w for w in windows if w.get('file') and Path(w['file']).resolve()==path]
                    assert len(matches)==1,'The owned test window was not uniquely found'
                    doc=service.select_document(mode='open',window_id=matches[0]['window_id'])
                result=(core(service,doc,first,second,mode,original) if args.scenario=='core'
                        else review(service,doc,mode,original))
                row={'format':extension,'mode':mode,'ok':True,**result}
            except Exception as e:
                row={'format':extension,'mode':mode,'ok':False,'error':getattr(e,'code',type(e).__name__),'message':str(e)}
            finally:
                if service:service.close()
                if fixture:fixture.close()
                finalize_sta()
            results.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['ok'] for r in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
