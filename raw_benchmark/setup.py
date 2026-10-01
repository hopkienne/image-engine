"""Pin actual tools and create explicit RT profile from version-matched key names."""
from .common import *

def prepare():
    profile = '''[Version]
AppVersion=5.13
Version=353
[Exposure]
Auto=false
Compensation=0
Brightness=0
Contrast=0
Saturation=0
Black=0
HighlightCompr=0
ShadowCompr=0
Curve=0;
Curve2=0;
ClampOOG=false
[White Balance]
Enabled=true
Setting=Camera
[Sharpening]
Enabled=false
[PostDemosaicSharpening]
Enabled=false
[SharpenEdge]
Enabled=false
[SharpenMicro]
Enabled=false
[Impulse Denoising]
Enabled=false
[Directional Pyramid Denoising]
Enabled=false
[Shadows & Highlights]
Enabled=false
[Vibrance]
Enabled=false
[Color appearance]
Enabled=false
[Film Simulation]
Enabled=false
[LensProfile]
LcMode=none
UseDistortion=false
UseVignette=false
UseCA=false
[Distortion]
Amount=0
[Chromatic Aberration]
Red=0
Blue=0
[RAW]
CA=false
HotDeadPixels=false
DarkFrame=
FlatFieldFile=
[RAW Bayer]
Method=amaze
[RAW X-Trans]
Method=3-pass
[Crop]
Enabled=false
[Resize]
Enabled=false
[Color Management]
InputProfile=(camera)
WorkingProfile=ProPhoto
OutputProfile=RTv4_sRGB
OutputProfileIntent=Relative
OutputBPC=false
ApplyLookTable=false
ApplyBaselineExposureOffset=false
[HLRecovery]
Enabled=false
[PostResizeSharpening]
Enabled=false
'''
    # Exact PPVERSION and supported keys are recorded in rt-procparams.cc/rtversion.h.
    p=CONFIG/'base.pp3'
    if not p.exists(): p.write_text(profile, encoding='utf-8')
    lock={'created_at':now(),'engines':{},'packages':load(BASE/'tools/downloads.json'),
          'shared_decoder_limitation':'ours uses LibRaw 0.22.2; RT 5.13 includes LibRaw and legacy fallback; darktable uses RawSpeed and LibRaw fallback. References are not ground truth.',
          'core_algorithm_changed':False,'scope_status':'Proposed', 'gpu':'darktable opencl=false; ours/RT CPU pipelines'}
    for name,exe in binaries().items():
        folder=RUN/'environment'/name
        flag='--version' if name=='darktable' else '-h' if name=='rawtherapee' else None
        result=process([exe]+([flag] if flag else []),folder,30)
        text=(RUN/result['stdout_path']).read_text(errors='replace')+(RUN/result['stderr_path']).read_text(errors='replace')
        # Hash DLL/assets too: an unchanged EXE alone does not freeze the converter.
        parent=exe.parent
        if name=='ours': deps={}
        else:
            parent = parent.parent if name=='darktable' else parent
            deps={str(f.relative_to(parent)):sha(f) for f in sorted(parent.rglob('*')) if f.is_file()}
        lock['engines'][name]={'path':str(exe),'sha256':sha(exe),'actual_version_output':text,
                               'dependency_hashes':deps,'dependency_digest':digest(deps),
                               'version_process':result,'base_profile_sha256':sha(p) if name=='rawtherapee' else None}
        if name=='darktable': process([exe,'--help'],RUN/'environment/darktable-help',30)
    import numpy, tifffile, imagecodecs, PIL, psutil
    lock['python']={'executable':sys.executable,'version':sys.version,
                    'dependencies':{m.__name__:m.__version__ for m in (numpy,tifffile,imagecodecs,PIL,psutil)}}
    deps_files={str(f.relative_to(BASE/'python-deps')):sha(f) for f in sorted((BASE/'python-deps').rglob('*')) if f.is_file() and f.suffix not in ('.pyc',)}
    lock['python']['project_local_dependency_digest']=digest(deps_files)
    lock['python']['project_local_dependency_hashes']=deps_files
    dll=ROOT/'artifacts/engine-improvements/20261001/reference-lcms/lcms2.dll'
    lock['lcms']={'path':str(dll),'sha256':sha(dll),'version':2170,
                  'provenance':str(dll.parent/'provenance.json')}
    path=RUN/'engines.lock.json'
    if path.exists():
        old=load(path)
        # A repeated doctor is read-only for an unchanged semantic lock. Preserve
        # original measurement timestamps and the holdout's engine-lock hash.
        def signature(value):
            return {'engines':{k:{f:v.get(f) for f in ('path','sha256','dependency_digest','base_profile_sha256')} for k,v in value['engines'].items()},
                    'python':{k:v for k,v in value['python'].items() if k!='project_local_dependency_hashes'},
                    'lcms':value['lcms']}
        if signature(old)==signature(lock): return old
    write(path,lock)
    return lock

import sys
