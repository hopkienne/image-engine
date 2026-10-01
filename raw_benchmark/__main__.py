import argparse
import platform
import sys
import statistics
import tifffile
import numpy as np
from .common import *
from . import corpus, setup, selftest
from .adapters import render, output_cache_valid
from .imaging import CMS, pair, triage, effect, linear
from .report import generate

def doctor():
    lock=setup.prepare(); CMS()
    host={'created_at':now(),'platform':platform.platform(),'python':sys.version,
          'cpu_logical':psutil.cpu_count(),'cpu_physical':psutil.cpu_count(logical=False),
          'memory_total_bytes':psutil.virtual_memory().total,'memory_available_bytes':psutil.virtual_memory().available,
          'G_free_bytes':shutil.disk_usage(ROOT).free,'thread_budget':4,'render_concurrency':1,'download_concurrency':1,
          'git_state':'No Git repository found; baseline source hashes and archive are the provenance',
          'C_drive_free_bytes':shutil.disk_usage('C:/').free,
          'installed_reference_versions':['darktable 5.6.1','RawTherapee 5.13'],
          'security':'darktable installed CURRENTUSER on G, no administrator privileges; RT and dependency packages project-local',
          'limitations':['Other desktop apps remained open; wall time/working set are observations on this host.',
                         'darktable reports missing optional liblut3d dependency; LUT module disabled in BASE.',
                         'GPU off via darktable opencl=false; ours and RT CPU paths.',
                         'Windows installer changed its own HKCU installation/environment entries; no user presets accessed.']}
    cpu=subprocess.run(['powershell','-NoProfile','-Command','Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json'],capture_output=True,text=True,timeout=30)
    try: host['cpu']=json.loads(cpu.stdout)
    except ValueError: host['cpu']=cpu.stdout
    write(RUN/'environment.json',host)
    manifest=corpus.plan(); tests=selftest.run()
    write(RUN/'doctor.json',{'status':'PASS' if tests['status']=='PASS' else 'INVALID','environment':'environment.json',
           'engines':'engines.lock.json','policy_sha256':sha(BASE/'benchmark.policy.json'),'planned_raws':len(manifest['items'])})
    print(json.dumps({'doctor':tests['status'],'versions':host['installed_reference_versions'],'G_free_GiB':host['G_free_bytes']/2**30}),flush=True)

def probe(item):
    folder=RUN/'probes'/item['source_id']
    r=process([binaries()['ours'],'probe',RUN/item['path'],'--json'],folder,60)
    if r['status']!='SUCCESS':
        item['probe_status']=r['status']; return item
    try:
        info=json.loads((RUN/r['stdout_path']).read_text())
        write(folder/'probe.json',info)
        item['probe_status']='SUCCESS'; item['probe_evidence']=rel(folder/'probe.json')
        # Field names vary by C ABI version; keep complete factual probe in evidence.
        item['verified_metadata']={k:info.get(k) for k in ('camera','dimensions','format','orientation','levels','whiteBalance')}
        fmt=info.get('format',{})
        filters=fmt.get('filters')
        item['cfa']='X-Trans' if filters==9 else 'Bayer' if isinstance(filters,int) and filters>0 else 'UNKNOWN'
        dims=info.get('dimensions',{})
        w=dims.get('raw_width',dims.get('rawWidth',0)); h=dims.get('raw_height',dims.get('rawHeight',0))
        if w and h and w*h/1e6>120: raise ValueError('actual RAW exceeds 120 MP cap')
        item['metadata_origin']='actual LibRaw probe; unsupported/unknown not inferred from filename'
    except Exception as exc:
        item['probe_status']='BLOCKED'; item['reason']=str(exc)
    return item

def compare(item,results):
    sid=item['source_id']; images={}; pairs=[]
    for r in results:
        if output_eligible(r): images[r['engine_id']]=tifffile.imread(RUN/r['normalized_export']['path'])
    for a,b in [('ours','darktable'),('ours','rawtherapee'),('darktable','rawtherapee')]:
        if a not in images or b not in images:
            result={'status':'PARTIAL_REFERENCE','reason':'missing/failed engine output; no fake metrics'}
        else:
            folder=RUN/'pairs'/sid/f'{a}-{b}'; folder.mkdir(parents=True,exist_ok=True)
            result=pair(images[a],images[b],folder)
        pairs.append(dict(result,pair=f'{a}-{b}'))
    anomaly=any(r.get('metrics',{}).get('technical_anomaly',False) for r in results if r['engine_id']=='ours')
    result={'source_id':sid,'pairs':pairs,'triage':triage(pairs[:2],anomaly)}
    del images
    return result

def config_effect(item):
    results=[]
    for engine in ('ours','darktable','rawtherapee'):
        base=load(RUN/'jobs'/item['source_id']/engine/'latest.json')
        changed=render(item,engine,False,perturb=True)
        if not output_eligible(base) or not output_eligible(changed):
            results.append({'engine':engine,'status':'BLOCKED','reason':'missing valid before/after outputs','perturbed_job':changed}); continue
        a=tifffile.imread(RUN/base['normalized_export']['path']); b=tifffile.imread(RUN/changed['normalized_export']['path'])
        delta=float(np.max(np.abs(a-b))); passed=effect(a,b)
        results.append({'engine':engine,'status':'PASS' if passed else 'FAIL','baseline_job':base['job_id'],
                        'perturbed_job':changed['job_id'],'max_encoded_RGB_response':delta,
                        'perturbation':'WB red gain *1.25 in generated source-verified temperature v4 XMP' if engine=='darktable' else 'exposure +1 EV in explicit recipe/PP3',
                        'expected':'measurable response, not final-display RGB exactly doubled',
                        'baseline_settings_sha256':base['settings_sha256'],'perturbed_settings_sha256':changed['settings_sha256']})
        del a,b
    result={'status':'PASS' if all(r['status']=='PASS' for r in results) else 'BLOCKED','source_id':item['source_id'],'rows':results,'core_algorithm_changed':False}
    write(RUN/'config-effects.json',result)
    print('config-effect',result['status'],[(r['engine'],r['status']) for r in results],flush=True)
    return result

def repeatability(items,resume):
    fixtures=[item for item in items if item['pilot']][:3]; rows=[]
    for item in fixtures:
        for engine in ('ours','darktable','rawtherapee'):
            runs=[render(item,engine,resume,repeat=i) for i in range(1,4)]
            success=all(output_eligible(r) for r in runs)
            max_delta=None; identical=None
            if success:
                hashes=[r['descriptor']['native_pixel_sha256'] for r in runs]
                identical=len(set(hashes))==1
                a=tifffile.imread(RUN/runs[0]['normalized_export']['path']); max_delta=0.
                for r in runs[1:]:
                    b=tifffile.imread(RUN/r['normalized_export']['path'])
                    if a.shape!=b.shape: max_delta=1.; break
                    max_delta=max(max_delta,float(np.max(np.abs(a-b)))); del b
                del a
            # Same-engine repeatability tolerance frozen before repeats; one 16-bit code for references.
            tolerance=1e-6 if engine=='ours' else 1/65535
            durations=[r['execution'].get('original_render_wall_seconds',r['execution'].get('wall_seconds')) for r in runs if r['execution']['status']=='SUCCESS']
            times=[v for v in durations if v is not None]
            row={'source_id':item['source_id'],'engine':engine,'status':'PASS' if success and max_delta<=tolerance else 'FAIL' if success else 'BLOCKED',
                 'n':len(runs),'fresh_process_runs':3,'cold_os_cache':False,'same_engine_tolerance':tolerance,
                 'native_pixels_exactly_identical':identical,'max_normalized_float_delta':max_delta,
                 'wall_seconds_samples':times,'median_seconds':statistics.median(times) if times else None,
                 'range_seconds':[min(times),max(times)] if times else None,
                 'sampled_peak_working_set_bytes':[r['execution'].get('peak_memory_bytes') for r in runs],
                 'jobs':[r['job_id'] for r in runs],'cache_hits':[r['execution']['cache_hit'] for r in runs],
                 'performance_limitation':'fresh process != cold OS cache; n=3 has no p95; darktable history-generation pass recorded separately; no equivalent-work ranking'}
            rows.append(row); write(RUN/'repeatability.json',{'status':'PARTIAL','rows':rows})
            print('repeat',item['source_id'],engine,row['status'],row['median_seconds'],flush=True)
    result={'created_at':now(),'status':'PASS' if len(rows)==9 and all(r['status']=='PASS' for r in rows) else 'BLOCKED','rows':rows}
    write(RUN/'repeatability.json',result); return result

def freeze(manifest):
    data={'created_at':now(),'policy_sha256':sha(BASE/'benchmark.policy.json'),'engine_lock_sha256':sha(RUN/'engines.lock.json'),
          'selection_sha256':sha(RUN/'selection.lock.json'),'runner_source_hashes':{p.name:sha(p) for p in (ROOT/'raw_benchmark').glob('*.py') if p.name!='report.py'},
          'base_pp3_sha256':sha(CONFIG/'base.pp3'),'target_srgb_sha256':sha(RUN/'profiles/target-sRGB.icc'),
          'same_engine_repeatability_tolerance':{'ours':1e-6,'references':1/65535},
          'geometry_method':'native 3-patch integer displacement agreement and edge correlation >=0.80; otherwise NOT_COMPARABLE',
          'triage':'Policy exploratory only; immutable corpus selection; no core edits'}
    path=RUN/'holdout.freeze.json'
    if path.exists():
        previous=load(path)
        if {k:v for k,v in previous.items() if k!='created_at'}!={k:v for k,v in data.items() if k!='created_at'}:
            raise RuntimeError('BLOCKED: policy/config/engine/source drift after holdout freeze; preserve previous run')
    else: write(path,data)

def run(stage,resume):
    if not (RUN/'doctor.json').exists(): doctor()
    if load(RUN/'harness-tests.json')['status']!='PASS': raise RuntimeError('INVALID harness self-tests')
    # Actual installed dependencies are rehashed before any resume reuse, not
    # inferred from an old EXE filename or stale lock.
    lock=load(RUN/'engines.lock.json')
    dependency_checks=[]
    for engine,entry in lock['engines'].items():
        exe=Path(entry['path']); parent=exe.parent.parent if engine=='darktable' else exe.parent
        actual={str(p.relative_to(parent)):sha(p) for p in sorted(parent.rglob('*')) if p.is_file()} if engine!='ours' else {}
        ok=sha(exe)==entry['sha256'] and actual==entry['dependency_hashes']
        dependency_checks.append({'engine':engine,'status':'PASS' if ok else 'BLOCKED','actual_dependency_digest':digest(actual)})
    write(RUN/'dependency-verification.json',{'checked_at':now(),'rows':dependency_checks})
    if any(v['status']!='PASS' for v in dependency_checks): raise RuntimeError('BLOCKED: installed engine/dependency drift; regenerate a separate baseline before reuse')
    manifest=corpus.plan()
    if stage=='standard':
        if not (RUN/'pilot-summary.json').exists() or not load(RUN/'pilot-summary.json').get('pilot_valid',False):
            raise RuntimeError('BLOCKED: valid pilot required before standard')
        freeze(manifest)
    active=[v for v in manifest['items'] if v['pilot']] if stage=='pilot' else manifest['items']
    # Development first; HOLDOUT is unopened until the above immutable freeze is saved.
    active.sort(key=lambda v:(v['split']=='holdout',int(v['source_id'][1:])))
    comparisons=load(RUN/'comparisons.json') if (RUN/'comparisons.json').exists() else {}
    for selected in active:
        try: item=corpus.acquire(selected)
        except (RuntimeError,OSError) as exc:
            item=dict(selected,acquisition_status='BLOCKED',reason=str(exc))
            manifest['items']=[item if v['source_id']==item['source_id'] else v for v in manifest['items']]
            write(RUN/'corpus.manifest.json',manifest)
            write(RUN/'stage-blocked.json',{'at':now(),'stage':stage,'source_id':item['source_id'],'reason':str(exc)})
            print('BLOCKED acquisition/resource',str(exc),flush=True)
            return generate(stage)
        if item['acquisition_status']=='SUCCESS': item=probe(item)
        manifest['items']=[item if v['source_id']==item['source_id'] else v for v in manifest['items']]
        write(RUN/'corpus.manifest.json',manifest)
        print('source',item['source_id'],item['model'],item['acquisition_status'],flush=True)
        results=[]
        if item['acquisition_status']=='SUCCESS' and item.get('probe_status')!='BLOCKED':
            for engine in ('ours','darktable','rawtherapee'):
                try: r=render(item,engine,resume)
                except (RuntimeError,OSError) as exc:
                    folder=RUN/'jobs'/item['source_id']/engine/f'resource-block-{time.time_ns()}'
                    folder.mkdir(parents=True,exist_ok=True)
                    r={'job_id':rel(folder),'source_id':item['source_id'],'engine_id':engine,'mode':'BASE_CONTROLLED',
                       'source_sha256':item['sha256'],'execution':{'status':'BLOCKED','wall_seconds':None,'peak_memory_bytes':None,'cache_hit':False},
                       'reason':str(exc),'technical_checks':[{'name':'resource preflight','status':'BLOCKED','reason':str(exc)}],
                       'quality_triage':'NOT_EVALUATED','review_status':'NOT_REVIEWED','comparison_eligibility':'NOT_COMPARABLE'}
                    write(folder/'result.json',r); write(folder.parent/'latest.json',r)
                    write(RUN/'stage-blocked.json',{'at':now(),'stage':stage,'source_id':item['source_id'],'engine':engine,'reason':str(exc)})
                    print('BLOCKED render/resource',str(exc),flush=True)
                    return generate(stage)
                results.append(r)
                with (RUN/'execution-events.jsonl').open('a',encoding='utf-8') as ledger:
                    ledger.write(json.dumps({'requested_at':now(),'stage':stage,'source_id':item['source_id'],
                        'engine':engine,'job_id':r['job_id'],'cache_hit':r['execution']['cache_hit'],
                        'render_wall_seconds_this_invocation':r['execution'].get('wall_seconds'),
                        'execution_status':r['execution']['status']})+'\n')
                print('render',item['source_id'],engine,r['execution']['status'],r.get('reason',''),
                      'cache' if r['execution']['cache_hit'] else round(r['execution'].get('wall_seconds') or 0,3),flush=True)
            comparisons[item['source_id']]=compare(item,results)
            write(RUN/'comparisons.json',comparisons)
            print('geometry',item['source_id'],[p['status'] for p in comparisons[item['source_id']]['pairs']],flush=True)
        # Make useful, truthful partial report after every scene, including failures.
        generate(stage)
    if stage=='pilot':
        # Acquisition replaces manifest entries. Never repeat using the initial
        # plan objects, whose sha256/bytes can still be null on a first run.
        active=[v for v in manifest['items'] if v['pilot']]
        valid=all((RUN/'jobs'/v['source_id']/engine/'latest.json').exists() and output_eligible(load(RUN/'jobs'/v['source_id']/engine/'latest.json')) for v in active for engine in ('ours','darktable','rawtherapee'))
        if valid:
            from benchmark.compact_outputs import compact
            compact()
            if not (RUN/'config-effects.json').exists(): config_effect(active[0])
            repeatability(active,resume)
            compact()
        summary=generate(stage)
        summary['pilot_valid']=valid and load(RUN/'config-effects.json')['status']=='PASS' and load(RUN/'repeatability.json')['status']=='PASS'
        write(RUN/'pilot-summary.json',summary)
    else: summary=generate(stage)
    print(json.dumps(summary,indent=2),flush=True)

def main():
    parser=argparse.ArgumentParser(description='Evidence-first RAW multi-engine benchmark')
    sub=parser.add_subparsers(dest='command',required=True)
    d=sub.add_parser('doctor'); d.add_argument('--policy',default='benchmark/benchmark.policy.json')
    r=sub.add_parser('run'); r.add_argument('--policy',default='benchmark/benchmark.policy.json'); r.add_argument('--stage',choices=['pilot','standard'],required=True); r.add_argument('--resume',action='store_true')
    sub.add_parser('selftest'); h=sub.add_parser('report'); h.add_argument('--stage',default='standard')
    args=parser.parse_args()
    if hasattr(args,'policy') and Path(args.policy).resolve()!=(BASE/'benchmark.policy.json').resolve():
        raise SystemExit('This run is pinned to benchmark/benchmark.policy.json; make a separate run root for another policy.')
    if args.command=='doctor': doctor()
    elif args.command=='selftest': selftest.run()
    elif args.command=='report': print(generate(args.stage))
    else: run(args.stage,args.resume)

if __name__=='__main__': main()
