"""Known-answer nonidentity CMS check; no production engine operators reused."""
import ctypes
import numpy as np
from raw_benchmark.imaging import CMS
from raw_benchmark.common import RUN, write, now, sha

class xyY(ctypes.Structure):
    _fields_=[('x',ctypes.c_double),('y',ctypes.c_double),('Y',ctypes.c_double)]
class Primaries(ctypes.Structure):
    _fields_=[('Red',xyY),('Green',xyY),('Blue',xyY)]

def main():
    cms=CMS(); lib=cms.lib
    lib.cmsBuildGamma.argtypes=[ctypes.c_void_p,ctypes.c_double]; lib.cmsBuildGamma.restype=ctypes.c_void_p
    lib.cmsFreeToneCurve.argtypes=[ctypes.c_void_p]
    lib.cmsCreateRGBProfile.argtypes=[ctypes.POINTER(xyY),ctypes.POINTER(Primaries),ctypes.POINTER(ctypes.c_void_p)]
    lib.cmsCreateRGBProfile.restype=ctypes.c_void_p
    gamma=lib.cmsBuildGamma(None,1.0); curves=(ctypes.c_void_p*3)(gamma,gamma,gamma)
    p=lib.cmsCreateRGBProfile(ctypes.byref(xyY(.3127,.3290,1)),
        ctypes.byref(Primaries(xyY(.64,.33,1),xyY(.30,.60,1),xyY(.15,.06,1))),curves)
    if not p: raise RuntimeError('linear profile creation failed')
    size=ctypes.c_uint32(); lib.cmsSaveProfileToMem(p,None,ctypes.byref(size))
    memory=ctypes.create_string_buffer(size.value); lib.cmsSaveProfileToMem(p,memory,ctypes.byref(size))
    profile=memory.raw[:size.value]; lib.cmsCloseProfile(p); lib.cmsFreeToneCurve(gamma)
    source=RUN/'profiles/synthetic-linear-sRGB.icc'; source.write_bytes(profile)
    samples=np.linspace(0,1,4096,dtype=np.float32).reshape(1,4096,1).repeat(3,2)
    observed=cms.transform(samples,profile)
    expected=np.where(samples<=.0031308,12.92*samples,1.055*samples**(1/2.4)-.055)
    error=float(np.max(np.abs(observed-expected)))
    result={'created_at':now(),'status':'PASS' if error<3e-4 else 'FAIL',
        'test':'Linear-sRGB gamma=1 ICC -> pinned encoded sRGB; independent IEC piecewise expected values',
        'samples':4096,'actual_float_transform_max_error':error,'tolerance':3e-4,
        'nonidentity_response_at_linear_0_5':float(observed[0,2048,0]),
        'distinct_output_levels':len(np.unique(observed[:,:,0])),
        'source_icc_sha256':sha(source),'target_icc_sha256':sha(cms.target_path),
        'measurement_8bit_conversion':False,'engine_operators_reused':False}
    write(RUN/'color-transform-tests.json',result); print(result)
    if result['status']!='PASS': raise SystemExit(1)

if __name__=='__main__': main()
