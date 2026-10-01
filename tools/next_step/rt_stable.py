"""Uniform CPU1 reference group after X-Trans threading isolation."""
import argparse,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
import numpy as np,tifffile
from tools.next_step.reference import RT,OLD,common,load,write,sha,inspect,IndependentTiff
from raw_benchmark.imaging import CMS
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();out=run/'rt-stable';out.mkdir(exist_ok=False);common.RUN=out
 repeats=load(run/'rt-repeatability/results.json')
 assert all(next(v for v in repeats if v['id']==sid and v['thread_limit']==1)['status']=='VERIFIED' for sid in ['R025','R039'])
 items={v['source_id']:v for v in load(OLD/'corpus.manifest.json')['items']};rows=[];effects=[]
 reader=IndependentTiff();cms=CMS()
 for sid in ['R025','R039','R001','R004']:
  for variant in (['base','ev1'] if sid in ['R025','R001'] else ['base']):
   folder=out/sid/variant;folder.mkdir(parents=True)
   raw=folder/('input'+Path(items[sid]['path']).suffix);shutil.copyfile(OLD/items[sid]['path'],raw)
   pp3=folder/'profile.pp3';text=(run/f'reference/{sid}/base-fixed/profile.pp3').read_text()
   if variant=='ev1':text=text.replace('Compensation=0','Compensation=1')
   pp3.write_text(text)
   conf=folder/'rt-settings';conf.mkdir();(conf/'options').write_text('[General]\nVerbose=true\n[Raw Decoder]\nEnableLibRaw=true\n')
   result=common.process([RT,'-O',folder/'native.tif','-p',pp3,'-tz','-b16','-c',raw],folder/'process',env_extra={'RT_SETTINGS':str(conf),'OMP_NUM_THREADS':'1','OMP_THREAD_LIMIT':'1'})
   assert result['status']=='SUCCESS' and sha(raw)==sha(OLD/items[sid]['path'])==items[sid]['sha256']
   record={'id':sid,'variant':variant,'mode':'BASE_CONTROLLED','execution_variant':'CPU1_REFERENCE','execution':result,'source_sha256':sha(raw),'settings_sha256':sha(pp3),'native_sha256':sha(folder/'native.tif'),'engine_sha256':sha(RT)}
   record.update(inspect(folder/'native.tif',folder,reader,cms))
   if sid in ['R025','R039'] and variant=='base':
    original=tifffile.imread(run/f'rt-repeatability/{sid}/threads-1-rep-0/native.tif');current=tifffile.imread(folder/'native.tif')
    assert np.array_equal(original,current)
    record['third_CPU1_render_exact']=True
   write(folder/'record.json',record);rows.append(record);write(out/'results.json',rows);print(sid,variant,'SUCCESS',flush=True)
  if sid in ['R025','R001']:
   first=tifffile.imread(out/sid/'base/normalized.tif');second=tifffile.imread(out/sid/'ev1/normalized.tif');delta=float(np.max(np.abs(first-second)));assert delta>1e-4
   effects.append({'id':sid,'cfa':items[sid]['cfa'],'mode':'BASE_CONTROLLED','execution_variant':'CPU1_REFERENCE','change':'Compensation 0 to 1','max_abs':delta,'status':'VERIFIED'});write(out/'config-effects.json',effects)
if __name__=='__main__':main()
