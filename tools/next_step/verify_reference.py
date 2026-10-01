"""Trace native -> normalized -> derivative; unchanged integer-grid comparator."""
import argparse,json,sys,zipfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
import numpy as np,tifffile
from PIL import Image
from raw_benchmark import common,imaging
from raw_benchmark.common import load,write,sha
OLD=common.RUN
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();common.RUN=run
 trace=[];pairs=[];cms=imaging.CMS()
 for sid in ['R025','R039','R001','R004']:
  old=load(OLD/f'jobs/{sid}/rawtherapee/latest.json');before=run/'reference'/sid/'before'
  original=tifffile.imread(OLD/old['normalized_export']['path']);independent=tifffile.imread(before/'normalized.tif')
  same=np.array_equal(original,independent);assert same
  derivative=OLD/old['job_id']/'roi-center.png'
  assert np.array_equal(np.asarray(Image.open(derivative)),np.asarray(Image.open(before/'normalized-crop.png')))
  fixed=load(run/f'reference/{sid}/base-fixed/record.json')
  log=(run/f'reference/{sid}/base-fixed/process/stdout.log').read_text(errors='replace')
  method=[line for line in log.splitlines() if 'Demosaicing' in line]
  backend=[line for line in log.splitlines() if 'provided by libraw' in line]
  assert backend
  row={'id':sid,'old_execution_retained':old['execution']['status'],'independent_normalized_equals_original':same,'independent_crop_equals_review_derivative':True,
   'original_native_hash_verified':sha(OLD/old['native_export'][0]['path'])==old['native_export'][0]['sha256'],
   'actual_backend_evidence':backend,'actual_demosaic_log':method,'review_status':'AI_SUGGESTION; NOT_REVIEWED',
   'old_reference_quality_anomaly':'GREEN_GRID' if sid in ['R025','R039'] else None,'old_reference_eligibility':'BLOCKED' if sid in ['R025','R039'] else 'UNCHANGED'}
  if sid in ['R025','R039']:
   assert any('3-pass (best)' in line for line in method)
   prior=load(run/f'reference/{sid}/base-old-token/record.json')
   assert prior['native_pixel_sha256']==load(before/'inspection.json')['native_pixel_sha256']
   group=tifffile.imread(run/f'reference/{sid}/neutral-plus-optional/native.tif').astype('int32')
   corrected=tifffile.imread(run/f'reference/{sid}/base-fixed/native.tif').astype('int32')
   difference=np.abs(group-corrected)
   row.update(old_anomaly_reproduced_exact=True,fix_equals_neutral_plus_all_other_base_groups_exact=bool(np.array_equal(group,corrected)),
       same_saved_PP3_repeatability={'max_uint16_code_delta':int(difference.max()),'changed_channels':int(np.count_nonzero(difference)),
         'status':'VERIFIED' if int(difference.max())<=1 else 'FAILED','tolerance_uint16_codes':1},first_observed_anomaly='native TIFF')
  trace.append(row)
  oursdir=run/'core/regression'/sid;d=load(oursdir/'pixels.json')
  ours=np.fromfile(oursdir/'pixels.f32',dtype='<f4').reshape(d['height'],d['width'],3)
  with Image.open(oursdir/'output.jpg') as im:profile=im.info['icc_profile']
  ours=np.clip(cms.transform(ours,profile),0,1)
  for engine in ['rawtherapee','darktable']:
   if engine=='rawtherapee':ref=tifffile.imread(run/'rt-stable'/sid/'base/normalized.tif')
   else:
    record=next(v for v in load(run/'darktable/results.json') if v['source_id']==sid)
    if record['execution']['status']!='SUCCESS':pairs.append({'id':sid,'engine':engine,'status':'BLOCKED'});continue
    ref=tifffile.imread(run/'darktable'/record['normalized_export']['path'])
   folder=run/'comparisons'/sid/engine;folder.mkdir(parents=True,exist_ok=True)
   pair=imaging.pair(ours,ref,folder);pair.update(id=sid,reference_engine=engine,quality_acceptance='NOT_REVIEWED',mapping_threshold=.80)
   pairs.append(pair)
   print(sid,engine,pair['status'],flush=True)
 write(run/'reference-trace.json',trace);write(run/'comparisons.json',pairs)
 write(run/'reference-eligibility.json',[{'id':r['id'],'engine':'rawtherapee','execution':'SUCCESS',
  'reference_eligibility':'ELIGIBLE_FOR_TECHNICAL_PAIRWISE_COMPARISON' if r['status']=='COMPARABLE' else 'INCONCLUSIVE',
  'scope':'corrected BASE_CONTROLLED CPU1_REFERENCE export paired with ours on unchanged integer-grid rule; four-thread corrected branch remains repeatability FAILED',
  'legacy_XTrans_anomaly':'resolved in inspected native/normalized crops and supported by exact none-token experiment' if r['id'] in ['R025','R039'] else 'not observed in this Bayer control',
  'review_type':'AI_SUGGESTION','human_review':'NOT_REVIEWED','g2_approved':False,
  'note':'Export-time investigation records retain initial INCONCLUSIVE state; this is the later scope-specific eligibility decision, not quality acceptance.'}
  for r in pairs if r.get('reference_engine')=='rawtherapee'])
if __name__=='__main__':main()
