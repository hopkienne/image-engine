import ctypes
import math
import zipfile
import numpy as np
import tifffile
from PIL import Image
from .common import *

RGB_FLT=(1<<22)|(4<<16)|(3<<3)|4

class CMS:
    def __init__(self):
        dll=load(RUN/'engines.lock.json')['lcms']
        if sha(dll['path'])!=dll['sha256']: raise ValueError('LCMS binary hash changed')
        self.lib=ctypes.CDLL(dll['path'])
        signatures={'cmsOpenProfileFromMem':([ctypes.c_void_p,ctypes.c_uint32],ctypes.c_void_p),
                    'cmsCreate_sRGBProfile':([],ctypes.c_void_p),
                    'cmsSaveProfileToMem':([ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)],ctypes.c_int),
                    'cmsGetColorSpace':([ctypes.c_void_p],ctypes.c_uint32),
                    'cmsCreateTransform':([ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_void_p),
                    'cmsDoTransform':([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32],None),
                    'cmsDeleteTransform':([ctypes.c_void_p],None),
                    'cmsCloseProfile':([ctypes.c_void_p],ctypes.c_int)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.lib,name); fn.argtypes=args; fn.restype=result
        self.target_path=RUN/'profiles/target-sRGB.icc'
        if not self.target_path.exists():
            self.target_path.parent.mkdir(exist_ok=True)
            p=self.lib.cmsCreate_sRGBProfile(); size=ctypes.c_uint32()
            self.lib.cmsSaveProfileToMem(p,None,ctypes.byref(size))
            buf=ctypes.create_string_buffer(size.value)
            self.lib.cmsSaveProfileToMem(p,buf,ctypes.byref(size)); self.lib.cmsCloseProfile(p)
            self.target_path.write_bytes(buf.raw[:size.value])
        self.target=self.target_path.read_bytes()

    def transform(self,array,profile,expected_sha=None):
        if not profile: raise ValueError('BLOCKED: missing ICC; no implicit sRGB retag')
        if expected_sha and hashlib.sha256(profile).hexdigest()!=expected_sha:
            raise ValueError('ICC contradicts verified descriptor')
        memory=[ctypes.create_string_buffer(v) for v in (profile,self.target)]
        profiles=[self.lib.cmsOpenProfileFromMem(m,len(v)) for m,v in zip(memory,(profile,self.target))]
        tr=None
        try:
            if not all(profiles): raise ValueError('invalid ICC')
            if any(self.lib.cmsGetColorSpace(p)!=0x52474220 for p in profiles): raise ValueError('not RGB ICC')
            tr=self.lib.cmsCreateTransform(profiles[0],RGB_FLT,profiles[1],RGB_FLT,1,0x0100)
            if not tr: raise ValueError('BLOCKED: cannot build verified RGB float CMS transform')
            a=np.ascontiguousarray(array,dtype=np.float32); out=np.empty_like(a)
            flat=a.reshape(-1,3); output=out.reshape(-1,3)
            for start in range(0,len(flat),262144):
                n=min(262144,len(flat)-start)
                self.lib.cmsDoTransform(tr,flat[start:].ctypes.data,output[start:].ctypes.data,n)
            return out
        finally:
            if tr: self.lib.cmsDeleteTransform(tr)
            for p in profiles:
                if p: self.lib.cmsCloseProfile(p)

def orient(a,code):
    if code==1: return a
    if code==2: return a[:,::-1]
    if code==3: return a[::-1,::-1]
    if code==4: return a[::-1]
    if code==5: return a.transpose(1,0,2)
    if code==6: return np.rot90(a,3)
    if code==7: return a.transpose(1,0,2)[::-1,::-1]
    if code==8: return np.rot90(a,1)
    raise ValueError('unknown orientation')

def finite_range(a,bounded=True):
    if not np.isfinite(a).all(): raise ValueError('nonfinite pixels')
    count=int(np.count_nonzero((a<0)|(a>1)))
    if bounded and count: raise ValueError('bounded descriptor range violation')
    return {'finite':True,'minimum':float(a.min()),'maximum':float(a.max()),'outside_0_1_channels':count,
            'bounded_native':bounded}

def read_native(folder,engine):
    if engine=='ours':
        d=load(folder/'native.json'); h,w=d['height'],d['width']
        checked_output(folder/'native.f32',h*w*3*4)
        if (d['sampleType'],d['transferFunction'],d['primaries'],d['orientationState'])!=('float32','srgb-encoded','sRGB','baked-normalized'):
            raise ValueError('unsupported ours pixel descriptor')
        a=np.fromfile(folder/'native.f32',dtype='<f4').reshape(h,w,3)
        with Image.open(folder/'output.jpg') as jpeg: icc=jpeg.info.get('icc_profile')
        # JPEG carries the matching production ICC; JPEG pixels are NEVER measurement input.
        d.update(icc_contract='production pre-quantize encoded-sRGB dump; ICC extracted from matching production JPEG container',
                 native_precision_bits=32,orientation_tag=1)
        return a,icc,d
    path=folder/'native.tif'; checked_output(path)
    with tifffile.TiffFile(path) as t:
        p=t.pages[0]
        if p.dtype not in (np.dtype('uint16'),np.dtype('float32')) or len(p.shape)!=3 or p.shape[2]!=3:
            raise ValueError('not actual 16-bit/float RGB TIFF')
        a=p.asarray(); icc=p.tags.get(34675); icc=icc.value if icc else None
        orientation=p.tags.get(274); orientation=int(orientation.value) if orientation else 1
        d={'width':p.shape[1],'height':p.shape[0],'channels':3,'sampleType':str(p.dtype),
           'native_precision_bits':p.dtype.itemsize*8,'orientation_tag':orientation,
           'icc_contract':'embedded ICC interpreted by LCMS; missing/wrong profile rejected'}
    if a.dtype==np.uint16: a=a.astype(np.float32)/65535.0
    a=orient(a,orientation)
    return a,icc,d

def tiff_write(path,a,icc):
    tifffile.imwrite(path,a,photometric='rgb',metadata=None,compression='deflate',compressionargs={'level':3},
                     predictor=3,rowsperstrip=64,
                     extratags=[(34675,'B',len(icc),icc,False),(274,'H',1,1,False)])

def preview(a,path,size=1600):
    p=Image.fromarray(np.rint(np.clip(a,0,1)*255).astype(np.uint8))
    p.thumbnail((size,size),Image.Resampling.LANCZOS)
    p.save(path)

def normalize(folder,engine):
    a,icc,descriptor=read_native(folder,engine)
    descriptor['native_pixel_sha256']=hashlib.sha256(a.tobytes()).hexdigest()
    descriptor['native_range']=finite_range(a,engine=='ours' or descriptor['sampleType']=='uint16')
    if not icc: raise ValueError('BLOCKED: no native RGB ICC')
    source_hash=hashlib.sha256(icc).hexdigest(); profile_path=RUN/'profiles'/f'{source_hash}.icc'
    profile_path.parent.mkdir(exist_ok=True); profile_path.write_bytes(icc)
    cms=CMS(); norm=cms.transform(a,icc)
    stats=finite_range(norm,False)
    descriptor.update(icc_sha256=source_hash,target_icc_sha256=sha(cms.target_path),
                      normalization='LCMS 2.17 RGB_FLT -> RGB_FLT, relative-colorimetric, NOOPTIMIZE; no histogram/WB matching',
                      normalized_before_clamp=stats,
                      range_policy='Explicit display SDR clamp AFTER finite/range evidence; native range preserved',
                      normalized_dtype='float32',orientation_state='baked-normalized')
    preview(a,folder/'native-preview.png')
    norm=np.clip(norm,0,1)
    output=folder/'normalized.tif'; tiff_write(output,norm,cms.target)
    # Verify exact float32 pixel roundtrip: no silent 8-bit or 16-bit downgrade.
    verify=tifffile.imread(output)
    if not np.array_equal(norm,verify): raise ValueError('normalized lossless roundtrip mismatch')
    del verify
    descriptor['normalized_pixel_sha256']=hashlib.sha256(norm.tobytes()).hexdigest()
    preview(norm,folder/'overview.png')
    native_paths=[folder/'native.f32',folder/'native.json'] if engine=='ours' else [folder/'native.tif']
    native=[checked_output(p) for p in native_paths]
    if engine=='ours':
        archive=folder/'native-f32.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
            z.write(folder/'native.f32','native.f32'); z.write(folder/'native.json','native.json')
        with zipfile.ZipFile(archive) as z:
            h=hashlib.sha256()
            with z.open('native.f32') as f:
                for part in iter(lambda:f.read(1024*1024),b''): h.update(part)
            if h.hexdigest()!=native[0]['sha256']: raise ValueError('native archive roundtrip hash mismatch')
        (folder/'native.f32').unlink()  # Own transient after lossless byte verification, never source RAW.
        native[0]['archive']=checked_output(archive)
    write(folder/'descriptor.json',descriptor)
    return norm,descriptor,native,checked_output(output)

def linear(a):
    return np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)

def endpoints(a):
    return {'near_white_any':float(np.mean(a.max(axis=2)>=.995)),
            'near_white_all':float(np.mean(a.min(axis=2)>=.995)),
            'near_black_all':float(np.mean(a.max(axis=2)<=.005)),
            'near_white_channels':[float(np.mean(a[:,:,c]>=.995)) for c in range(3)],
            'near_black_channels':[float(np.mean(a[:,:,c]<=.005)) for c in range(3)]}

def measurements(a,folder):
    e=endpoints(a)
    y=np.empty(a.shape[:2],dtype=np.float32)
    hist=np.zeros((3,256),dtype=np.int64)
    for start in range(0,len(a),128):
        chunk=a[start:start+128]; lin=linear(chunk)
        y[start:start+128]=lin[:,:,0]*.2126+lin[:,:,1]*.7152+lin[:,:,2]*.0722
        for c in range(3): hist[c]+=np.histogram(chunk[:,:,c],bins=256,range=(0,1))[0]
    q=np.quantile(y,[.01,.5,.99]).tolist(); del y
    h,w=a.shape[:2]; side=min(512,h,w)
    rois=[]
    for label,xx,yy in [('center',(w-side)//2,(h-side)//2),('top-left',0,0),('bottom-right',w-side,h-side)]:
        roi=a[yy:yy+side,xx:xx+side]; l=linear(roi); lum=l[:,:,0]*.2126+l[:,:,1]*.7152+l[:,:,2]*.0722
        lap=lum[:-2,1:-1]+lum[2:,1:-1]+lum[1:-1,:-2]+lum[1:-1,2:]-4*lum[1:-1,1:-1]
        chroma=roi[:,:,0]-roi[:,:,1]
        hf=chroma[:-2,1:-1]+chroma[2:,1:-1]+chroma[1:-1,:-2]+chroma[1:-1,2:]-4*chroma[1:-1,1:-1]
        crop=folder/f'roi-{label}.png'; preview(roi,crop,side)
        rois.append({'label':label,'native_pixel_rectangle':[xx,yy,side,side],
                     'laplacian_variance_linear_Y':float(np.var(lap)),'median_absolute_hf_RG_encoded':float(np.median(np.abs(hf))),
                     'path':rel(crop),'flatness':'candidate only; no verified flat/neutral reference',
                     'limitation':'Texture, demosaic, sharpening and noise confounded. No sensor SNR or quality score.'})
    return {'endpoints':e,'linear_Y_quantiles':dict(zip(('p01','p50','p99'),q)),
            'histogram_encoded_RGB_256bins':hist.tolist(),'rois':rois,
            'domain':'endpoint encoded sRGB [0,1]; Y linear sRGB Rec.709 coefficients',
            'mask':'all valid native pixels after verified orientation; pairwise use validated overlap only',
            'technical_anomaly':bool(e['near_black_all']>=.9999 or e['near_white_all']>=.9999),
            'absolute_color_accuracy':{'status':'NOT_RUN','reason':'NO_VALID_COLOR_REFERENCE'},
            'dynamic_range_stops':None}

def phase_shift(a,b):
    # Correlate native-grid edge patches; no resampling or nonlinear geometry.
    aa=a.mean(axis=2); bb=b.mean(axis=2)
    aa=np.gradient(aa)[0]+np.gradient(aa)[1]; bb=np.gradient(bb)[0]+np.gradient(bb)[1]
    fa=np.fft.fft2(aa-aa.mean()); fb=np.fft.fft2(bb-bb.mean())
    cross=fa*np.conj(fb); cross/=np.maximum(np.abs(cross),1e-12)
    yy,xx=np.unravel_index(np.argmax(np.fft.ifft2(cross).real),aa.shape)
    if yy>aa.shape[0]//2: yy-=aa.shape[0]
    if xx>aa.shape[1]//2: xx-=aa.shape[1]
    return int(xx),int(yy)

def overlap(a,b,dx,dy):
    # Coordinate of B pixel is A coordinate + (dx,dy).
    x0=max(0,-dx); y0=max(0,-dy); x1=min(a.shape[1],b.shape[1]-dx); y1=min(a.shape[0],b.shape[0]-dy)
    if x1<=x0 or y1<=y0: raise ValueError('no overlap')
    return (slice(y0,y1),slice(x0,x1)),(slice(y0+dy,y1+dy),slice(x0+dx,x1+dx))

def alignment(a,b):
    h=min(a.shape[0],b.shape[0]); w=min(a.shape[1],b.shape[1]); side=min(512,h//3,w//3)
    initx=(b.shape[1]-a.shape[1])//2; inity=(b.shape[0]-a.shape[0])//2
    evidence=[]; offsets=[]
    if side<32: return {'status':'NOT_COMPARABLE','reason':'insufficient patch size'}
    for fx,fy in ((.5,.5),(.25,.25),(.75,.75)):
        x=max(32,int(w*fx)-side//2); y=max(32,int(h*fy)-side//2)
        ap=a[y:y+side,x:x+side]; bp=b[y+inity:y+inity+side,x+initx:x+initx+side]
        if ap.shape!=bp.shape: return {'status':'NOT_COMPARABLE','reason':'patch crop outside frame'}
        sx,sy=phase_shift(ap,bp); dx=initx-sx; dy=inity-sy
        if abs(dx)>64 or abs(dy)>64: return {'status':'NOT_COMPARABLE','reason':'integer mapping exceeds search bound'}
        bp=b[y+dy:y+dy+side,x+dx:x+dx+side]
        if ap.shape!=bp.shape: return {'status':'NOT_COMPARABLE','reason':'shift patch outside frame'}
        aa=ap.mean(axis=2); bb=bp.mean(axis=2)
        ea=np.gradient(aa)[0]+np.gradient(aa)[1]; eb=np.gradient(bb)[0]+np.gradient(bb)[1]
        corr=float(np.corrcoef(ea.ravel(),eb.ravel())[0,1])
        evidence.append({'a_patch':[x,y,side,side],'offset_B_minus_A':[dx,dy],
                         'edge_correlation':corr if math.isfinite(corr) else None})
        offsets.append((dx,dy))
    if len(set(offsets))!=1 or any(v['edge_correlation'] is None or v['edge_correlation']<.80 for v in evidence):
        return {'status':'NOT_COMPARABLE','reason':'three native edge patches disagree or correlation below .80','evidence':evidence}
    dx,dy=offsets[0]; sa,sb=overlap(a,b,dx,dy)
    return {'status':'COMPARABLE','offset_B_minus_A':[dx,dy],'evidence':evidence,
            'mask_A':[sa[1].start,sa[0].start,sa[1].stop-sa[1].start,sa[0].stop-sa[0].start],
            'method':'consistent integer translation across 3 native-grid edge patches after known orientation; no resize/warp',
            'mask_sha256':digest([a.shape,b.shape,dx,dy])}

def difference(a,b):
    d=a.astype(np.float64)-b.astype(np.float64)
    return {'MAE':float(np.mean(np.abs(d))),'RMSE':float(np.sqrt(np.mean(d*d))),
            'max_absolute_channel':float(np.max(np.abs(d))),'units':'encoded sRGB fraction; descriptive difference only'}

def pair(a,b,folder):
    mapping=alignment(a,b)
    if mapping['status']!='COMPARABLE': return mapping
    dx,dy=mapping['offset_B_minus_A']; sa,sb=overlap(a,b,dx,dy)
    aa=a[sa]; bb=b[sb]; total=0; absolute=0.; squared=0.; maximum=0.
    heat=np.zeros(aa.shape[:2],np.float32)
    for start in range(0,len(aa),128):
        d=aa[start:start+128].astype(np.float64)-bb[start:start+128].astype(np.float64)
        total+=d.size; absolute+=np.abs(d).sum(); squared+=(d*d).sum(); maximum=max(maximum,float(np.abs(d).max()))
        heat[start:start+128]=np.abs(d).mean(axis=2)
    rgb=np.zeros((*heat.shape,3),np.float32); rgb[:,:,0]=np.clip(heat/.25,0,1)
    preview(rgb,folder/'diff.png')
    mapping.update(MAE=absolute/total,RMSE=math.sqrt(squared/total),max_absolute_channel=maximum,
                   units='encoded sRGB fraction; descriptive, never correctness or acceptance',
                   heatmap={'path':rel(folder/'diff.png'),'fixed_scale':[0,.25],'saturated_above':.25})
    side=min(512,*aa.shape[:2]); x=(aa.shape[1]-side)//2; y=(aa.shape[0]-side)//2
    for label,img in [('A',aa),('B',bb)]: preview(img[y:y+side,x:x+side],folder/f'matched-{label}.png',side)
    mapping['matched_roi']={'overlap_rectangle':[x,y,side,side],'A_path':rel(folder/'matched-A.png'),
                            'B_path':rel(folder/'matched-B.png'),'display':'100% native pixels'}
    mapping['endpoints_A']=endpoints(aa); mapping['endpoints_B']=endpoints(bb)
    def median_y(img):
        y=np.empty(img.shape[:2],np.float32)
        for start in range(0,len(img),128):
            l=linear(img[start:start+128]); y[start:start+128]=l[:,:,0]*.2126+l[:,:,1]*.7152+l[:,:,2]*.0722
        return float(np.median(y))
    mapping['median_linear_Y_A']=median_y(aa); mapping['median_linear_Y_B']=median_y(bb)
    return mapping

def triage(pairs, anomaly=False):
    valid=[p for p in pairs if p.get('status')=='COMPARABLE']
    result={'quality_triage':'NOT_EVALUATED','reference_status':'PARTIAL_REFERENCE',
            'review_status':'NOT_REVIEWED','flags':[],
            'limitation':'Exploratory rules only; converters are not ground truth.'}
    if anomaly: result['flags'].append('all-black/all-white technical anomaly')
    if len(valid)!=2:
        if anomaly: result['quality_triage']='REVIEW_REQUIRED'
        return result
    result['reference_status']='COMPARABLE'; result['quality_triage']='NO_FLAG'
    for key in ('near_white_any','near_white_all','near_black_all'):
        if all(p['endpoints_A'][key]-p['endpoints_B'][key]>.02 for p in valid):
            result['flags'].append(f'{key} exceeds EACH reference by >0.02 on verified overlap')
    if all(min(p['median_linear_Y_A'],p['median_linear_Y_B'])>.01 for p in valid):
        ev=[math.log2(p['median_linear_Y_A']/p['median_linear_Y_B']) for p in valid]
        result['median_Y_delta_EV_each_reference']=ev
        if all(abs(v)>=.5 for v in ev): result['flags'].append('median linear Y differs >=0.5 EV from EACH reference; exposure/WB/pipeline investigation needed')
    if result['flags']: result['quality_triage']='REVIEW_REQUIRED'
    return result
