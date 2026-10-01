"""Independent reconstruction of the pinned darktable sRGB output color tags.

release-5.6.1 common/colorspaces.c: _colorspaces_create_srgb_profile(TRUE)
and common/colorspaces.h: D65xyY. Header timestamps/descriptive tags are not
color interpretation. Compare matrix, TRC, whitepoint and adaptation tag bytes.
"""
import ctypes
import struct
from raw_benchmark.imaging import CMS
from raw_benchmark.common import BASE, RUN, sha, write, now
from benchmark.check_color_transform import xyY, Primaries

COLOR_TAGS=('rXYZ','gXYZ','bXYZ','rTRC','gTRC','bTRC','wtpt','chad')

def color_tags(data):
    result={}
    for i in range(struct.unpack_from('>I',data,128)[0]):
        sig=data[132+i*12:136+i*12].decode('ascii')
        start,count=struct.unpack_from('>II',data,136+i*12)
        if start+count>len(data): raise ValueError('truncated ICC tag')
        result[sig]=data[start:start+count]
    return {tag:result[tag] for tag in COLOR_TAGS}

def darktable_srgb_expected(cms):
    lib=cms.lib
    lib.cmsBuildParametricToneCurve.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_double)]
    lib.cmsBuildParametricToneCurve.restype=ctypes.c_void_p
    lib.cmsSetProfileVersion.argtypes=[ctypes.c_void_p,ctypes.c_double]
    lib.cmsCreateRGBProfile.argtypes=[ctypes.POINTER(xyY),ctypes.POINTER(Primaries),ctypes.POINTER(ctypes.c_void_p)]
    lib.cmsCreateRGBProfile.restype=ctypes.c_void_p
    lib.cmsFreeToneCurve.argtypes=[ctypes.c_void_p]
    parameters=(ctypes.c_double*5)(2.4,1/1.055,.055/1.055,1/12.92,.04045)
    curve=lib.cmsBuildParametricToneCurve(None,4,parameters)
    if not curve: raise ValueError('independent curve construction failed')
    profile=None
    try:
        profile=lib.cmsCreateRGBProfile(ctypes.byref(xyY(.31271,.32902,1)),
            ctypes.byref(Primaries(xyY(.64,.33,1),xyY(.30,.60,1),xyY(.15,.06,1))),
            (ctypes.c_void_p*3)(curve,curve,curve))
        if not profile: raise ValueError('independent profile construction failed')
        lib.cmsSetProfileVersion(profile,2.4)
        size=ctypes.c_uint32(); lib.cmsSaveProfileToMem(profile,None,ctypes.byref(size))
        memory=ctypes.create_string_buffer(size.value)
        lib.cmsSaveProfileToMem(profile,memory,ctypes.byref(size))
        expected=memory.raw[:size.value]
    finally:
        if profile: lib.cmsCloseProfile(profile)
        lib.cmsFreeToneCurve(curve)
    path=RUN/'profiles/source-derived-darktable-sRGB-v2.icc'; path.write_bytes(expected)
    write(RUN/'profile-contract-evidence.json',{
        'created_at':now(),'method':'Reconstruct RGB ICC v2.4 matrix/TRC from pinned official darktable release source, compare eight color tag payloads byte-exactly',
        'source':[{'path':str(BASE/'reference'/p),'sha256':sha(BASE/'reference'/p),
                   'url':'https://raw.githubusercontent.com/darktable-org/darktable/release-5.6.1/src/common/'+name}
                  for p,name in [('dt-colorspaces.c','colorspaces.c'),('dt-colorspaces.h','colorspaces.h')]],
        'expected_profile_sha256':sha(path),'tags':list(COLOR_TAGS),
        'D65xyY':[.31271,.32902,1], 'TRC_type':4,
        'TRC_parameters':list(parameters),'ICC_version':2.4,
        'target_profile_is_separate':True,'normalization_pixels_changed':False,
        'limitation':'Configured-profile consistency, not verification of camera calibration or physical scene color.'})
    return expected
