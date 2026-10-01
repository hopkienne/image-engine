from .common import *
import shutil
import sqlite3

def dt_argv(raw,output,folder,xmp=None,database=None):
    args=[binaries()['darktable'],raw]
    if xmp: args.append(xmp)
    args += [output,'--apply-custom-presets','false','--icc-type','SRGB','--icc-intent','RELATIVE_COLORIMETRIC','--verbose']
    if database: args += ['--library',database]
    args += ['--core','--configdir',folder/'config','--cachedir',folder/'cache','-t','4']
    for item in ('opencl=false','plugins/imageio/format/tiff/bpp=16','plugins/imageio/format/tiff/compress=1',
                 'plugins/imageio/format/tiff/compresslevel=6','plugins/imageio/format/tiff/shortfile=0',
                 'plugins/darkroom/workflow=display-referred','write_sidecar_files=always'):
        args += ['--conf',item]
    # darktable expands backslash escapes in export paths even with argv execution.
    return [v.as_posix() if isinstance(v,Path) else str(v) for v in args]

def run_smoke():
    for name,exe in binaries().items():
        folder=RUN/'smoke'/name; folder.mkdir(parents=True,exist_ok=True)
        raw=folder/'input.NEF'
        original=ROOT/'fixtures/raw/D7000_compressed_12bit_NIK_3876.NEF'
        shutil.copyfile(original,raw)
        if name=='ours':
            recipe=folder/'recipe.json'; look=ROOT/'fixtures/looks/identity-technical-fixture'
            init=process([exe,'init-recipe',raw,'--look',look,'--amount','0','--out',recipe],folder/'init')
            args=[exe,'render',raw,'--recipe',recipe,'--look',look,'--out',folder/'output.jpg',
                  '--report',folder/'engine-report.json','--diagnostic-pixels',folder/'native']
        elif name=='rawtherapee':
            args=[exe,'-O',folder/'native.tif','-p',CONFIG/'base.pp3','-tz','-b16','-c',raw]
        else:
            args=dt_argv(raw,folder/'native.tif',folder,database=folder/'library.db')
        result=process(args,folder/'render')
        print(name,result['status'],round(result['wall_seconds'],3),flush=True)
        write(folder/'source.json',{'original_sha256':sha(original),'working_sha256_after':sha(raw),
                                   'same_bytes':sha(original)==sha(raw)})
        if name=='darktable' and (folder/'library.db').exists():
            db=sqlite3.connect(folder/'library.db')
            rows=db.execute('select * from history').fetchall()
            cols=[v[0] for v in db.execute('select * from history').description]
            write(folder/'history.json',[{k:(v.hex() if isinstance(v,bytes) else v) for k,v in zip(cols,row)} for row in rows])
            db.close()

if __name__=='__main__': run_smoke()
