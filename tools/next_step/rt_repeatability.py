"""Isolate RT X-Trans same-profile pixel nondeterminism; do not relax tolerance."""
import argparse,sys,shutil,configparser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
import numpy as np,tifffile
from PIL import Image
from tools.next_step.reference import RT,OLD,common,load,write,sha,inspect,IndependentTiff
from raw_benchmark.imaging import CMS
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();out=run/'rt-repeatability';out.mkdir(exist_ok=False);common.RUN=out
 items={v['source_id']:v for v in load(OLD/'corpus.manifest.json')['items']};rows=[]
 for sid in ['R025','R039']:
  for threads in [1,4]:
   images=[];records=[]
   for rep in range(2):
    folder=out/sid/f'threads-{threads}-rep-{rep}';folder.mkdir(parents=True)
    raw=folder/'input.raf';shutil.copyfile(OLD/items[sid]['path'],raw)
    pp3=folder/'profile.pp3';shutil.copyfile(run/f'reference/{sid}/base-fixed/profile.pp3',pp3)
    conf=folder/'rt-settings';conf.mkdir();(conf/'options').write_text('[General]\nVerbose=true\n[Raw Decoder]\nEnableLibRaw=true\n')
    result=common.process([RT,'-O',folder/'native.tif','-p',pp3,'-tz','-b16','-c',raw],folder/'process',env_extra={'RT_SETTINGS':str(conf),'OMP_NUM_THREADS':str(threads),'OMP_THREAD_LIMIT':str(threads)})
    assert result['status']=='SUCCESS' and sha(raw)==items[sid]['sha256']
    image=tifffile.imread(folder/'native.tif');images.append(image)
    record={'id':sid,'threads_requested':threads,'rep':rep,'execution':result,'native_sha256':sha(folder/'native.tif'),'source_sha256':sha(raw),'settings_sha256':sha(pp3)};records.append(record)
    write(folder/'record.json',record);print(sid,threads,rep,flush=True)
   delta=np.abs(images[0].astype('int32')-images[1].astype('int32'))
   row={'id':sid,'thread_limit':threads,'n':2,'max_uint16_code_delta':int(delta.max()),'changed_channels':int(np.count_nonzero(delta)),'mean_code_delta':float(delta.mean()),'tolerance_uint16_codes':1,'status':'VERIFIED' if int(delta.max())<=1 else 'FAILED','runs':records}
   rows.append(row);write(out/'results.json',rows)
 # Keep explicit original four-thread corrected exports. A stable one-thread
 # alternative can be considered separately; never replace their evidence.
 for sid in ['R025','R039']:
  inspect(out/sid/'threads-1-rep-0/native.tif',out/sid/'threads-1-rep-0',IndependentTiff(),CMS())
if __name__=='__main__':main()
