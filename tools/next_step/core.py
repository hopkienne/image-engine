"""Focused baseline regression, production/diagnostic timings, sessions, headroom."""
import argparse, json, os, shutil, subprocess, sys, time, zipfile, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
import numpy as np
import tifffile
from PIL import Image
from raw_benchmark import common
from raw_benchmark.common import load, write, sha
OLD=common.RUN
CLI=ROOT/'build-next/photo-cli.exe'; HARNESS=ROOT/'build-next/next_step_harness.exe'
LOOK=ROOT/'fixtures/looks/identity-technical-fixture'

def session(mode,source,look,recipe,out,commands):
    out.mkdir(parents=True,exist_ok=False)
    write(out/'commands.json',commands)
    env=os.environ.copy();env.update(OMP_NUM_THREADS='4',OMP_THREAD_LIMIT='4')
    start=time.perf_counter()
    with (out/'stdout.jsonl').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
        p=subprocess.Popen([str(HARNESS),mode,str(source),str(look),str(recipe),str(out)],stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,env=env)
        import psutil
        proc=psutil.Process(p.pid);proc.cpu_affinity(proc.cpu_affinity()[:4])
        p.communicate(('\n'.join(json.dumps(c) for c in commands)+'\n').encode(),timeout=600)
    write(out/'process.json',{'exit_code':p.returncode,'wall_seconds':time.perf_counter()-start,'thread_budget':4,'affinity':'first four allowed processors','cold_os_cache':False,'same_process_commands':len(commands),'exe_sha256':sha(HARNESS)})
    assert p.returncode==0,(out,p.returncode)
    rows=[json.loads(s) for s in (out/'stdout.jsonl').read_text().splitlines()]
    assert len(rows)==len(commands)
    for ppm in out.glob('*.ppm'):Image.open(ppm).save(ppm.with_suffix('.png'))
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--section',choices=['all','regression','preview','headroom'],default='all');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);common.RUN=out
    items={i['source_id']:i for i in load(OLD/'corpus.manifest.json')['items']}
    # Frozen before any new experiment. Pixel equality is exact, with a separate
    # locked cross-build tolerance 1e-7 to report tiny compiler effects honestly.
    policy={'created_before_experiment':True,'prejpeg_max_abs_tolerance':1e-7,'preview_cache_vs_uncached_max_abs':0,
      'orientation_equal':True,'alpha_exact':1,'recipe_replay_pixel_hash_equal':True,
      'roi_coordinates':'native oriented full-resolution XYWH, selected from run-v1 overviews',
      'rois':{'R007':{'highlight':[700,650,512,512],'midtone':[700,1800,512,512],'control':[50,2350,512,512]},
              'R020':{'highlight':[64,64,512,512],'midtone':[2400,850,512,512],'control':[700,1500,512,512]},
              'R001':{'highlight':[1800,200,512,512],'midtone':[1900,1200,512,512],'control':[400,2000,512,512]}}}
    policy_path=out/'locked-test-policy.json'
    if policy_path.exists():assert load(policy_path)==policy
    else:write(policy_path,policy)
    write(out/'opened-fixtures.json',[{'id':sid,'previous_split':items[sid]['split'],'now':'opened; regression, not confirmation holdout'} for sid in ['R025','R039','R001','R004','R007','R020','R011']])
    recipes=out/'recipes';recipes.mkdir(exist_ok=True)
    for sid in ['R025','R039','R001','R004','R007','R020']:
        old=load(OLD/f'jobs/{sid}/ours/latest.json')
        if not (recipes/f'{sid}.json').exists():shutil.copyfile(OLD/old['settings_path'],recipes/f'{sid}.json')
        assert sha(OLD/items[sid]['path'])==items[sid]['sha256']
    if a.section in ['all','regression']:
        regression=[]
        for sid in ['R025','R039','R001','R004','R007','R020']:
            source=OLD/items[sid]['path'];folder=out/'regression'/sid;folder.mkdir(parents=True,exist_ok=False)
            exe=common.process([CLI,'render',source,'--recipe',recipes/f'{sid}.json','--look',LOOK,'--out',folder/'output.jpg','--report',folder/'report.json','--diagnostic-pixels',folder/'pixels'],folder/'process')
            assert exe['status']=='SUCCESS'
            old=load(OLD/f'jobs/{sid}/ours/latest.json');oldfolder=OLD/old['job_id']
            with zipfile.ZipFile(oldfolder/'native-f32.zip') as z:previous=np.frombuffer(z.read('native.f32'),dtype='<f4')
            actual=np.fromfile(folder/'pixels.f32',dtype='<f4');diff=float(np.max(np.abs(actual-previous)))
            d=load(folder/'pixels.json');h,w=d['height'],d['width'];arr=actual.reshape(h,w,3)
            x,y=w//2-256,h//2-256
            for name,buf in [('before',previous.reshape(h,w,3)),('after',arr)]:
                Image.fromarray(np.rint(np.clip(buf[y:y+512,x:x+512],0,1)*255).astype('uint8')).save(folder/f'{name}-crop.png')
            regression.append({'id':sid,'status':'VERIFIED' if diff<=1e-7 else 'FAILED','max_abs':diff,'exact':np.array_equal(previous,actual),'old_native_sha256':old['native_export'][0]['sha256'],'new_sha256':sha(folder/'pixels.f32'),'recipe_sha256':sha(recipes/f'{sid}.json'),'descriptor':d,'source_unchanged':sha(source)==items[sid]['sha256']})
            print('regression',sid,diff,flush=True)
        write(out/'regression.json',regression)
        # Probe succeeds while as-shot WB recipe resolution fails. No fallback.
        folder=out/'missing-wb';folder.mkdir(exist_ok=False);source=OLD/items['R011']['path']
        probe=common.process([CLI,'probe',source,'--json'],folder/'probe')
        init=common.process([CLI,'init-recipe',source,'--look',LOOK,'--out',folder/'recipe.json'],folder/'init')
        write(folder/'contract.json',{'probe_execution':probe['status'],'asShot_recipe_execution':init['status'],'recipe_created':(folder/'recipe.json').exists(),
          'product_policy':'Proposed: decoded container/metadata supported; unresolved as-shot WB is a distinct capability error. No fabricated gains or silent fallback. Custom WB only with verified user-supplied values; Auto WB opt-in requires separate provenance/version.'})
        assert probe['status']=='SUCCESS' and init['status']=='FAILED' and not (folder/'recipe.json').exists()
        # Repeat fresh processes; diagnostic work measured separately, not a speedup claim.
        perf=[]
        for sid in ['R025','R039']:
            for rep in range(3):
                for mode in ['production','diagnostic']:
                    folder=out/'performance'/sid/f'{mode}-{rep}';folder.mkdir(parents=True,exist_ok=False)
                    argv=[CLI,'render',OLD/items[sid]['path'],'--recipe',recipes/f'{sid}.json','--look',LOOK,'--out',folder/'output.jpg','--report',folder/'report.json']
                    if mode=='diagnostic':argv+=['--diagnostic-pixels',folder/'pixels']
                    execution=common.process(argv,folder/'process');assert execution['status']=='SUCCESS'
                    perf.append({'id':sid,'rep':rep,'mode':mode,'execution':execution,'report':load(folder/'report.json')})
                    print('performance',sid,mode,rep,flush=True)
        write(out/'performance.json',perf)
    if a.section in ['all','preview']:
        look=out/'looks/cache-test';look.mkdir(parents=True,exist_ok=True)
        # Technical fixture, deliberately not a commercial/aesthetic preset.
        cube='LUT_3D_SIZE 17\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n'+'\n'.join(f'{r/16*.8} {g/16*.9} {b/16}' for b in range(17) for g in range(17) for r in range(17))+'\n'
        (look/'color.cube').write_text(cube);shutil.copyfile(LOOK/'LICENSE.txt',look/'LICENSE.txt')
        manifest=load(LOOK/'manifest.json');manifest.update(id='cache-test',name='Cache test only',notes='Synthetic channel scaling fixture; not a product look')
        manifest['operator'].update(dimension=17,assetSha256=sha(look/'color.cube'));write(look/'manifest.json',manifest)
        identity=out/'looks/identity'
        if not identity.exists():shutil.copytree(LOOK,identity)
        alternate={'id':'identity-technical-fixture','version':'1.0.0','manifestSha256':sha(identity/'manifest.json')}
        results=[]
        for sid in ['R025','R039','R001']:
            recipe=load(recipes/f'{sid}.json');recipe['look'].update(id='cache-test',manifestSha256=sha(look/'manifest.json'))
            rpath=recipes/f'{sid}-cache-test.json';write(rpath,recipe)
            for rep in range(3):
                commands=[{'name':'cancel-cold','cancelAt':'raw.open'}, {'name':'initial','amount':0},{'name':'lookA','amount':.35},{'name':'lookB','amount':.7},
                    {'name':'lookA-return','amount':.35},{'name':'ev','amount':.35,'ev':-1},
                    {'name':'wb','amount':.35,'wbFactor':1.1},{'name':'wb-reset','amount':.35},
                    {'name':'cancel-warm','amount':.35,'cancelAt':'transfer.chunk'},
                    {'name':'after-cancel','amount':.35}, {'name':'look-switch','amount':.35,'lookOverride':alternate},
                    {'name':'geometry','amount':.35,'rotation':1,'mirror':True},
                    {'name':'stale','amount':.7,'generation':1}, {'name':'latest','amount':.35,'export':rep==0}]
                for n,c in enumerate(commands):
                    if 'generation' not in c:c['generation']=n+1
                    if rep==0 and c['name'] in ['initial','lookA','lookB','ev','wb','geometry','look-switch']:c['verifyUncached']=True
                rows=session('session',OLD/items[sid]['path'],out/'looks',rpath,out/'preview'/sid/f'rep-{rep}',commands)
                byname={r['name']:r for r in rows}
                assert byname['initial']['developCountDelta']==1
                for name in ['lookA','lookB','lookA-return','ev','after-cancel','look-switch','geometry','latest']:
                    assert byname[name]['status']==0 and byname[name]['cacheHit'] and byname[name]['developCountDelta']==0
                for name in ['wb','wb-reset']:assert byname[name]['developCountDelta']==1
                assert byname['lookA']['pixelSha256']==byname['lookA-return']['pixelSha256']==byname['after-cancel']['pixelSha256']==byname['latest']['pixelSha256']
                assert byname['lookA']['pixelSha256']!=byname['lookB']['pixelSha256']
                for name in ['cancel-cold','cancel-warm','stale']:assert byname[name]['status']==10 and byname[name]['imageIsNull']
                for r in rows:
                    if r['status']==0:assert r['alphaAllOne'] and r['orientationState']==1
                    if 'uncachedMaxAbs' in r:assert r['uncachedMaxAbs']==0 and r['uncachedShapeEqual']
                    if 'exportStatus' in r:
                        assert r['exportStatus']==0
                        im=Image.open(out/'preview'/sid/f'rep-{rep}/latest.jpg')
                        assert max(im.size)>1200
                        r['exportDimensions']=list(im.size)
                results.append({'id':sid,'rep':rep,'rows':rows});write(out/'preview.json',results)
                print('preview',sid,rep,flush=True)
    if a.section in ['all','headroom']:
        rows=[]
        for sid in ['R007','R020','R001']:
            commands=[{'name':'baseline','ev':0},{'name':'late-minus2','ev':-2},{'name':'early-quarter','earlyScale':.25}]
            result=session('headroom',OLD/items[sid]['path'],LOOK,recipes/f'{sid}.json',out/'headroom'/sid,commands)
            assert all(r['status']==0 for r in result)
            rows.append({'id':sid,'runs':result,'roi':policy['rois'][sid]});print('headroom',sid,flush=True)
        write(out/'headroom.json',rows)

if __name__=='__main__':main()
