"""Lossless storage for historical native exports, with byte-exact restoration.

Current latest exports remain ordinary TIFF/ZIP files. Old containers whose data
payload matches a retained current export store original metadata inline and
reference its identical byte range. This is storage deduplication, not image
conversion. Every archived file is reconstructed into a hash before unlinking it.
"""
import base64
import struct
import zipfile
from raw_benchmark.common import *
import tifffile

def ranges(path):
    size=path.stat().st_size
    if path.suffix=='.tif':
        with tifffile.TiffFile(path) as t:
            page=t.pages[0]
            start=min(page.dataoffsets); end=max(o+n for o,n in zip(page.dataoffsets,page.databytecounts))
        return [(start,end-start)]
    if path.suffix=='.zip':
        result=[]
        with zipfile.ZipFile(path) as z, path.open('rb') as f:
            for item in z.infolist():
                f.seek(item.header_offset); header=f.read(30)
                if header[:4]!=b'PK\x03\x04': raise ValueError('unknown ZIP local header')
                name,extra=struct.unpack_from('<HH',header,26)
                result.append((item.header_offset+30+name+extra,item.compress_size))
        return sorted(result)
    raise ValueError('only generated TIFF/ZIP containers')

def range_sha(path,start,count):
    h=hashlib.sha256()
    with path.open('rb') as f:
        f.seek(start)
        while count:
            block=f.read(min(count,1024*1024))
            if not block: raise ValueError('truncated byte range')
            h.update(block); count-=len(block)
    return h.hexdigest()

def reconstructed(manifest,output=None):
    h=hashlib.sha256(); written=0
    handle=Path(output).open('wb') if output else None
    try:
        for segment in manifest['segments']:
            if 'inline_base64' in segment:
                data=base64.b64decode(segment['inline_base64']); h.update(data); written+=len(data)
                if handle: handle.write(data)
            else:
                source=(RUN/segment['reference_path']).resolve(); source.relative_to(RUN.resolve())
                with source.open('rb') as f:
                    f.seek(segment['offset']); remaining=segment['bytes']; check=hashlib.sha256()
                    while remaining:
                        data=f.read(min(remaining,1024*1024))
                        if not data: raise ValueError('truncated canonical export')
                        check.update(data); h.update(data); written+=len(data); remaining-=len(data)
                        if handle: handle.write(data)
                if check.hexdigest()!=segment['range_sha256']: raise ValueError('canonical payload changed; refusing historical restoration')
        if written!=manifest['original_bytes'] or h.hexdigest()!=manifest['original_sha256']:
            raise ValueError('byte-exact reconstruction hash/size mismatch')
    finally:
        if handle: handle.close()
    return h.hexdigest()

def archive_one(path,index):
    original_sha=sha(path); original_bytes=path.stat().st_size
    segments=[]; offset=0; matched=0
    with path.open('rb') as f:
        for start,count in ranges(path):
            key=(count,range_sha(path,start,count))
            if start<offset: raise ValueError('overlapping storage ranges')
            if start>offset:
                f.seek(offset); segments.append({'inline_base64':base64.b64encode(f.read(start-offset)).decode()})
            if key in index:
                ref,ref_offset=index[key]
                segments.append({'reference_path':rel(ref),'offset':ref_offset,'bytes':count,'range_sha256':key[1]})
                matched+=count
            else:
                if count>16*1024*1024: return None
                f.seek(start); segments.append({'inline_base64':base64.b64encode(f.read(count)).decode()})
            offset=start+count
        if offset<original_bytes:
            f.seek(offset); segments.append({'inline_base64':base64.b64encode(f.read()).decode()})
    if matched<.90*original_bytes: return None
    manifest={'created_at':now(),'storage_version':1,'original_path':rel(path),
        'original_sha256':original_sha,'original_bytes':original_bytes,
        'representation':'Original metadata bytes plus byte-identical retained compressed payload; no decode/reencode/lossy change',
        'segments':segments}
    reconstructed(manifest)
    out=path.with_name(path.name+'.history.json'); write(out,manifest)
    # Resolve the final absolute path and require this own generated run directory.
    path.resolve().relative_to(RUN.resolve())
    if not path.parts[-1].endswith(('.tif','.zip')): raise ValueError('RAW originals never archived by this tool')
    path.unlink()
    return {'original_path':rel(path),'original_sha256':original_sha,'manifest_path':rel(out),
            'manifest_sha256':sha(out),'bytes_saved':original_bytes-out.stat().st_size}

def archive():
    latest=[load(p) for p in RUN.rglob('latest.json')]
    protected={r['job_id'] for r in latest if r.get('normalized_export')}
    dependencies=set()
    for p in RUN.rglob('*.history.json'):
        for segment in load(p)['segments']:
            if 'reference_path' in segment: dependencies.add(segment['reference_path'])
    canonical=[]
    for r in latest:
        if not r.get('normalized_export'): continue
        folder=RUN/r['job_id']
        for name in ('native.tif','native-f32.zip','default-native.tif'):
            p=folder/name
            if p.exists(): canonical.append(p)
    index={}
    for path in canonical:
        for start,count in ranges(path):
            index.setdefault((count,range_sha(path,start,count)),(path,start))
    old=load(RUN/'historical-storage.json') if (RUN/'historical-storage.json').exists() else {'events':[]}
    events=[]
    for record_path in sorted(RUN.rglob('result.json')):
        r=load(record_path)
        if not r.get('normalized_export') or r['job_id'] in protected: continue
        folder=record_path.parent; archived=[]
        for name in ('native.tif','native-f32.zip','default-native.tif'):
            p=folder/name
            if not p.exists() or rel(p) in dependencies: continue
            event=archive_one(p,index)
            if event: archived.append(event); events.append(event)
        if archived:
            r['historical_native_storage']=r.get('historical_native_storage',[])+archived
            r['native_restoration_command']='python -m benchmark.archive_history restore --manifest <path-to-history.json>'
            write(record_path,r)
    result={'created_at':now(),'method':'Byte-exact historical native container reconstruction; current latest exports remain materialized',
            'raw_originals_touched':False,'lossy_changes':False,'events':old['events']+events,
            'new_bytes_saved':sum(e['bytes_saved'] for e in events),'unique_run_bytes':budget()}
    write(RUN/'historical-storage.json',result)
    print({k:v for k,v in result.items() if k!='events'})
    return result

def main():
    import argparse
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('archive')
    r=sub.add_parser('restore'); r.add_argument('--manifest',required=True)
    a=p.parse_args()
    if a.action=='archive': archive(); return
    manifest_path=Path(a.manifest).resolve(); manifest_path.relative_to(RUN.resolve())
    m=load(manifest_path); out=(RUN/m['original_path']).resolve(); out.relative_to(RUN.resolve())
    if out.exists():
        if sha(out)!=m['original_sha256']: raise ValueError('refusing to overwrite different existing file')
        print('already restored',out); return
    budget(m['original_bytes'])
    temporary=out.with_name(out.name+'.restore-part'); reconstructed(m,temporary); temporary.replace(out)
    print('restored byte-exact',out,m['original_sha256'])

if __name__=='__main__': main()
