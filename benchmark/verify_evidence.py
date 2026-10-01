"""Post-run artifact checks, independent of render adapter success statuses."""
import json
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
import numpy as np
from raw_benchmark.common import *
import tifffile
from raw_benchmark.imaging import CMS
from raw_benchmark.adapters import output_cache_valid
from benchmark.archive_history import reconstructed
from benchmark.profile_contracts import darktable_srgb_expected, color_tags

class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ('href','src') and value: self.links.append(value)

def verify():
    rows=[]; results=load(RUN/'render-results.json'); manifest=load(RUN/'corpus.manifest.json')
    lock=load(RUN/'engines.lock.json')
    actual_deps={str(p.relative_to(BASE/'python-deps')):sha(p)
                 for p in sorted((BASE/'python-deps').rglob('*')) if p.is_file() and p.suffix!='.pyc'}
    rows.append({'check':'Project-local normalizer dependency bytes match saved lock',
                 'status':'PASS' if digest(actual_deps)==lock['python']['project_local_dependency_digest'] else 'FAIL'})
    import PIL,imagecodecs,psutil
    versions={m.__name__:m.__version__ for m in (np,tifffile,imagecodecs,PIL,psutil)}
    rows.append({'check':'Loaded Python dependency versions match saved lock',
                 'status':'PASS' if versions==lock['python']['dependencies'] else 'FAIL','actual_versions':versions,
                 'global_package_scope':'NumPy/Pillow versions recorded; project-local dependency files hashed.'})
    assert len(results)==120 and len(manifest['items'])==40
    assert len({v['publisher_sha256'] for v in manifest['items']})==40
    groups={}
    for v in manifest['items']:
        groups.setdefault(v['scene_session_group'],set()).add(v['split'])
        if v['acquisition_status']=='SUCCESS':
            rows.append({'check':'RAW digest/bytes/license','source':v['source_id'],
                'status':'PASS' if sha(RUN/v['path'])==v['publisher_sha256']==v['sha256'] and (RUN/v['path']).stat().st_size==v['bytes'] and 'publicdomain/zero/1.0' in v['license_evidence'] else 'FAIL'})
    assert all(len(split)==1 for split in groups.values())
    selection=load(RUN/'selection.lock.json')
    selection_digest=digest([{k:v[k] for k in ('source_id','publisher_sha256','split','scene_session_group','pilot')}
                             for v in manifest['items']])
    rows.append({'check':'Selected source identities and split did not drift',
                 'status':'PASS' if selection_digest==selection['immutable_selection_digest'] else 'FAIL'})
    c=CMS(); patches=np.random.default_rng(18).random((1,4096,3),dtype=np.float32)
    dt_expected=darktable_srgb_expected(c)
    expected_rt=next((BASE/'tools/rawtherapee-5.13').rglob('RTv4_sRGB.icc')); rt_hash=sha(expected_rt)
    for r in results:
        if not output_eligible(r): continue
        d=r['descriptor']; icc=RUN/'profiles'/f"{d['icc_sha256']}.icc"
        assert sha(icc)==d['icc_sha256']
        converted=c.transform(patches,icc.read_bytes())
        deviation=float(np.max(np.abs(converted-patches)))
        if r['engine_id']=='rawtherapee':
            agrees=d['icc_sha256']==rt_hash
            contract='byte-exact official bundled RTv4_sRGB ICC'
        elif r['engine_id']=='darktable':
            agrees=color_tags(icc.read_bytes())==color_tags(dt_expected)
            contract='eight color tag payloads byte-exact to independently reconstructed pinned release sRGB v2.4 profile'
        else:
            agrees=deviation<.0003
            contract='4096 random RGB patches functional agreement within 0.0003; custom production ICC rounding'
        rows.append({'check':'Actual embedded ICC agrees with configured sRGB interpretation',
            'source':r['source_id'],'engine':r['engine_id'],'status':'PASS' if agrees else 'FAIL',
            'verified_contract':contract,
            'srgb_functional_max_error_4096_RGB_patches':deviation,
            'functional_tolerance_for_ours':.0003 if r['engine_id']=='ours' else None,
            'DT_color_tags_exact':agrees if r['engine_id']=='darktable' else None})
        norm=RUN/r['normalized_export']['path']
        pixels=tifffile.imread(norm)
        same_pixels=hashlib.sha256(pixels.tobytes()).hexdigest()==d['normalized_pixel_sha256']
        rows.append({'check':'Normalized FP32 pixels / finite / hash','source':r['source_id'],'engine':r['engine_id'],
            'status':'PASS' if pixels.dtype==np.float32 and np.isfinite(pixels).all() and same_pixels and sha(norm)==r['normalized_export']['sha256'] else 'FAIL'})
        del pixels
        assert {'source','engine','dependencies','profile','target_profile','adapter_normalizer_metrics','python_dependencies','lcms'}.issubset(r['cache_inputs'])
        changed_results=[]
        for key in r['cache_inputs']:
            changed=dict(r['cache_inputs']); changed[key]='synthetic changed content hash'
            changed_results.append(not output_cache_valid(r,digest(changed)))
        accepted=output_cache_valid(r,r['cache_key'])
        rows.append({'check':'Actual cached record rejects changed content keys','source':r['source_id'],'engine':r['engine_id'],
                     'status':'PASS' if all(changed_results) and accepted else 'FAIL',
                     'fields':list(r['cache_inputs']),'unchanged_positive_record_accepted':accepted})
    import copy
    from shutil import copyfile
    positive=next(r for r in results if output_eligible(r) and r['engine_id']=='ours')
    temp=RUN/'selftest/same-filename-settings.json'
    copyfile(RUN/positive['settings_path'],temp)
    local=copy.deepcopy(positive); local['settings_path']=rel(temp)
    original_accepted=output_cache_valid(local,local['cache_key'])
    temp.write_bytes(temp.read_bytes()+b'\n ')
    changed_rejected=not output_cache_valid(local,local['cache_key'])
    rows.append({'check':'Changed actual settings bytes under same filename invalidate cached record',
                 'status':'PASS' if original_accepted and changed_rejected else 'FAIL',
                 'original_accepted':original_accepted,'changed_rejected':changed_rejected,
                 'scope':'Own copied test settings; no source RAW, original settings or native exports edited.'})
    missing=[]; external=[]; html_count=0
    for path in RUN.rglob('*.html'):
        parser=Links(); parser.feed(path.read_text(encoding='utf-8')); html_count+=1
        for target in parser.links:
            u=urlsplit(target)
            if u.scheme or u.netloc: external.append((rel(path),target)); continue
            dest=(path.parent/unquote(u.path)).resolve()
            try: dest.relative_to(RUN.resolve())
            except ValueError: missing.append((rel(path),target,'outside run root')); continue
            if not dest.is_file(): missing.append((rel(path),target,'missing'))
    rows.append({'check':'Offline HTML relative links, all planned source pages',
                 'status':'PASS' if not missing and not external and html_count==42 else 'FAIL',
                 'html_pages':html_count,'missing':missing,'external_assets':external})
    summary=load(RUN/'summary.json')
    counts={s:sum(r['execution']['status']==s for r in results) for s in {r['execution']['status'] for r in results}}
    rows.append({'check':'Dashboard counters vs planned 120 rows','status':'PASS' if summary['execution_counts']==counts else 'FAIL',
                 'actual_counts':counts,'planned':len(results)})
    historical=list(RUN.rglob('*.history.json'))
    for path in historical:
        m=load(path)
        rows.append({'check':'Historical native container byte-exact reconstruction',
                     'manifest':rel(path),'status':'PASS' if reconstructed(m)==m['original_sha256'] else 'FAIL',
                     'original_sha256':m['original_sha256'],'original_bytes':m['original_bytes']})
    baseline=load(RUN/'baseline.json')
    rows.append({'check':'Engine source remains unchanged from saved baseline',
                 'status':'PASS' if all(sha(ROOT/p)==s for p,s in baseline['source_hashes'].items()) else 'FAIL'})
    freeze=load(RUN/'holdout.freeze.json')
    events=[json.loads(line) for line in (RUN/'execution-events.jsonl').read_text().splitlines()]
    holdout={v['source_id'] for v in manifest['items'] if v['split']=='holdout'}
    holdout_events=[e for e in events if e['source_id'] in holdout]
    holdout_starts=[]
    for r in results:
        if r['source_id'] not in holdout: continue
        started=r['execution'].get('started_at')
        if started: holdout_starts.append(started)
        elif r.get('job_id'):
            holdout_starts.extend(load(p)['started_at'] for p in (RUN/r['job_id']).rglob('process.json'))
    frozen_sources=all(sha(ROOT/'raw_benchmark'/p)==s for p,s in freeze['runner_source_hashes'].items())
    frozen_config=(sha(BASE/'benchmark.policy.json')==freeze['policy_sha256'] and
                   sha(RUN/'engines.lock.json')==freeze['engine_lock_sha256'] and
                   sha(RUN/'selection.lock.json')==freeze['selection_sha256'] and
                   sha(BASE/'configs/base.pp3')==freeze['base_pp3_sha256'] and
                   sha(RUN/'profiles/target-sRGB.icc')==freeze['target_srgb_sha256'])
    rows.append({'check':'Immutable settings/source freeze preceded holdout execution',
                 'status':'PASS' if frozen_sources and frozen_config and len(holdout_events)>=36 and
                     all(e['requested_at']>freeze['created_at'] for e in holdout_events) and
                     bool(holdout_starts) and all(t and t>freeze['created_at'] for t in holdout_starts) else 'FAIL',
                 'holdout_events':len(holdout_events),'freeze_time':freeze['created_at']})
    result={'created_at':now(),'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL','rows':rows,
            'scope':'artifact integrity and configured-color agreement, not physical scene accuracy or human image review'}
    write(RUN/'artifact-verification.json',result); print(json.dumps({'status':result['status'],'checks':len(rows),'missing':missing},indent=2))
    return result

if __name__=='__main__':
    if verify()['status']!='PASS': raise SystemExit(1)
