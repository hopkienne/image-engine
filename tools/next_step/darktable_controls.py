"""Four fresh darktable controls, isolated from all run-v1 records."""
import argparse, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
from raw_benchmark import common, imaging, adapters, smoke
from raw_benchmark.common import load, write, sha
OLD=common.RUN
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    for module in [common,imaging,adapters,smoke]:module.RUN=out
    shutil.copyfile(OLD/'engines.lock.json',out/'engines.lock.json');shutil.copytree(OLD/'profiles',out/'profiles')
    items=[i for i in load(OLD/'corpus.manifest.json')['items'] if i['source_id'] in ['R025','R039','R001','R004']]
    rows=[]
    effects=[]
    for item in items:
        target=out/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(OLD/item['path'],target);assert sha(target)==item['sha256']
        row=adapters.render(item,'darktable',resume=False);rows.append(row);write(out/'results.json',rows)
        print(item['source_id'],row['execution']['status'],flush=True)
        if item['source_id'] in ['R025','R001']:
            perturbed=adapters.render(item,'darktable',resume=False,perturb=True)
            import tifffile,numpy as np
            if row['execution']['status']=='SUCCESS' and perturbed['execution']['status']=='SUCCESS':
                first=tifffile.imread(out/row['normalized_export']['path']);second=tifffile.imread(out/perturbed['normalized_export']['path'])
                delta=float(np.max(np.abs(first-second)));assert delta>1e-4
                effects.append({'id':item['source_id'],'cfa':item['cfa'],'perturbation':'generated temperature-v4 red gain x1.25','max_abs':delta,'record':perturbed})
                write(out/'config-effects.json',effects)
if __name__=='__main__':main()
