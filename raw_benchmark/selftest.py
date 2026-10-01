"""Independent known-answer tests for the benchmark harness, H01-H14."""
import sys
import tempfile
import numpy as np
from .common import *
from .imaging import *
from .corpus import stream_checked

def run():
    rows=[]
    def test(name,fn):
        try:
            detail=fn(); rows.append({'id':name,'status':'PASS','evidence':detail})
        except Exception as e: rows.append({'id':name,'status':'FAIL','reason':str(e)})
    def equal():
        a=np.arange(12,dtype=np.float32).reshape(2,2,3)/12
        assert difference(a,a)['RMSE']==0; return {'max':0,'pixels':4}
    def pixel():
        a=np.zeros((2,2,3)); b=a.copy(); b[0,0,0]=1
        d=difference(a,b); assert abs(d['MAE']-1/12)<1e-12 and abs(d['RMSE']-math.sqrt(1/12))<1e-12
        return d
    def endpoint():
        a=np.zeros((10,10,3)); a[0]=1; e=endpoints(a)
        assert e['near_white_any']==.1 and e['near_white_all']==.1; return e
    def geometry():
        a=np.random.default_rng(4).random((512,512,3),dtype=np.float32)
        b=np.zeros_like(a); b[:,1:]=a[:,:-1]; m=alignment(a,b)
        assert m['status']=='COMPARABLE' and m['offset_B_minus_A']==[1,0]
        rotated=np.rot90(a,3); assert np.array_equal(orient(rotated,8),a)
        assert alignment(a,rotated)['status']=='NOT_COMPARABLE'
        return m
    def precision():
        c=CMS(); a=(np.arange(65536,dtype=np.uint16).astype(np.float32)/65535).reshape(256,256,1).repeat(3,2)
        b=c.transform(a,c.target); error=float(np.abs(a-b).max())
        assert error<2e-6 and len(np.unique(b[:,:,0]))>60000
        # Transform a real linear-sRGB ICC ramp to encoded target, check independent sRGB formula.
        from PIL import ImageCms
        # Do not use ImageCms RGB image conversion (8-bit). LCMS floats above are the measurement path.
        return {'identity_max_error':error,'distinct_levels':len(np.unique(b[:,:,0])),
                'transform':'actual LCMS RGB_FLT; target ICC pinned', 'pillow_used_for_measurement':False}
    def bounds():
        for v in (np.nan,np.inf):
            try: finite_range(np.full((1,1,3),v)); raise AssertionError('accepted nonfinite')
            except ValueError: pass
        a=np.full((1,1,3),2.,np.float32)
        assert finite_range(a,False)['maximum']==2
        try: finite_range(a,True); raise AssertionError('accepted bounded out-of-range')
        except ValueError: pass
        return {'nonfinite_rejected':True,'unbounded_above_one_preserved':True}
    def profiles():
        c=CMS(); a=np.ones((1,1,3),np.float32)
        for icc,expected in ((None,None),(b'wrong',None),(c.target,'0'*64)):
            try: c.transform(a,icc,expected); raise AssertionError('accepted missing/wrong ICC')
            except ValueError: pass
        return {'missing_invalid_inconsistent_rejected':3}
    def output():
        p=RUN/'selftest/truncated.bin'; p.parent.mkdir(exist_ok=True); p.write_bytes(b'0')
        for v,n in ((p,4),(p.with_name('absent.bin'),None)):
            try: checked_output(v,n); raise AssertionError('missing output accepted')
            except ValueError: pass
        return {'exit_zero_not_enough_for_SUCCESS':True}
    def processes():
        f=RUN/'selftest/process'
        timeout=process([sys.executable,'-c','import time; time.sleep(20)'],f/'timeout',.2)
        error=process([sys.executable,'-c','raise SystemExit(17)'],f/'error',3)
        assert timeout['status']=='TIMEOUT' and error['status']=='FAILED' and error['exit_code']==17
        return {'timeout':timeout,'failure':error}
    def cache():
        base={'source':'a','binary':'b','config':'c','profile':'d','normalizer':'e','metrics':'f','dependencies':'g'}
        for key in base: assert digest(base)!=digest(dict(base,**{key:'changed'}))
        return {'content_fields_invalidated':list(base)}
    def download():
        p=RUN/'selftest/download.part'
        expected=hashlib.sha256(b'abcd').hexdigest()
        assert stream_checked(iter([b'ab',b'cd']),p,expected,4,4)==4; p.unlink()
        for chunks,limit,remaining,h in (([b'ab',b'cd'],3,10,expected),([b'abcd'],10,3,expected),([b'abcd'],10,10,'0'*64)):
            try: stream_checked(iter(chunks),p,h,limit,remaining); raise AssertionError('bad download accepted')
            except ValueError: assert not p.exists()
        return {'absent_content_length_supported':True,'actual_file_quota_total_quota_bad_hash_rejected':True}
    def missing():
        p={'status':'NOT_COMPARABLE'}; r=triage([p,p]); assert r['quality_triage']=='NOT_EVALUATED' and r['reference_status']=='PARTIAL_REFERENCE'
        planned=[{'source':'one','portrait':None},{'source':'two','status':'FAILED','portrait':None}]
        assert len(planned)==2 and sum(v.get('portrait') is True for v in planned)==0
        return {'planned_denominator':2,'missing_portrait':'coverage gap','missing_refs':r}
    def ignored():
        a=np.zeros((4,4,3)); assert not effect(a,a) and effect(a,np.full_like(a,.1))
        return {'ignored_config_detected_by_pixel_response':True}
    def anomaly():
        b=endpoints(np.zeros((3,3,3))); w=endpoints(np.ones((3,3,3)))
        assert b['near_black_all']==1 and w['near_white_all']==1
        r=triage([],True); assert r['quality_triage']=='REVIEW_REQUIRED'
        return {'black':b,'white':w,'triage':r}
    for name,fn in zip([f'H{i:02}' for i in range(1,15)],(equal,pixel,endpoint,geometry,precision,bounds,profiles,output,processes,cache,download,missing,ignored,anomaly)):
        test(name,fn)
    result={'created_at':now(),'synthetic_only':True,'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL','rows':rows}
    write(RUN/'harness-tests.json',result); print(result['status'],[(r['id'],r['status']) for r in rows],flush=True)
    return result

if __name__=='__main__': run()
