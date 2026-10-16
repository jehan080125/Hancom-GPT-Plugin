"""Service transactions for revision-bound reads, searches and bounded changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from . import document as dm
from .errors import WriterError

class EditingService:
    def _analysis(self,doc):
        from .service import guard_file,digest
        if doc.get('mode')=='open':
            result=self.runner({'operation':'open_read','target':doc['target'],'selection':doc.get('selection')})
        else:
            active=Path(doc['active'])
            if digest(active)!=doc['active_hash'] or digest(doc['source'])!=doc['source_hash']:
                dm.fail('EXTERNAL_CHANGE','선택 이후 파일이 변경됐습니다. 다시 선택하세요.')
            with guard_file(active),tempfile.TemporaryDirectory(prefix='read-',dir=self.state) as tmp:
                copy=Path(tmp)/active.name;shutil.copyfile(active,copy)
                result=self.runner({'operation':'read_document','path':str(copy)})
                if digest(active)!=doc['active_hash']:dm.fail('EXTERNAL_CHANGE','읽는 동안 파일이 변경됐습니다.')
        return result['document']

    def _assert_revision(self,doc,revision):
        from .service import digest
        if doc.get('mode')=='open':
            current=self.runner({'operation':'open_revision','target':doc['target']})['revision']
            if current!=revision:dm.fail('STALE_REVISION','문서가 변경됐습니다. 다시 읽으세요.')
        elif digest(doc['active'])!=doc['active_hash'] or digest(doc['source'])!=doc['source_hash']:
            dm.fail('EXTERNAL_CHANGE','파일이 변경됐습니다. 다시 선택하세요.')

    def _store_analysis(self,document_id,analysis):
        from .service import dumps
        row=self.db.execute('SELECT data FROM analyses WHERE doc=?',(document_id,)).fetchone()
        if row:
            previous=json.loads(row[0])
            if previous['revision']==analysis['revision']:analysis['targets']={**previous['targets'],**analysis['targets']}
        with self.db:self.db.execute('INSERT OR REPLACE INTO analyses VALUES (?,?)',(document_id,dumps(analysis)))

    def _get_analysis(self,document_id,revision):
        row=self.db.execute('SELECT data FROM analyses WHERE doc=?',(document_id,)).fetchone()
        if not row:dm.fail('ANALYSIS_MISSING','read_document로 문서를 먼저 읽으세요.')
        analysis=json.loads(row[0])
        if analysis['revision']!=revision:dm.fail('STALE_REVISION','이전 분석입니다. 문서를 다시 읽으세요.')
        return analysis

    def read_document(self,document_id,scope='all',cursor=0,limit=20,revision=None):
        if scope not in ('all','selection'):dm.fail('INVALID_SCOPE','scope은 all 또는 selection입니다.')
        if type(cursor)!=int or cursor<0 or type(limit)!=int or not 1<=limit<=100:dm.fail('INVALID_PAGE','cursor와 limit을 확인하세요.')
        with self.lock:
            doc=self._load(document_id)
            if revision is not None:
                analysis=self._get_analysis(document_id,revision);self._assert_revision(doc,revision)
            else:analysis=self._analysis(doc)
            if revision is not None and revision!=analysis['revision']:dm.fail('STALE_REVISION','페이지 조회 중 문서가 바뀌었습니다. 처음부터 다시 읽으세요.')
            if scope=='selection' and analysis.get('selection_stale'):dm.fail('STALE_SELECTION','선택한 뒤 문서가 바뀌었습니다. 범위를 선택하고 문서를 다시 선택하세요.')
            if scope=='selection' and not analysis.get('selection_target'):dm.fail('SELECTION_MISSING','선택 영역이 없습니다. 한글에서 선택하고 다시 문서를 선택하세요.')
            ranges=dm.expand(analysis,'all' if scope=='all' else analysis['selection_target'])
            blocks=[]
            for r in ranges:
                p=analysis['paragraphs'][r['paragraph']]
                base={'paragraph_id':p['id'],'paragraph_index':p['index'],'scope':p['scope'],'cell_path':p['cell_path'],'paragraph_style':p['style'].get('Name'),'mapped':p['mapped']}
                for part in p['parts']:
                    if part['end']<=r['start'] or part['start']>=r['end']:continue
                    if part['kind']=='text':
                        lo=max(r['start'],part['start']);hi=min(r['end'],part['end'])
                        text=part['text'][dm.char_index(part['text'],lo-part['start']):dm.char_index(part['text'],hi-part['start'])]
                        offset=lo
                        for i in range(0,len(text),2048):
                            fragment=text[i:i+2048];end=offset+dm.units(fragment)
                            key=dm.add_target(analysis,{'kind':'text','paragraph':p['index'],'start':offset,'end':end})
                            blocks.append(dict(base,kind='text',target_id=key,text=fragment,style=part['style']))
                            offset=end
                    elif part['kind']=='equation':
                        if not r['start']<=part['start']<part['end']<=r['end']:dm.fail('PARTIAL_CONTROL','수식 개체의 일부만 선택할 수 없습니다.')
                        for i in range(0,max(1,len(part['script'])),8000):
                            blocks.append(dict(base,kind='equation',target_id=part['id'],script=part['script'][i:i+8000],
                                               script_offset=i,script_length=len(part['script']),script_complete=len(part['script'])<=8000,
                                               font=part['font'],size_pt=part['size_pt']))
                    elif part.get('type')=='PICTURE':
                        blocks.append(dict(base,kind='image',target_id=part['id'],embedded=part['image']['embedded'],format=part['image']['format'],read_tool='read_image'))
                    else:blocks.append(dict(base,kind='control',target_id=part['id'],type=part['type']))
                if not p['parts']:blocks.append(dict(base,kind='paragraph',target_id=p['id'],text=''))
            if cursor>len(blocks):dm.fail('INVALID_PAGE','cursor가 문서 범위를 넘습니다.')
            page=[];used=0
            for b in blocks[cursor:cursor+limit]:
                size=len(dm.encode(b))
                if page and used+size>24000:break
                page.append(b);used+=size
            next_cursor=cursor+len(page)
            self._store_analysis(document_id,analysis)
            return {'ok':True,'document_id':document_id,'revision':analysis['revision'],'blocks':page,
                    'total_blocks':len(blocks),'next_cursor':next_cursor if next_cursor<len(blocks) else None,
                    'complete':next_cursor==len(blocks),'scope':scope,'all_target_id':'all' if scope=='all' else None,
                    'selection_target_id':analysis.get('selection_target'),'selection_stale':analysis.get('selection_stale',False),'tables':[{k:v for k,v in t.items() if k not in ('_anchor','xml_target_id')} for t in analysis['tables']],'excluded':analysis['excluded'],
                    'unmapped_paragraphs':[p['index'] for p in analysis['paragraphs'] if p['scope']!='excluded' and not p['mapped']],
                    'content_is_untrusted':True,'image_reading':{'tool':'read_image','scope':'embedded standalone raster pictures in body/tables; excludes groups/backgrounds/headers/textboxes'}}

    def find_targets(self,document_id,revision,selector):
        with self.lock:
            doc=self._load(document_id);analysis=self._get_analysis(document_id,revision)
            self._assert_revision(doc,revision)
            matches=dm.locate(analysis,selector);self._store_analysis(document_id,analysis)
            offset=selector.get('offset',0);limit=selector.get('limit',20)
            if type(offset)!=int or offset<0 or type(limit)!=int or not 1<=limit<=100:dm.fail('INVALID_PAGE','검색 offset과 limit을 확인하세요.')
            page=matches[offset:offset+limit];end=offset+len(page)
            return {'ok':True,'revision':revision,'matches':page,'ambiguous':len(matches)>1,'count':len(page),
                    'total_matches':len(matches),'next_cursor':end if end<len(matches) else None}

    def apply_edits(self,document_id,revision,request_id,edits,dry_run=False):
        from .service import guard_file,digest,dumps
        if not isinstance(request_id,str) or not 1<=len(request_id)<=128:dm.fail('INVALID_REQUEST','고유 request_id가 필요합니다.')
        with self.lock:
            doc=self._load(document_id)
            payload_hash=hashlib.sha256(dumps({'operation':'apply_edits','revision':revision,'edits':edits}).encode()).hexdigest()
            if not dry_run:
                replay=self._recover(doc,request_id,payload_hash)
                if replay:return replay
            analysis=self._get_analysis(document_id,revision)
            ops=dm.compile_edits(analysis,edits)
            if doc.get('mode')=='open':
                if self.db.execute("SELECT 1 FROM requests WHERE doc=? AND status='live_pending'",(document_id,)).fetchone():
                    dm.fail('LIVE_RECOVERY_REQUIRED','이 문서의 이전 작업 결과를 먼저 확인하세요.')
                root=self.state/'live-backups'/document_id;root.mkdir(parents=True,exist_ok=True)
                key=hashlib.sha256(request_id.encode()).hexdigest()
                backup=root/(key+'-edit.hwp');receipt=root/(key+'-edit.json')
                with tempfile.TemporaryDirectory(prefix='edit-stage-',dir=self.state) as tmp:
                    if dry_run:backup=Path(tmp)/'before.hwp';receipt=Path(tmp)/'receipt.json'
                    journal={'backup':str(backup),'receipt':str(receipt),'bookmark':None,'counts':{}}
                    if not dry_run:
                        with self.db:self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)',(document_id,request_id,payload_hash,'live_pending',dumps(journal)))
                    try:
                        result=self.runner({'operation':'open_edit','target':doc['target'],'revision':revision,'targets':analysis['targets'],
                                            'edits':edits,'dry_run':dry_run,'backup':str(backup),'receipt':str(receipt),
                                            'stage':str(Path(tmp)/'stage.hwp')})
                    except WriterError as e:
                        if not dry_run and e.code not in ('HANCOM_TIMEOUT','BACKEND_FAILED','LIVE_RECOVERY_REQUIRED'):
                            with self.db:self.db.execute('DELETE FROM requests WHERE doc=? AND id=?',(document_id,request_id))
                        raise
                result.update(document_id=document_id,request_id=request_id,dry_run=dry_run)
                if not dry_run:
                    with self.db:self.db.execute('UPDATE requests SET status=?,data=? WHERE doc=? AND id=?',('done',dumps({'result':result}),document_id,request_id))
                return result
            for rid,ph in self.db.execute("SELECT id,hash FROM requests WHERE doc=? AND status='pending'",(document_id,)).fetchall():
                self._recover(doc,rid,ph)
            source,active,output=map(Path,(doc['source'],doc['active'],doc['output']))
            if digest(source)!=doc['source_hash'] or digest(active)!=doc['active_hash']:dm.fail('EXTERNAL_CHANGE','파일이 변경됐습니다. 다시 선택하세요.')
            if active==source and output.exists():dm.fail('OUTPUT_COLLISION','수정본 이름이 이미 사용 중입니다. 다시 선택하세요.')
            with guard_file(active) as release,tempfile.TemporaryDirectory(prefix='.hangul-edit-',dir=output.parent) as tmp:
                stage=Path(tmp)/output.name;shutil.copyfile(active,stage)
                result=self.runner({'operation':'apply_edits','path':str(stage),'revision':revision,'targets':analysis['targets'],'edits':edits})
                if digest(active)!=doc['active_hash'] or digest(source)!=doc['source_hash']:dm.fail('EXTERNAL_CHANGE','시험 중 파일이 변경됐습니다.')
                if dry_run:
                    return dict(result,ok=True,dry_run=True,saved=False,output=None,edits=edits,document_id=document_id,request_id=request_id)
                result.update(ok=True,mode='file',saved=True,output=str(output),document_id=document_id,request_id=request_id,dry_run=False)
                expected=digest(stage);journal={'output':str(output),'expected_hash':expected,'result':result}
                with self.db:self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)',(document_id,request_id,payload_hash,'pending',dumps(journal)))
                try:
                    release()
                    if digest(active)!=doc['active_hash'] or digest(source)!=doc['source_hash']:dm.fail('EXTERNAL_CHANGE','저장 직전 파일이 변경됐습니다.')
                    if active==source:
                        if output.exists():dm.fail('OUTPUT_COLLISION','저장 예정 파일이 생겼습니다.')
                        os.rename(stage,output)
                    else:os.replace(stage,output)
                except Exception:
                    with self.db:self.db.execute('DELETE FROM requests WHERE doc=? AND id=?',(document_id,request_id))
                    raise
                doc['active']=str(output);doc['active_hash']=expected
                with self.db:
                    self._put(doc)
                    self.db.execute('UPDATE requests SET status=?,data=? WHERE doc=? AND id=?',('done',dumps({'result':result}),document_id,request_id))
                return result

    def read_image(self,document_id,revision,target_id,crop=None,max_edge=2048):
        from .images import validate_options
        from .service import guard_file,digest
        validate_options(crop,max_edge)
        with self.lock:
            doc=self._load(document_id);analysis=self._get_analysis(document_id,revision)
            target=analysis['targets'].get(target_id)
            if not target or target.get('kind')!='control':dm.fail('NOT_AN_IMAGE','read_document에서 읽은 그림 target_id를 지정하세요.')
            self._assert_revision(doc,revision)
            job={'revision':revision,'target_id':target_id,'crop':crop,'max_edge':max_edge}
            if doc.get('mode')=='open':
                result=self.runner(dict(job,operation='open_image',target=doc['target']))
            else:
                active=Path(doc['active'])
                with guard_file(active),tempfile.TemporaryDirectory(prefix='image-',dir=self.state) as tmp:
                    copy=Path(tmp)/active.name;shutil.copyfile(active,copy)
                    result=self.runner(dict(job,operation='read_image',path=str(copy)))
                    self._assert_revision(doc,revision)
            result['document_id']=document_id
            return result
