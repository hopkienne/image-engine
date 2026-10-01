import argparse, json, sys, hashlib, statistics, html, os, configparser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
import numpy as np
from PIL import Image
from raw_benchmark.common import load, write, sha

def pixels(folder,stage,kind='f32'):
    d=load(folder/(stage+'.json'));a=np.memmap(folder/(stage+'.'+kind),dtype='<f4' if kind=='f32' else '<u2',mode='r',shape=(d['height'],d['width'],d['channels']))
    return a,d
def show(a,path):Image.fromarray(np.rint(np.clip(a,0,1)*255).astype('uint8')).save(path)
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();core=run/'core'
    evidence=[]
    if (core/'headroom.json').exists():
        old=ROOT/'artifacts/multi-engine-benchmark/20261001/run-v1'
        policies=[]
        for sid in ['R007','R020']:
            ours=load(core/f'regression/{sid}/report.json')
            rt=load(old/f'jobs/{sid}/rawtherapee/latest.json');dt=load(old/f'jobs/{sid}/darktable/latest.json')
            pp3=old/rt['job_id']/'native.tif.pp3';profile=configparser.ConfigParser();profile.read(pp3)
            policies.append({'id':sid,'mode':'BASE_CONTROLLED','ours':{'effective_config':ours['decoderConfig'],'exposure_stage':'after bounded integer develop'},
                'rawtherapee':{'HLRecovery_enabled':profile['HLRecovery'].getboolean('Enabled'),'merged_pp3_sha256':sha(pp3),'job':rt['job_id']},
                'darktable':{'highlight_modules':[h for h in dt['effective_settings']['exported_history'] if 'highlight' in h['operation']],'effective_settings':dt['effective_settings'],'job':dt['job_id']},
                'equivalent_highlight_semantics':False,'reference_policy_evidence':'retained original effective profiles, not a new usable-render mode'})
        write(core/'headroom-policies.json',policies)
        policy=load(core/'locked-test-policy.json')
        for sid in ['R007','R020','R001']:
            root=core/'headroom'/sid
            base,_=pixels(root/'baseline','B0_base_develop');late,_=pixels(root/'late-minus2','B0_after_exposure');early,_=pixels(root/'early-quarter','B0_base_develop')
            before,_=pixels(root/'baseline','D0_pre_scale','u16');early_before,_=pixels(root/'early-quarter','D0_pre_scale','u16')
            assert np.array_equal(before,early_before)
            scale,sd=pixels(root/'baseline','D1_post_scale','u16');early_scale,_=pixels(root/'early-quarter','D1_post_scale','u16')
            post,_=pixels(root/'baseline','D3_post_rgb','u16')
            rgb=post[:,:,:3].astype('float32')*np.float32(1/65535)
            if sd['sourceFlip']==5:rgb=np.rot90(rgb,1)
            elif sd['sourceFlip']==6:rgb=np.rot90(rgb,3)
            assert np.array_equal(rgb,base)
            assert np.array_equal(np.asarray(base)*np.float32(.25),late)
            def oriented_native(a):
                return np.rot90(a,1) if sd['sourceFlip']==5 else np.rot90(a,3) if sd['sourceFlip']==6 else a
            oriented_before=oriented_native(before);oriented_scale=oriented_native(scale);oriented_early_scale=oriented_native(early_scale)
            b4_exact=sha(root/'baseline/B4_output.f32')==sha(core/f'regression/{sid}/pixels.f32')
            assert b4_exact
            row={'id':sid,'pre_scale_inputs_exact':True,'production_post_rgb_matches_B0_exact':True,'baseline_B4_equals_undumped_regression_exact':b4_exact,'late_exposure_equals_B0_times_quarter_exact':True,'rois':[]}
            for name,(x,y,w,h) in policy['rois'][sid].items():
                folder=root/'crops';folder.mkdir(exist_ok=True)
                roi={};mask=np.min(base[y:y+h,x:x+w],axis=2)>=np.float32(65534/65535)
                for label,buf in [('baseline',base),('late-minus2',late),('early-quarter',early)]:
                    crop=np.asarray(buf[y:y+h,x:x+w]);encoded=np.where(crop<=.0031308,12.92*crop,1.055*np.maximum(crop,0)**(1/2.4)-.055)
                    show(encoded,folder/f'{name}-{label}.png')
                    final_pixels,_=pixels(root/label,'B4_output')
                    show(final_pixels[y:y+h,x:x+w],folder/f'{name}-{label}-prejpeg.png')
                    v=crop[mask]
                    roi[label]={'mean_linear_rgb':crop.mean(axis=(0,1),dtype='float64').tolist(),'std_linear_rgb':crop.std(axis=(0,1),dtype='float64').tolist(),
                        'baseline_all_channel_endpoint_pixels':int(mask.sum()),'std_on_baseline_white':v.std(axis=0,dtype='float64').tolist() if len(v) else None}
                pair=mask[:,1:] & mask[:,:-1];grad=np.abs(np.diff(np.asarray(early[y:y+h,x:x+w]),axis=1));roi['early_neighbor_difference_on_baseline_flat_white']=float(grad[pair].mean()) if pair.any() else None
                native_region=oriented_scale[y:y+h,x:x+w];native_mask=native_region==65535
                old_samples=oriented_before[y:y+h,x:x+w][native_mask];new_samples=oriented_early_scale[y:y+h,x:x+w][native_mask]
                roi['scale_stage_same_roi']={'baseline_clipped_native_slots':int(native_mask.sum()),
                    'distinct_D0_values_collapsed_to_endpoint':int(len(np.unique(old_samples))),
                    'distinct_early_D1_values_at_same_slots':int(len(np.unique(new_samples)))}
                b=np.asarray(base[y:y+h,x:x+w]);e=np.asarray(early[y:y+h,x:x+w]);unsaturated=(b>0.01)&(b<0.8)
                roi['unsaturated_channel_control']={'samples':int(unsaturated.sum()),
                    'median_abs_early_times4_minus_baseline':float(np.median(np.abs(e[unsaturated]*4-b[unsaturated]))) if unsaturated.any() else None,
                    'note':'Descriptive nominal-gain control only; early integer truncation/demosaic differ, not an acceptance threshold.'}
                row['rois'].append({'name':name,'xywh':[x,y,w,h],'observations':roi})
            # Same raw coordinates, same native channel. Tests information lost
            # specifically at scale_colors; does not declare scene detail/DR.
            clipped=scale==65535
            row['scale_colors']={'baseline_endpoint_samples':int(clipped.sum()),'early_endpoint_samples':int((early_scale==65535).sum()),
                'early_unique_values_where_baseline_clipped':int(len(np.unique(early_scale[clipped]))),
                'input_unique_values_where_baseline_clipped':int(len(np.unique(before[clipped])))}
            row['limitation']='Early quarter attenuates black-subtracted integer camera samples before scale_colors; loses two bits through truncation and changes demosaic inputs. Diagnostic experiment, not an approved production policy or recoverable sensor stops.'
            evidence.append(row)
        write(core/'headroom-analysis.json',evidence)
    sections=['<!doctype html><meta charset="utf-8"><title>Next step · run-v2</title><style>body{font:16px system-ui;margin:32px;background:#191c21;color:#eee}a{color:#aaccff}p{max-width:1100px}section{margin:36px 0}.row{display:flex;gap:18px;overflow:auto}figure{margin:0;flex:none}figure img{width:512px;height:512px;object-fit:contain;background:#111}figcaption{padding:8px;max-width:500px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #555}pre{white-space:pre-wrap}</style><h1>Reference, preview & headroom · run-v2</h1><p>AI_SUGGESTION. Human review NOT_REVIEWED. G2 not approved. Core color baseline v0 retained. Native crops below are 512 pixels at 100% CSS scale. No image upload, mapping relaxation, warp or color matching.</p>']
    def link(path,label):return f'<a href="{path}">{html.escape(label)}</a>'
    def fig(path,caption):return f'<figure><a href="{path}"><img src="{path}" loading="lazy"></a><figcaption>{html.escape(caption)}</figcaption></figure>'
    sections.append('<p>'+link('NEXT_STEP_REPORT.md','Status report')+' · '+link('reference/root-cause.json','Root-cause evidence')+' · '+link('reference/config-effects.json','X-Trans and Bayer config-effect')+' · '+link('core/locked-test-policy.json','Frozen tolerance / ROI')+'</p>')
    for sid in ['R025','R039','R001','R004']:
        sections.append(f'<section><h2>{sid} · RawTherapee</h2><div class="row">')
        for variant,title in [('before','Original native export, independently read'),('neutral','Verified CLI neutral defaults'),('base-fixed','BASE with valid X-Trans token')]:
            sections.append(fig(f'reference/{sid}/{variant}/normalized-crop.png',title+' · ICC-normalized crop'))
        if (run/f'rt-stable/{sid}/base/normalized-crop.png').exists():
            sections.append(fig(f'rt-stable/{sid}/base/normalized-crop.png','Final CPU1_REFERENCE · uniform resource policy across four RAWs'))
        sections.append('</div><p>Native reader: libtiff scanline uint16, exact against tifffile/imagecodecs; FP32 ICC transform with locked LCMS. Display PNG only is 8-bit.</p>')
        for variant in ['before','neutral','base-fixed']:
            sections.append(link(f'reference/{sid}/{variant}/native-crop.png',variant+' native RGB crop (embedded-profile interpretation in normalized crop)')+' · '+link(f'reference/{sid}/{variant}/record.json',variant+' hashes/settings/logs')+'<br>')
            sections.append(link(f'reference/{sid}/{variant}/normalized.tif',variant+' normalized FP32 TIFF')+' · ')
            if variant!='before':
                sections.append(link(f'reference/{sid}/{variant}/native.tif','native uint16 TIFF')+' · '+link(f'reference/{sid}/{variant}/native.tif.pp3','merged PP3')+' · '+link(f'reference/{sid}/{variant}/process/stdout.log','actual backend/demosaic log')+'<br>')
        sections.append('</section>')
    if (run/'rt-repeatability/results.json').exists():
        sections.append('<h2>RT threading/repeatability finding</h2><p>The corrected four-thread X-Trans path is NOT numerically repeatable at the locked 1-code tolerance. CPU1 preserves the same supported method and gives exact repeated pixels in the measured X-Trans runs; final four-file RT group uses CPU1 uniformly. This resolves the old green grid and provides a reproducible scoped reference, not quality acceptance.</p><p>'+link('rt-repeatability/results.json','1 versus 4 thread evidence')+' · '+link('rt-stable/results.json','Final CPU1 group, raw logs/settings/hashes')+' · '+link('rt-stable/config-effects.json','CPU1 X-Trans/Bayer config effect')+'</p>')
    if (core/'regression.json').exists():
        sections.append('<h2>Core numerical regression</h2><p>Six pre-JPEG full-resolution comparisons; exact baseline hashes, recipe and descriptors retained.</p><div class="row">')
        for sid in ['R025','R039','R007','R020']:
            sections.append(fig(f'core/regression/{sid}/before-crop.png',sid+' baseline'))
            sections.append(fig(f'core/regression/{sid}/after-crop.png',sid+' instrumented core'))
        sections.append('</div><p>'+link('core/regression.json','Full regression evidence')+'</p>')
    if (core/'preview.json').exists():
        preview=load(core/'preview.json');sections.append('<h2>Real preview · persistent process</h2><p>1200px preview after full-resolution develop and look. Cache stores full-resolution oriented linear base. Exposure invalidates downstream; WB invalidates develop. Each warm result is a render, not a cached final output counted as another render.</p><table><tr><th>RAW</th><th>n</th><th>Initial median ms</th><th>Warm look median ms</th><th>EV median ms</th><th>WB median ms</th></tr>')
        summary=[]
        for sid in ['R025','R039','R001']:
            runs=[r for r in preview if r['id']==sid]
            def median(name):return statistics.median(next(v['wallRenderMs'] for v in r['rows'] if v['name']==name) for r in runs)
            values=[median(s) for s in ['initial','lookA','ev','wb']]
            summary.append({'id':sid,'n':len(runs),'initial_ms':values[0],'warm_look_ms':values[1],'ev_ms':values[2],'wb_ms':values[3]})
            sections.append(f'<tr><td>{sid}</td><td>{len(runs)}</td>'+''.join(f'<td>{v:.1f}</td>' for v in values)+'</tr>')
        sections.append('</table><p>Desktop only; fixed four logical processors, OS cache not cold. First repetition includes separate uncached verification, so its lifetime peak RAM includes validation. No p95 or mobile inference.</p><div class="row">')
        for name in ['initial','lookA','lookB','lookA-return','ev','wb']:
            sections.append(fig(f'core/preview/R025/rep-0/{name}.png','R025 '+name+' · overview, not a 1:1 crop'))
        sections.append('</div><p>'+link('core/preview.json','Cache counts, cancellation, alpha, geometry, replay, RAM and timings')+'</p>')
        write(core/'preview-summary.json',summary)
    for row in evidence:
        sections.append(f'<h2>{row["id"]} · headroom diagnostic</h2><p>Columns compare baseline, −2 EV after develop, and quarter signal before scale_colors. Early path is test-only. Reduced endpoints alone are not recovery evidence.</p>')
        for roi in row['rois']:
            sections.append('<h3>'+roi['name']+' '+str(roi['xywh'])+'</h3><div class="row">')
            for label in ['baseline','late-minus2','early-quarter']:sections.append(fig(f'core/headroom/{row["id"]}/crops/{roi["name"]}-{label}-prejpeg.png',label+' · fixed ROI from real B4 pre-JPEG'))
            sections.append('</div>')
    sections.append('<p>'+link('core/headroom-analysis.json','Headroom checkpoints and limits')+' · '+link('mobile-environment.json','Mobile blockers')+'</p>')
    (run/'index.html').write_text('\n'.join(sections),encoding='utf-8')
if __name__=='__main__':main()
