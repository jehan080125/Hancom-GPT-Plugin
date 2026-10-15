"""Structured, revision-bound document model. Document text is untrusted data."""
import copy
import hashlib
import json
import re
from .errors import WriterError
from . import xmlcheck
from .latex import convert, validate_script

EXCLUDED = {'HEADER','FOOTER','FOOTNOTE','ENDNOTE','TEXTBOX','DRAWTEXT','MASTERPAGE'}
LANGS = ('Hangul','Latin','Hanja','Japanese','Other','Symbol','User')

def fail(code, message):
    raise WriterError(code, message)

def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',',':'))

def digest(obj):
    return hashlib.sha256(encode(obj).encode()).hexdigest()

def revision(xml):
    root = xmlcheck.parse(xml)
    for parent in root.iter():
        for child in list(parent):
            if xmlcheck.tag(child) in ('DOCSUMMARY','DOCSETTING'): parent.remove(child)
    return digest(xmlcheck.ET.tostring(root,encoding='unicode'))

def uid(rev, path):
    return hashlib.sha256((rev+'|'+path).encode()).hexdigest()[:32]

def units(text):
    return len(text.encode('utf-16-le'))//2

def canonical(node, ignore=()):
    return [xmlcheck.tag(node),{k:v for k,v in node.attrib.items() if k not in ignore},
            node.text or '',[canonical(c,ignore) for c in node]]

def model(xml):
    root=xmlcheck.parse(xml); rev=revision(xml)
    fonts={f.get('Lang'):{n.get('Id'):n.get('Name') for n in f if xmlcheck.tag(n)=='FONT'} for f in root.iter() if xmlcheck.tag(f)=='FONTFACE'}
    charstyles={}
    for s in root.iter():
        if xmlcheck.tag(s)!='CHARSHAPE': continue
        others=copy.deepcopy(s);others.attrib.pop('Id',None);others.attrib.pop('Height',None)
        names={}
        for c in list(others):
            if xmlcheck.tag(c)=='FONTID':
                names={lang:fonts.get(lang,{}).get(c.get(lang),'?'+str(c.get(lang))) for lang in LANGS}
                others.remove(c)
        charstyles[s.get('Id')]={'size_pt':int(s.get('Height','1000'))/100,'fonts':names,'other':canonical(others)}
    parastyles={s.get('Id'):canonical(s,('Id',)) for s in root.iter() if xmlcheck.tag(s)=='PARASHAPE'}
    styles={s.get('Id'):s.attrib for s in root.iter() if xmlcheck.tag(s)=='STYLE'}
    paragraphs=[];tables=[];targets={};excluded={}
    def walk(node,path,context,unsupported=False):
        tag=xmlcheck.tag(node);unsupported=unsupported or tag in EXCLUDED
        if tag in EXCLUDED: excluded[tag]=excluded.get(tag,0)+1
        if tag=='TABLE':
            number=0 if unsupported else len(tables)+1
            table={'number':number,'xml_target_id':uid(rev,path),'path':context+ [{'table':number}],'rows':int(node.get('RowCount','0')),'columns':int(node.get('ColCount','0'))}
            if not unsupported:tables.append(table)
            context=table['path']
        if tag=='CELL':
            context=context+[{'row':int(node.get('RowAddr','0'))+1,'column':int(node.get('ColAddr','0'))+1,
                              'row_span':int(node.get('RowSpan','1')),'column_span':int(node.get('ColSpan','1'))}]
        if tag=='P':
            p={'id':uid(rev,path),'path':path,'index':len(paragraphs),'scope':'excluded' if unsupported else ('table' if context else 'body'),
               'cell_path':copy.deepcopy(context),'parts':[],'text':'','length':0,
               'paragraph_shape':parastyles.get(node.get('ParaShape')),'style':dict(styles.get(node.get('Style'),{})),
               'attributes':{k:v for k,v in node.attrib.items() if k not in ('InstId','ParaShape','Style')}}
            paragraphs.append(p)
            position=0
            def inline(n,style,path2):
                nonlocal position
                kind=xmlcheck.tag(n)
                if kind=='TEXT': style=charstyles.get(n.get('CharShape'),{})
                if kind=='CHAR':
                    text=n.text or ''
                    if text:
                        part={'kind':'text','id':uid(rev,path2),'start':position,'end':position+units(text),'text':text,'style':copy.deepcopy(style)}
                        p['parts'].append(part);p['text']+=text;position=part['end']
                    return
                if kind=='EQUATION':
                    script=''.join(x.text or '' for x in n.iter() if xmlcheck.tag(x)=='SCRIPT')
                    part={'kind':'equation','id':uid(rev,path2),'start':position,'end':position+8,'script':script,
                          'size_pt':int(n.get('BaseUnit','1000'))/100,'font':n.get('Font','HancomEQN'),
                          'attributes':{k:v for k,v in n.attrib.items() if k not in ('BaseUnit','BaseLine','Font')}}
                    p['parts'].append(part);position+=8;return
                if kind in ('P','PARALIST'): return
                if kind not in ('TEXT',):
                    # HWP extended/inline controls occupy eight UTF-16 code units.
                    if kind in ('LINEBREAK','HYPHEN','NBSPACE','FWSPACE'):
                        value={'LINEBREAK':'\n','HYPHEN':'-','NBSPACE':'\u00a0','FWSPACE':'\u2007'}[kind]
                        p['parts'].append({'kind':'control','id':uid(rev,path2),'start':position,'end':position+1,'type':kind,'value':value})
                        position+=1;return
                    if kind=='TAB':
                        p['parts'].append({'kind':'control','id':uid(rev,path2),'start':position,'end':position+8,'type':kind,'value':'\t'})
                        position+=8;return
                    if kind not in ('TEXT',):
                        p['parts'].append({'kind':'control','id':uid(rev,path2),'start':position,'end':position+8,'type':kind,
                                          'value':None if kind=='TABLE' else canonical(n,('InstId',))})
                        position+=8;return
                for i,c in enumerate(n): inline(c,style,path2+'/'+str(i))
            for i,c in enumerate(node): inline(c,{},path+'/'+str(i))
            p['length']=position
            if not p['parts']:
                first=next((c for c in node if xmlcheck.tag(c)=='TEXT'),None)
                p['empty_style']=copy.deepcopy(charstyles.get(first.get('CharShape'),{})) if first is not None else {}
        for i,c in enumerate(node): walk(c,path+'/'+str(i),context,unsupported)
    body=next((n for n in root if xmlcheck.tag(n)=='BODY'),None)
    if body is None: fail('EXPORT_FAILED','본문 구조가 없습니다.')
    walk(body,'body',[])
    result={'revision':rev,'paragraphs':paragraphs,'tables':tables,'excluded':excluded,
            'table_structure':xmlcheck.snapshot(xml)['tables'],'bookmarks':xmlcheck.bookmarks(xml),'targets':targets}
    for p in paragraphs:
        if p['scope']=='excluded': continue
        targets[p['id']]={'kind':'range','paragraph':p['index'],'start':0,'end':p['length']}
        for part in p['parts']:
            targets[part['id']]={'kind':part['kind'],'paragraph':p['index'],'start':part['start'],'end':part['end']}
    targets['all']={'kind':'group','members':[p['id'] for p in paragraphs if p['scope']!='excluded']}
    return result

def public_paragraph(p):
    out={k:copy.deepcopy(v) for k,v in p.items() if k not in ('native','mapped','path')}
    out['target_id']=out.pop('id')
    for part in out['parts']:
        part['target_id']=part.pop('id')
    return out

def expand(doc,target):
    if target not in doc['targets']: fail('TARGET_MISSING','분석한 문서에 없는 대상입니다. 다시 읽으세요.')
    entry=doc['targets'][target]
    if entry['kind']=='group':
        return [r for m in entry['members'] for r in expand(doc,m)]
    return [dict(entry)]

def add_target(doc,entry,key=None):
    key=key or uid(doc['revision'],encode(entry))
    doc['targets'][key]=entry
    return key

def locate(doc,selector):
    if not isinstance(selector,dict): fail('INVALID_SELECTOR','selector 객체가 필요합니다.')
    kind=selector.get('type','text');hits=[]
    if kind=='all': return [{'target_id':'all','kind':'group'}]
    if kind=='selection':
        if not doc.get('selection_target'): fail('SELECTION_MISSING','한글에서 범위를 선택한 뒤 문서를 다시 선택하세요.')
        return [{'target_id':doc['selection_target'],'kind':'group'}]
    for p in doc['paragraphs']:
        if p['scope']=='excluded': continue
        if kind=='table':
            found=False
            for ti,cell in zip(p['cell_path'][::2],p['cell_path'][1::2]):
                if ti['table']!=selector.get('table'): continue
                row,col=selector.get('row'),selector.get('column')
                if row is not None and not cell['row']<=row<cell['row']+cell['row_span']:continue
                if col is not None and not cell['column']<=col<cell['column']+cell['column_span']:continue
                found=True
            if found: hits.append({'target_id':p['id'],'kind':'range','paragraph':p['index'],'text':p['text'],'cell_path':p['cell_path']})
        elif kind=='paragraph':
            if p['id']==selector.get('target_id') or p['index']==selector.get('index'):hits.append({'target_id':p['id'],'kind':'range','text':p['text']})
        elif kind in ('text','equation'):
            needle=selector.get('text') if kind=='text' else selector.get('script')
            if kind=='text' and (not isinstance(needle,str) or not needle):fail('INVALID_SELECTOR','검색할 text가 필요합니다.')
            candidates=[]
            for part in p['parts']:
                if part['kind']!=kind:continue
                if kind=='text' and candidates and candidates[-1]['end']==part['start']:
                    candidates[-1]['text']+=part['text'];candidates[-1]['end']=part['end']
                else:candidates.append(copy.deepcopy(part))
            for part in candidates:
                if kind=='equation':
                    if needle is None or needle in part['script']:
                        hits.append({'target_id':part['id'],'kind':kind,'script':part['script'],'paragraph':p['index'],'cell_path':p['cell_path']})
                else:
                    for match in re.finditer(re.escape(needle),part['text']):
                        start=part['start']+units(part['text'][:match.start()]);end=start+units(needle)
                        entry={'kind':'text','paragraph':p['index'],'start':start,'end':end}
                        hits.append({'target_id':add_target(doc,entry),'kind':'text','text':needle,'paragraph':p['index'],
                                     'context':part['text'][max(0,match.start()-120):match.end()+120],'context_is_excerpt':True,'cell_path':p['cell_path']})
        elif kind=='heading':
            if p['scope']=='body' and p['text']==selector.get('text'):
                # Automatic boundary needs an actual heading style; otherwise ask.
                def level(item):
                    attrs=(item.get('paragraph_shape') or [None,{}])[1]
                    if attrs.get('HeadingType') not in (None,'None'):
                        return int(attrs.get('Level','0'))
                    name=item['style'].get('Name','')
                    if re.search(r'제목|개요|heading',name,re.I):
                        number=re.search(r'([0-9]+)',name)
                        return int(number.group(1)) if number else 0
                    return None
                heading_level=level(p)
                if heading_level is None and selector.get('end_heading') is None:
                    fail('AMBIGUOUS_BOUNDARY','제목 스타일이 명확하지 않습니다. 끝 제목이나 대상 문단을 지정하세요.')
                members=[];found_end=False
                for q in doc['paragraphs'][p['index']+1:]:
                    if q['scope']=='body':
                        qlevel=level(q)
                        if (selector.get('end_heading') is not None and q['text']==selector['end_heading']) or (
                            selector.get('end_heading') is None and qlevel is not None and qlevel<=heading_level):
                            found_end=True;break
                    if q['scope']!='excluded':members.append(q['id'])
                if selector.get('end_heading') is not None and not found_end:
                    fail('AMBIGUOUS_BOUNDARY','끝 제목을 찾지 못했습니다.')
                if not members:fail('TARGET_MISSING','제목 아래에 대상 문단이 없습니다.')
                hits.append({'target_id':add_target(doc,{'kind':'group','members':members}),'kind':'group','heading':p['text']})
        elif kind not in ('bookmark',): fail('INVALID_SELECTOR','지원하지 않는 selector type입니다.')
    if kind=='bookmark':
        key=doc.get('bookmark_targets',{}).get(selector.get('name'))
        if key: hits=[{'target_id':key,'kind':'range','name':selector.get('name')}]
    occurrence=selector.get('occurrence')
    if occurrence is not None:
        if type(occurrence)!=int or occurrence<1:fail('INVALID_SELECTOR','occurrence는 1부터 시작합니다.')
        hits=hits[occurrence-1:occurrence]
    return hits

def compile_edits(doc,edits):
    if not isinstance(edits,list) or not edits or len(edits)>1000:fail('INVALID_EDIT','1~1000개 변경이 필요합니다.')
    compiled=[]
    for edit in edits:
        if not isinstance(edit,dict):fail('INVALID_EDIT','변경 항목은 객체여야 합니다.')
        kind=edit.get('type')
        if kind not in ('replace_text','replace_equation','set_format'):fail('INVALID_EDIT','허용되지 않은 변경 종류입니다.')
        if edit.get('uncertain'):fail('UNCERTAIN_CONTENT','불명확한 수정 내용을 먼저 확인하세요.')
        target=edit.get('target_id')
        ranges=expand(doc,target)
        if kind!='set_format' and len(ranges)!=1:fail('INVALID_EDIT','내용 교체는 한 글자 구간 또는 한 수식씩 지정하세요.')
        for r in ranges:
            p=doc['paragraphs'][r['paragraph']]
            if r['kind']=='control':fail('UNSUPPORTED_LOCATION','이 개체는 서식 변경 대상이 아닙니다.')
            if not p.get('mapped',False):fail('UNMAPPED_LOCATION','실제 한글 위치가 검증되지 않은 영역입니다.')
            op=dict(r,type=kind)
            if kind=='replace_text':
                replacement=edit.get('text');old=edit.get('expected_text')
                if not isinstance(replacement,str) or any(c in replacement for c in '\r\n\x00\t') or not isinstance(old,str):
                    fail('INVALID_EDIT','expected_text와 줄바꿈 없는 text가 필요합니다.')
                pieces=[a for a in p['parts'] if a['end']>r['start'] and a['start']<r['end']]
                if not pieces or any(a['kind']!='text' for a in pieces) or pieces[0]['start']>r['start'] or pieces[-1]['end']<r['end']:
                    fail('INVALID_EDIT','개체를 가로지르는 글자 교체는 지원하지 않습니다.')
                actual=''
                for part in pieces:
                    lo=max(r['start'],part['start'])-part['start'];hi=min(r['end'],part['end'])-part['start']
                    actual+=part['text'][char_index(part['text'],lo):char_index(part['text'],hi)]
                if actual!=old:fail('STALE_TARGET','교체 전 원문이 다릅니다.')
                part=pieces[0]
                op.update(text=replacement,expected_text=old,style=part['style'])
            elif kind=='replace_equation':
                part=next((a for a in p['parts'] if a['kind']=='equation' and a['start']==r['start'] and a['end']==r['end']),None)
                if part is None or part['script']!=edit.get('expected_script'):fail('STALE_TARGET','교체 전 수식이 다릅니다.')
                fmt=edit.get('format','latex')
                if fmt not in ('latex','hwp'):fail('INVALID_EDIT','format은 latex 또는 hwp입니다.')
                op.update(script=convert(edit.get('script')) if fmt=='latex' else validate_script(edit.get('script')),expected_script=part['script'])
            else:
                props=edit.get('properties')
                allowed={'font_name','size_pt','equation_font','equation_size_pt'}
                if not isinstance(props,dict) or not props or set(props)-allowed:fail('INVALID_FORMAT','글꼴과 기본 크기만 지정할 수 있습니다.')
                for key,value in props.items():
                    if key.endswith('_pt'):
                        if isinstance(value,bool) or not isinstance(value,(int,float)) or not 0.1<=value<=4096 or round(value*100)!=value*100:
                            fail('INVALID_FORMAT','크기는 0.1~4096pt, 소수점 두 자리 이내여야 합니다.')
                    elif not isinstance(value,str) or not value.strip():fail('INVALID_FORMAT','유효한 글꼴 이름이 필요합니다.')
                for part in p['parts']:
                    if part['kind']=='equation' and max(r['start'],part['start'])<min(r['end'],part['end']) and not r['start']<=part['start']<part['end']<=r['end']:
                        fail('PARTIAL_CONTROL','수식 개체의 일부만 서식 변경할 수 없습니다.')
                op['properties']=props
            compiled.append(op)
    grouped={}
    for op in compiled:grouped.setdefault(op['paragraph'],[]).append(op)
    for group in grouped.values():
      for i,a in enumerate(group):
        for b in group[i+1:]:
            if a['paragraph']!=b['paragraph'] or max(a['start'],b['start'])>=min(a['end'],b['end']):continue
            if (a['type']=='set_format')==(b['type']=='set_format'):fail('OVERLAPPING_EDITS','겹치는 내용 변경 또는 서식 변경을 하나로 합치세요.')
            style=a if a['type']=='set_format' else b;content=b if a['type']=='set_format' else a
            if not style['start']<=content['start']<content['end']<=style['end']:fail('OVERLAPPING_EDITS','서식 범위가 내용 교체 구간의 일부와 겹칩니다.')
    if sum(len(o.get('text',''))+len(o.get('script','')) for o in compiled)>200000:fail('INVALID_EDIT','한 번의 내용 변경은 200,000자 이내여야 합니다.')
    return compiled

def char_index(text,offset):
    count=0
    for i,c in enumerate(text):
        if count==offset:return i
        count+=units(c)
    if count==offset:return len(text)
    fail('INVALID_EDIT','문자 중간의 위치는 선택할 수 없습니다.')

def atoms(p):
    result=[]
    if not p['parts']:
        return [{'kind':'empty','style':copy.deepcopy(p.get('empty_style',{})),'start':0,'end':0}]
    for part in p['parts']:
        if part['kind']=='text':
            start=part['start']
            for c in part['text']:
                result.append({'kind':'text','text':c,'style':part['style'],'start':start,'end':start+units(c)})
                start+=units(c)
        else:result.append({k:copy.deepcopy(v) for k,v in part.items() if k!='id'})
    return result

def shifted(position,ops):
    return position+sum(units(o['text'])-(o['end']-o['start']) for o in ops if o['type']=='replace_text' and o['end']<=position)

def expected_atoms(doc,ops):
    result=[atoms(p) for p in doc['paragraphs']]
    for op in sorted((o for o in ops if o['type']!='set_format'),key=lambda o:(o['paragraph'],o['start']),reverse=True):
        aa=result[op['paragraph']]
        indexes=[i for i,a in enumerate(aa) if op['start']<=a['start'] and a['end']<=op['end']]
        if op['type']=='replace_text':
            new=[{'kind':'text','text':c,'style':op['style'],'start':op['start'],'end':op['end']} for c in op['text']]
            aa[indexes[0]:indexes[-1]+1]=new
            if not aa:aa.append({'kind':'empty','style':op['style'],'start':0,'end':0})
        else:aa[indexes[0]]['script']=op['script']
    # Apply formatting using original atom coordinates, before stripping them.
    for op in (o for o in ops if o['type']=='set_format'):
        style_cache={}
        for a in result[op['paragraph']]:
            if a['kind']!='empty' and not op['start']<=a['start']<a['end']<=op['end']:continue
            props=op['properties']
            if a['kind'] in ('text','empty'):
                key=id(a['style'])
                if key not in style_cache:
                    changed=dict(a['style'])
                    if 'size_pt' in props:changed['size_pt']=props['size_pt']
                    if 'font_name' in props:changed['fonts']={k:props['font_name'] for k in LANGS}
                    style_cache[key]=changed
                a['style']=style_cache[key]
            elif a['kind']=='equation':
                if 'equation_size_pt' in props:a['size_pt']=props['equation_size_pt']
                if 'equation_font' in props:a['font']=props['equation_font']
    return [[{k:v for k,v in a.items() if k not in ('start','end')} for a in aa] for aa in result]

def verify_edit(before,after,ops):
    if before['table_structure']!=after['table_structure']:fail('VERIFY_FAILED','기존 표 구조가 달라졌습니다.')
    if before['bookmarks']!=after['bookmarks']:fail('VERIFY_FAILED','책갈피 구성이 달라졌습니다.')
    if len(before['paragraphs'])!=len(after['paragraphs']):fail('VERIFY_FAILED','문단 개수가 달라졌습니다.')
    for a,b in zip(before['paragraphs'],after['paragraphs']):
        for key in ('scope','cell_path','paragraph_shape','style','attributes'):
            if a[key]!=b[key]:fail('VERIFY_FAILED','요청 밖 문단 서식 또는 위치가 바뀌었습니다: '+key)
    if expected_atoms(before,ops)!=expected_atoms(after,[]):fail('VERIFY_FAILED','요청 밖 내용·수식·글자 서식이 바뀌었거나 요청한 변경이 적용되지 않았습니다.')
