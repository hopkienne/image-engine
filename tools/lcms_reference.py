"""Independent double-precision RGB -> D50 XYZ comparison via Little CMS.

Set PE_AUDIT_LCMS_DLL to a hash-recorded test-only lcms2 library. No engine
operator is reused. Format constants match the pinned lcms2.h ABI.
"""
import ctypes
import hashlib
import os
from pathlib import Path


def compare_xyz(profile_bytes, threshold=2e-4):
    path = Path(os.environ['PE_AUDIT_LCMS_DLL']).resolve()
    lib = ctypes.CDLL(str(path))
    signatures = {
        'cmsOpenProfileFromMem': ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_void_p),
        'cmsCreate_sRGBProfile': ([], ctypes.c_void_p),
        'cmsCreateXYZProfile': ([], ctypes.c_void_p),
        'cmsCreateTransform': ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_void_p),
        'cmsDoTransform': ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32], None),
        'cmsDeleteTransform': ([ctypes.c_void_p], None),
        'cmsCloseProfile': ([ctypes.c_void_p], ctypes.c_int),
        'cmsGetEncodedCMMversion': ([], ctypes.c_uint32),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name); fn.argtypes = args; fn.restype = result
    memory = ctypes.create_string_buffer(profile_bytes)
    profiles, transforms = [], []
    try:
        embedded = lib.cmsOpenProfileFromMem(memory, len(profile_bytes))
        trusted = lib.cmsCreate_sRGBProfile()
        xyz = lib.cmsCreateXYZProfile()
        profiles = [embedded, trusted, xyz]
        if not all(profiles):
            raise ValueError('LCMS could not open/create ICC profiles')
        # FLOAT_SH(1)|COLORSPACE_SH(PT_RGB/PT_XYZ)|CHANNELS_SH(3)|BYTES_SH(0)
        rgb_dbl, xyz_dbl = (1 << 22) | (4 << 16) | (3 << 3), (1 << 22) | (9 << 16) | (3 << 3)
        transforms = [lib.cmsCreateTransform(p, rgb_dbl, xyz, xyz_dbl, 1, 0x0100) for p in (embedded, trusted)]
        if not all(transforms):
            raise ValueError('LCMS could not build RGB double -> XYZ double transforms')
        values = [i / 16 for i in range(17)] + [0.0031308, 0.04045, 0.04044, 0.04046]
        patches = [(r,g,b) for r in values for g in values for b in values]
        inputs = (ctypes.c_double * (len(patches) * 3))(*[v for p in patches for v in p])
        outputs = [(ctypes.c_double * len(inputs))() for _ in range(2)]
        for transform, output in zip(transforms, outputs):
            lib.cmsDoTransform(transform, inputs, output, len(patches))
        errors = [abs(a-b) for a,b in zip(*outputs)]
        worst = max(range(len(errors)), key=errors.__getitem__)
        return {'pass': errors[worst] <= threshold, 'maxAbsoluteXYZError': errors[worst],
                'threshold': threshold, 'patchCount': len(patches), 'worstInputRGB': patches[worst//3],
                'worstXYZChannel': 'XYZ'[worst%3], 'pcs': 'D50 XYZ', 'intent': 'relative-colorimetric',
                'format': 'RGB_DBL -> XYZ_DBL', 'flags': 'NOOPTIMIZE',
                'lcmsVersionEncoded': lib.cmsGetEncodedCMMversion(), 'library': str(path),
                'librarySha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    finally:
        for transform in transforms:
            if transform: lib.cmsDeleteTransform(transform)
        for profile in profiles:
            if profile: lib.cmsCloseProfile(profile)
