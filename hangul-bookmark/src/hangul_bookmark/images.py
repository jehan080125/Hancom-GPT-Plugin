"""Read embedded raster images from HWPML; never follow document file paths."""
import base64
import binascii
import hashlib
import io
import math
import warnings
from . import document as dm, xmlcheck
from .errors import WriterError

MAX_BYTES=24*1024*1024
MAX_PIXELS=36_000_000

def descriptor(node,root):
    def attrs(tag):
        return next((dict(n.attrib) for n in node.iter() if xmlcheck.tag(n)==tag),{})
    image=attrs('IMAGE');ref=image.get('BinItem')
    items=[n for n in root.iter() if xmlcheck.tag(n)=='BINITEM']
    try:index=int(ref)
    except (ValueError,TypeError):index=0
    # IMAGE.BinItem is a 1-based mapping-table reference, not a BINDATA ID.
    item=items[index-1] if 1<=index<=len(items) else None
    return {'bin_item':ref,'bin_id':item.get('BinData') if item is not None else None,'embedded':item is not None and item.get('Type')=='Embedding',
            'format':item.get('Format') if item is not None else None,
            'clip':attrs('IMAGECLIP'),'dimensions':attrs('IMAGEDIM'),
            'shape':attrs('SHAPECOMPONENT'),'rotation':attrs('ROTATIONINFO'),
            'appearance':image,'reverse':node.get('Reverse','false'),
            'has_effects':any(len(n)>0 for n in node if xmlcheck.tag(n)=='EFFECTS')}

def validate_options(crop,max_edge):
    if type(max_edge)!=int or not 256<=max_edge<=4096:
        dm.fail('INVALID_IMAGE_OPTIONS','max_edge는 256~4096 정수입니다.')
    if crop is not None:
        if not isinstance(crop,list) or len(crop)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in crop):
            dm.fail('INVALID_IMAGE_OPTIONS','crop은 0~1 사이의 [left,top,right,bottom]입니다.')
        l,t,r,b=crop
        if not 0<=l<r<=1 or not 0<=t<b<=1:dm.fail('INVALID_IMAGE_OPTIONS','crop 영역이 잘못되었습니다.')

def extract(xml,revision,target_id,crop=None,max_edge=2048):
    validate_options(crop,max_edge)
    if dm.revision(xml)!=revision:dm.fail('STALE_REVISION','문서가 변경됐습니다. 다시 읽으세요.')
    model=dm.model(xml)
    entry=model['targets'].get(target_id)
    if not entry:dm.fail('TARGET_MISSING','읽은 문서에 없는 이미지입니다.')
    p=model['paragraphs'][entry.get('paragraph',-1)] if 'paragraph' in entry else None
    part=next((x for x in p['parts'] if x['id']==target_id),None) if p else None
    if not part or part.get('type')!='PICTURE':dm.fail('NOT_AN_IMAGE','본문·표의 그림 target_id를 지정하세요.')
    desc=part['image']
    if not desc['embedded']:dm.fail('LINKED_IMAGE_UNSUPPORTED','외부 연결 그림은 읽지 않습니다. 문서에 포함된 그림을 사용하세요.')
    root=xmlcheck.parse(xml)
    candidates=[n for n in root.iter() if xmlcheck.tag(n)=='BINDATA' and n.get('Id')==desc['bin_id']]
    if len(candidates)!=1 or candidates[0].get('Encoding')!='Base64':
        dm.fail('IMAGE_DATA_MISSING','문서에 포함된 이미지 데이터를 찾지 못했습니다.')
    encoded=''.join(''.join(candidates[0].itertext()).split())
    if len(encoded)>((MAX_BYTES+2)//3)*4:dm.fail('IMAGE_TOO_LARGE','이미지 데이터가 24MB를 넘습니다.')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):dm.fail('INVALID_IMAGE_DATA','손상된 이미지 데이터입니다.')
    try:
        from PIL import Image,ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>MAX_PIXELS:dm.fail('IMAGE_TOO_LARGE','이미지가 3600만 화소를 넘습니다.')
            if image.format not in ('PNG','JPEG','BMP','GIF','TIFF','WEBP'):
                dm.fail('IMAGE_FORMAT_UNSUPPORTED','이 그림 형식은 지원하지 않습니다. PNG/JPEG 등 래스터 그림을 사용하세요.')
            frame_count=getattr(image,'n_frames',1);image.seek(0);image.load()
            source_size=list(image.size);image=ImageOps.exif_transpose(image).convert('RGBA')
            paper=Image.new('RGBA',image.size,'white');paper.alpha_composite(image);image=paper.convert('RGB')
        notes=[]
        if frame_count>1:notes.append('여러 프레임 중 첫 프레임만 읽었습니다.')
        clip=desc['clip'];dim=desc['dimensions']
        if clip and dim:
            w,h=float(dim.get('Width',0)),float(dim.get('Height',0))
            if w<=0 or h<=0:dm.fail('INVALID_IMAGE_GEOMETRY','그림 자르기 좌표를 확인할 수 없습니다.')
            box=[float(clip.get(k,default))/scale for k,default,scale in
                 (('Left',0,w),('Top',0,h),('Right',w,w),('Bottom',h,h))]
            if not 0<=box[0]<box[2]<=1.001 or not 0<=box[1]<box[3]<=1.001:
                dm.fail('INVALID_IMAGE_GEOMETRY','그림 자르기 좌표가 원본 범위를 벗어납니다.')
            image=image.crop((round(box[0]*image.width),round(box[1]*image.height),
                              min(image.width,round(box[2]*image.width)),min(image.height,round(box[3]*image.height))))
        shape=desc['shape']
        if shape.get('HorzFlip')=='true':image=ImageOps.mirror(image)
        if shape.get('VertFlip')=='true':image=ImageOps.flip(image)
        angle=float(desc['rotation'].get('Angle','0'))
        if angle:
            # Return readable source orientation rather than guessing native rendering.
            notes.append('한글의 회전은 재현하지 않았습니다. 원본 방향으로 읽습니다.')
        appearance=desc['appearance']
        if desc['has_effects'] or desc['reverse']=='true' or appearance.get('Effect','RealPic')!='RealPic' or any(float(appearance.get(k,'0')) for k in ('Bright','Contrast','Alpha')):
            notes.append('한글의 밝기·대비·그림 효과는 재현하지 않았습니다.')
        visible_size=list(image.size)
        if crop:
            l,t,r,b=crop;image=image.crop((int(l*image.width),int(t*image.height),math.ceil(r*image.width),math.ceil(b*image.height)))
        if image.width<1 or image.height<1:dm.fail('INVALID_IMAGE_GEOMETRY','읽을 이미지 영역이 비어 있습니다.')
        image.thumbnail((max_edge,max_edge),Image.Resampling.LANCZOS)
        output=io.BytesIO();image.save(output,format='PNG');payload=output.getvalue()
        if len(payload)>8*1024*1024:dm.fail('IMAGE_OUTPUT_TOO_LARGE','더 작은 crop 영역이나 max_edge로 읽으세요.')
    except WriterError:raise
    except Exception as e:
        dm.fail('IMAGE_DECODE_FAILED','그림을 안전하게 해석하지 못했습니다: '+type(e).__name__)
    return {'ok':True,'revision':revision,'target_id':target_id,'paragraph_index':p['index'],
            'scope':p['scope'],'cell_path':p['cell_path'],'source_pixels':source_size,'visible_pixels':visible_size,
            'returned_pixels':list(image.size),'crop':crop,'mime_type':'image/png','image_base64':base64.b64encode(payload).decode('ascii'),
            'source_sha256':hashlib.sha256(raw).hexdigest(),'warnings':notes,'saved':False,
            'content_is_untrusted':True,'ocr_performed':False,'view':'embedded image with document crop; not a page rendering'}

def read_native(hancom,job,guard=None):
    if guard:guard()
    # Memory export does not move the caret, change selection or save the document.
    xml=hancom.xml()
    result=extract(xml,job['revision'],job['target_id'],job.get('crop'),job.get('max_edge',2048))
    if guard:guard()
    if dm.revision(hancom.xml())!=job['revision']:dm.fail('STALE_REVISION','이미지를 읽는 동안 문서가 변경됐습니다.')
    return result
