"""Deduplicate ONLY completed, byte-identical generated derivatives on NTFS.

No RAW hardlinks; no lossy recompression; record every replacement and verify both
content hashes afterward. Each record's paths/hashes remain valid. Do not edit any
linked derivative in place; render attempts always have new folders.
"""
import os
from raw_benchmark.common import *

def compact():
    sources={}; events=[]
    old=load(RUN/'storage-deduplication.json') if (RUN/'storage-deduplication.json').exists() else {'events':[]}
    # result.json is committed only AFTER export/normalization and hash checks.
    for result_path in sorted(RUN.rglob('result.json')):
        record=load(result_path)
        if not record.get('normalized_export') or not record.get('native_export'): continue
        files=[record['normalized_export']]
        files += [v.get('archive',v) for v in record['native_export']]
        for evidence in files:
            target=(RUN/evidence['path']).resolve()
            target.relative_to(RUN.resolve())
            if target.suffix.lower() not in ('.tif','.zip'): continue
            if not target.is_file() or sha(target)!=evidence['sha256']: continue
            key=(evidence['sha256'],target.stat().st_size)
            if key not in sources: sources[key]=target; continue
            canonical=sources[key]
            if os.path.samefile(target,canonical): continue
            # Resolve and bound both endpoints before any move/unlink on Windows.
            canonical.resolve().relative_to(RUN.resolve())
            temporary=target.with_name(target.name+'.dedupe-original')
            temporary.resolve().relative_to(RUN.resolve())
            if temporary.exists(): raise RuntimeError('unfinished earlier compaction; preserve files for inspection')
            target.rename(temporary)
            try:
                os.link(canonical,target)
                if sha(target)!=key[0] or sha(temporary)!=key[0]: raise ValueError('deduplication verification failed')
            except Exception:
                target.unlink(missing_ok=True); temporary.rename(target); raise
            temporary.unlink()
            events.append({'at':now(),'alias':rel(target),'canonical':rel(canonical),'sha256':key[0],
                           'bytes_saved':key[1],'method':'NTFS hardlink of completed byte-identical derivative; original RAW excluded'})
    all_files=[p for p in RUN.rglob('*') if p.is_file()]
    result={'created_at':now(),'raw_hardlinks':False,'lossy_changes':False,
            'events':old['events']+events,'logical_file_bytes':sum(p.stat().st_size for p in all_files),
            'unique_file_bytes':budget(),'new_bytes_saved':sum(v['bytes_saved'] for v in events),
            'rule':'Derived exports are immutable; verify hashes when reusing; never overwrite linked derivative paths.'}
    write(RUN/'storage-deduplication.json',result)
    print({k:v for k,v in result.items() if k!='events'})
    return result

if __name__=='__main__': compact()
