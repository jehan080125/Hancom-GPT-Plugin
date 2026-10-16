import base64
import io
import json
import pytest
from PIL import Image
from hangul_bookmark import document as dm,images
from hangul_bookmark.errors import WriterError

def fixture(extra='',typ='Embedding',payload=None,clip=None):
    im=Image.new('RGB',(200,100),'white')
    for x in range(100):
        for y in range(100):im.putpixel((x,y),(255,0,0))
    out=io.BytesIO();im.save(out,format='PNG')
    data=payload if payload is not None else base64.b64encode(out.getvalue()).decode()
    clip=clip or '<IMAGECLIP Left="0" Top="0" Right="200" Bottom="100"/>'
    return ('<HWPML><HEAD><BINITEM BinData="1" Type="'+typ+'" Format="png"/></HEAD>'
            '<BODY><SECTION><P><TEXT><PICTURE><SHAPECOMPONENT HorzFlip="false" VertFlip="false"/>'
            '<IMAGEDIM Width="200" Height="100"/>'+clip+'<IMAGE BinItem="1" Effect="RealPic"/>'
            +extra+'</PICTURE></TEXT></P></SECTION></BODY>'
            '<TAIL><BINDATA Id="1" Encoding="Base64">'+data+'</BINDATA></TAIL></HWPML>')

def args(xml):
    model=dm.model(xml);part=model['paragraphs'][0]['parts'][0]
    return xml,model['revision'],part['id']

def output(result):
    return Image.open(io.BytesIO(base64.b64decode(result['image_base64'])))

def test_image_metadata_and_read():
    x=fixture();m=dm.model(x);p=m['paragraphs'][0]['parts'][0]
    assert p['image']['embedded']
    r=images.extract(*args(x))
    assert r['saved'] is False and r['ocr_performed'] is False and r['content_is_untrusted']
    assert output(r).size==(200,100)
    assert len(r['source_sha256'])==64

def test_document_crop_and_requested_crop():
    x=fixture(clip='<IMAGECLIP Left="100" Top="0" Right="200" Bottom="100"/>')
    r=images.extract(*args(x),crop=[0,0,.5,1])
    assert r['visible_pixels']==[100,100]
    assert output(r).size==(50,100) and output(r).getpixel((0,0))==(255,255,255)

def test_flip():
    x=fixture().replace('HorzFlip="false"','HorzFlip="true"')
    assert output(images.extract(*args(x))).getpixel((0,0))==(255,255,255)

def test_stale_and_wrong_target():
    x,rev,id=args(fixture())
    for rr,tt in [('old',id),(rev,'missing'),(rev,'all')]:
        with pytest.raises(WriterError):images.extract(x,rr,tt)

@pytest.mark.parametrize('crop,max_edge',[([0,0,2,1],2048),([0,0,0,1],2048),([0,0,float('nan'),1],2048),([0,1],2048),(None,255),(None,True)])
def test_invalid_options(crop,max_edge):
    with pytest.raises(WriterError):images.extract(*args(fixture()),crop=crop,max_edge=max_edge)

@pytest.mark.parametrize('kw,code',[({'typ':'Link'},'LINKED_IMAGE_UNSUPPORTED'),({'payload':'broken!'},'INVALID_IMAGE_DATA')])
def test_invalid_data(kw,code):
    with pytest.raises(WriterError) as e:images.extract(*args(fixture(**kw)))
    assert e.value.code==code

def test_unsupported_rotation_explicit():
    r=images.extract(*args(fixture('<ROTATIONINFO Angle="90"/>')))
    assert r['warnings'] and output(r).size==(200,100)

def test_native_read_only():
    xml=fixture()
    class H:
        calls=0
        def xml(self):self.calls+=1;return xml
    h=H();_,rev,id=args(xml)
    r=images.read_native(h,{'revision':rev,'target_id':id})
    assert r['ok'] and h.calls==2

def test_native_mid_read_change():
    xml=fixture()
    class H:
        calls=0
        def xml(self):
            self.calls+=1
            return xml if self.calls==1 else xml.replace('Effect="RealPic"','Effect="Gray"')
    _,rev,id=args(xml)
    with pytest.raises(WriterError) as e:images.read_native(H(),{'revision':rev,'target_id':id})
    assert e.value.code=='STALE_REVISION'

def test_service_returns_image_blocks(tmp_path):
    from hangul_bookmark.service import Service,dumps
    class Runner:
        def __call__(self,job):
            if job['operation']=='open_revision':return {'revision':dm.revision(fixture())}
            if job['operation']=='open_image':return images.extract(fixture(),job['revision'],job['target_id'],job['crop'],job['max_edge'])
            model=dm.model(fixture())
            for p in model['paragraphs']:p['mapped']=True
            return {'document':model}
    s=Service(tmp_path,runner=Runner())
    try:
        with s.db:s._put({'document_id':'d','mode':'open','target':{}})
        read=s.read_document('d')
        b=read['blocks'][0];assert b['kind']=='image' and b['embedded']
        assert s.read_image('d',read['revision'],b['target_id'])['ok']
    finally:s.close()

def test_revision_ignores_only_binary_length_hint():
    x=fixture()
    a=x.replace('Encoding="Base64"','Encoding="Base64" Size="8719"')
    b=x.replace('Encoding="Base64"','Encoding="Base64" Size="8704"')
    assert dm.revision(a)==dm.revision(b)
    changed=b.replace('BinItem="1"','BinItem="2"')
    assert dm.revision(a)!=dm.revision(changed)
    assert dm.revision(a)!=dm.revision(b.replace('iVBOR','aVBOR'))

def test_image_find_and_cannot_edit_pixels():
    model=dm.model(fixture())
    found=dm.locate(model,{'type':'image','occurrence':1})
    assert len(found)==1 and found[0]['embedded']
    with pytest.raises(WriterError):
        dm.compile_edits(model,[{'type':'replace_text','target_id':found[0]['target_id'],'expected_text':'','text':'x'}])

def test_transparency_has_readable_paper_background():
    image=Image.new('RGBA',(200,100),(0,0,0,0));image.putpixel((0,0),(0,0,0,255))
    out=io.BytesIO();image.save(out,format='PNG')
    x=fixture(payload=base64.b64encode(out.getvalue()).decode())
    result=output(images.extract(*args(x)))
    assert result.getpixel((0,0))==(0,0,0) and result.getpixel((1,1))==(255,255,255)

def test_binary_mapping_reference_is_not_binary_id():
    x=fixture().replace('BinData="1"','BinData="7"').replace('Id="1" Encoding=','Id="7" Encoding=')
    assert output(images.extract(*args(x))).size==(200,100)
    model=dm.model(x)
    assert model['paragraphs'][0]['parts'][0]['image']['bin_id']=='7'

def test_binary_mapping_can_follow_external_link():
    x=fixture().replace('<BINITEM BinData="1"', '<BINITEM Type="Link" APath="Z:/do-not-open.png"/><BINITEM BinData="1"')
    x=x.replace('BinItem="1"','BinItem="2"')
    assert images.extract(*args(x))['ok']

def test_picture_effects_are_reported():
    x=fixture('<EFFECTS><GLOW Radius="50"/></EFFECTS>')
    assert images.extract(*args(x))['warnings']

@pytest.mark.parametrize('fmt',['PNG','JPEG','BMP','GIF','TIFF','WEBP'])
def test_supported_raster_decoders(fmt):
    image=Image.new('RGB',(200,100),'white')
    out=io.BytesIO();image.save(out,format=fmt)
    x=fixture(payload=base64.b64encode(out.getvalue()).decode()).replace('Format="png"','Format="'+fmt.lower()+'"')
    assert output(images.extract(*args(x))).size==(200,100)

def test_limits_are_explicit(monkeypatch):
    monkeypatch.setattr(images,'MAX_BYTES',1)
    with pytest.raises(WriterError) as e:images.extract(*args(fixture()))
    assert e.value.code=='IMAGE_TOO_LARGE'
    monkeypatch.setattr(images,'MAX_BYTES',24*1024*1024)
    monkeypatch.setattr(images,'MAX_PIXELS',1)
    with pytest.raises(WriterError) as e:images.extract(*args(fixture()))
    assert e.value.code=='IMAGE_TOO_LARGE'

def test_images_in_excluded_regions_have_no_read_target():
    x=fixture().replace('<P>','<HEADER><P>').replace('</P>','</P></HEADER>')
    model=dm.model(x);part=model['paragraphs'][0]['parts'][0]
    assert part['id'] not in model['targets']
    with pytest.raises(WriterError):images.extract(x,model['revision'],part['id'])
