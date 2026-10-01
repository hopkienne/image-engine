"""New immutable reference investigation; never writes run-v1. Run as module."""
import argparse, configparser, ctypes as C, hashlib, json, os, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'benchmark/python-deps'))
import numpy as np
import tifffile
from PIL import Image
from raw_benchmark import common, imaging
OLD=common.RUN
from raw_benchmark.common import sha, load, write
RT=common.binaries()['rawtherapee']

class IndependentTiff:
    """libtiff scanlines, NOT Pillow's 8-bit RGB TIFF path."""
    def __init__(self):
        self.dll_dir=os.add_dll_directory(str(RT.parent))
        self.lib=C.CDLL(str(RT.parent/'libtiff-6.dll'))
        for name,args,res in [('TIFFOpen',[C.c_char_p,C.c_char_p],C.c_void_p),('TIFFClose',[C.c_void_p],None),('TIFFReadScanline',[C.c_void_p,C.c_void_p,C.c_uint32,C.c_uint16],C.c_int),('TIFFScanlineSize64',[C.c_void_p],C.c_uint64)]:
            f=getattr(self.lib,name);f.argtypes=args;f.restype=res
    def read(self,path,shape):
        t=self.lib.TIFFOpen(str(path).encode(),'r'.encode());assert t
        try:
            a=np.empty(shape,dtype=np.uint16);assert self.lib.TIFFScanlineSize64(t)==shape[1]*6
            for y in range(shape[0]):assert self.lib.TIFFReadScanline(t,a[y].ctypes.data,y,0)==1
            return a
        finally:self.lib.TIFFClose(t)

def picture(a,p):
    Image.fromarray(np.rint(np.clip(a,0,1)*255).astype('uint8')).save(p)

def inspect(path,out,reader,cms):
    out.mkdir(parents=True,exist_ok=True)
    with tifffile.TiffFile(path) as t:
        page=t.pages[0];a=page.asarray();icc=page.tags[34675].value
        assert a.dtype==np.uint16 and int(page.tags.get(274).value)==1
    b=reader.read(path,a.shape);assert np.array_equal(a,b)
    native=b.astype('float32')/65535;norm=np.clip(cms.transform(native,icc),0,1)
    h,w=a.shape[:2];x,y=w//2-256,h//2-256
    picture(native[y:y+512,x:x+512],out/'native-crop.png')
    picture(norm[y:y+512,x:x+512],out/'normalized-crop.png')
    imaging.preview(norm,out/'overview.png',1200)
    imaging.tiff_write(out/'normalized.tif',norm,cms.target)
    info={'native_sha256':sha(path),'reader':'libtiff TIFFReadScanline uint16 RGB; byte-exact vs tifffile/imagecodecs',
          'independent_reader_dll_sha256':sha(RT.parent/'libtiff-6.dll'),'shape':list(a.shape),'dtype':str(a.dtype),'orientation':1,
          'icc_sha256':hashlib.sha256(icc).hexdigest(),'normalized_sha256':sha(out/'normalized.tif'),
          'crop_xywh':[x,y,512,512],'native_pixel_sha256':hashlib.sha256(a.tobytes()).hexdigest(),
          'precision':'uint16 preserved through read, FP32 LCMS transform, 8-bit display only',
          'mean_rgb':norm.mean(axis=(0,1),dtype='float64').tolist()}
    write(out/'inspection.json',info)
    return info

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    assert sha(RT)==load(OLD/'engines.lock.json')['engines']['rawtherapee']['sha256'], 'Pinned RT executable changed; re-verify version/source before rendering'
    common.RUN=out # process logs are relative to new run; CMS reads the old locked ICC only.
    reader=IndependentTiff();cms=imaging.CMS()
    # Known sentinel tests catch channel swaps, byte order and silent 8-bit truncation.
    sentinel=np.array([[[1,256,65535],[65534,4097,17]],[[0,32768,12345],[8193,511,257]]],dtype='uint16')
    tifffile.imwrite(out/'reader-sentinel.tif',sentinel,photometric='rgb',compression='deflate',metadata=None)
    assert np.array_equal(reader.read(out/'reader-sentinel.tif',sentinel.shape),sentinel)
    from benchmark.check_color_transform import main as color_check
    import benchmark.check_color_transform as color_module
    color_module.RUN=out
    (out/'profiles').mkdir(exist_ok=True)
    color_check()
    linear=np.array([[[0.,.0031308,.18],[.5,1.,.01]]],dtype='float32')
    # cms target identity is independently checked for RGB channel/precision preservation.
    identity=cms.transform(linear,cms.target)
    assert np.max(np.abs(linear-identity))<1e-5
    write(out/'reader-checks.json',{'sentinel_exact':True,'cms_identity_max_abs':float(np.max(np.abs(linear-identity))),
        'nonidentity_color_validation':str(out/'color-transform-tests.json'),'color_validation_sha256':sha(out/'color-transform-tests.json')})
    items={i['source_id']:i for i in load(OLD/'corpus.manifest.json')['items']}
    baseline_record=load(OLD/'jobs/R025/rawtherapee/latest.json')
    base=configparser.ConfigParser();base.optionxform=str;base.read(OLD/baseline_record['settings_path'])
    fixed=configparser.ConfigParser();fixed.optionxform=str;fixed.read(ROOT/'benchmark/configs/base.pp3');fixed['RAW X-Trans']['Method']='3-pass (best)'
    results=[]; opened=[]
    for sid in ['R025','R039','R001','R004']:
        item=items[sid];source=OLD/item['path'];assert sha(source)==item['sha256']
        opened.append({'id':sid,'previous_split':item['split'],'now':'opened-investigation-regression; NOT confirmation holdout'})
        old=load(OLD/f'jobs/{sid}/rawtherapee/latest.json');oldpath=OLD/old['native_export'][0]['path']
        assert sha(oldpath)==old['native_export'][0]['sha256']
        previous=inspect(oldpath,out/sid/'before',reader,cms)
        previous.update(id=sid,variant='before',execution=old['execution']['status'],reference_quality_anomaly='GREEN_GRID' if sid in ['R025','R039'] else None)
        write(out/sid/'before/record.json',previous)
        variants=[('neutral',None)]
        if sid in ['R025','R039']:
            groups=[('exposure',['Exposure','HLRecovery']),('wb',['White Balance']),('color',['Color Management']),('optional',[s for s in base.sections() if s not in ['Version','Exposure','HLRecovery','White Balance','Color Management','RAW X-Trans']])]
            cumulative=configparser.ConfigParser();cumulative.optionxform=str
            for name,sections in groups:
                for section in sections:cumulative[section]=dict(base[section])
                variants.append(('neutral-plus-'+name,{s:dict(cumulative[s]) for s in cumulative.sections()}))
            variants += [('base-old-token',{s:dict(base[s]) for s in base.sections()}),('base-none',{s:(dict(base[s]) if s!='RAW X-Trans' else {'Method':'none'}) for s in base.sections()})]
        variants += [('base-fixed',{s:dict(fixed[s]) for s in fixed.sections()}),('base-fixed-ev1',{s:(dict(fixed[s]) if s!='Exposure' else dict(fixed[s],Compensation='1')) for s in fixed.sections()})]
        for name,settings in variants:
            folder=out/sid/name;folder.mkdir(parents=True,exist_ok=False)
            raw=folder/('input'+source.suffix);shutil.copyfile(source,raw)
            # Documented options file, not an invented command-line switch.
            conf=folder/'rt-settings';conf.mkdir();(conf/'options').write_text('[General]\nVerbose=true\n[Raw Decoder]\nEnableLibRaw=true\n')
            argv=[RT,'-O',folder/'native.tif']
            if settings is not None:
                cp=configparser.ConfigParser();cp.optionxform=str;cp.read_dict(settings)
                with (folder/'profile.pp3').open('w') as f:cp.write(f,space_around_delimiters=False)
                argv+=['-p',folder/'profile.pp3']
            argv+=['-tz','-b16','-c',raw]
            execution=common.process(argv,folder/'process',env_extra={'RT_SETTINGS':str(conf)})
            assert sha(raw)==sha(source)==item['sha256']
            rec={'id':sid,'variant':name,'mode':'BASE_CONTROLLED' if name.startswith('base') else 'INVESTIGATION_NEUTRAL',
                 'execution':execution,'source_sha256':item['sha256'],'exe_sha256':sha(RT),'source_unchanged':True,
                 'settings_sha256':sha(folder/'profile.pp3') if settings is not None else None,
                 'backend_request':'LibRaw enabled in isolated options; actual loader evidence in verbose log',
                 'review_status':'AI_SUGGESTION; NOT_REVIEWED','reference_eligibility':'INCONCLUSIVE'}
            if execution['status']=='SUCCESS':
                rec.update(inspect(folder/'native.tif',folder,reader,cms))
                merged=configparser.ConfigParser();merged.read(folder/'native.tif.pp3')
                rec['saved_method']=merged['RAW X-Trans']['Method'];rec['merged_pp3_sha256']=sha(folder/'native.tif.pp3')
            write(folder/'record.json',rec);results.append(rec)
            print(sid,name,execution['status'],flush=True)
    write(out/'opened-fixtures.json',opened);write(out/'reference-results.json',results)
    evidence=[]
    for sid in ['R025','R039']:
        records={r['variant']:r for r in results if r['id']==sid}
        same=records['base-old-token']['native_pixel_sha256']==records['base-none']['native_pixel_sha256']
        assert same
        assert records['base-fixed']['native_pixel_sha256']!=records['base-old-token']['native_pixel_sha256']
        evidence.append({'id':sid,'invalid_token_equals_none_exactly':same,'first_observed_anomaly_stage':'native TIFF, before normalization',
          'root_cause':'PP3 3-pass does not match 5.13 3-pass (best); source dispatch falls through to nodemosaic(false); controlled none export is pixel-exact',
          'source_scope':'RT 5.13 build commit 1924179107995b01b73cdc7f4fe91e44fc8227a7'})
    effects=[]
    for sid in ['R025','R039','R001','R004']:
        a=tifffile.imread(out/sid/'base-fixed/normalized.tif');b=tifffile.imread(out/sid/'base-fixed-ev1/normalized.tif')
        effects.append({'id':sid,'cfa':items[sid]['cfa'],'change':'Exposure Compensation 0 to 1','max_abs':float(np.max(np.abs(a-b))),'mean_abs':float(np.mean(np.abs(a-b))),'effect':bool(np.any(a!=b))})
        assert effects[-1]['effect']
    write(out/'root-cause.json',evidence);write(out/'config-effects.json',effects)

if __name__=='__main__':main()
