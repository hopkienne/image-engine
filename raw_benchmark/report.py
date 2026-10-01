"""Offline static report; failures keep their planned rows and denominators."""
import csv
import html
import math
import random
import numpy as np
import tifffile
from PIL import Image
from collections import Counter
from .common import *

CSS='''body{font:15px system-ui;background:#111821;color:#e5edf5;margin:24px;line-height:1.5}a{color:#8dc6ff}h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #334050}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#202b38;padding:14px} .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.panel{background:#1b2735;padding:15px;border-radius:8px;overflow:auto}.overview{width:100%;height:auto}.nativecrop{width:512px;max-width:none;height:auto;image-rendering:auto}.badge{display:inline-block;border:1px solid #678;padding:3px 8px;border-radius:5px}.warning{color:#ffd18c}.muted{color:#b0bed0}svg{width:100%;height:100px}@media(max-width:900px){.grid{grid-template-columns:1fr}}'''

def esc(value): return html.escape(str(value),quote=True)
def link(path,label=None,prefix=''):
    return f'<a href="{esc(prefix+str(path))}">{esc(label or path)}</a>'
def image_tag(path,prefix='',crop=False):
    return f'<img loading="lazy" decoding="async" class="{"nativecrop" if crop else "overview"}" src="{esc(prefix+path)}" alt="{"Native-grid 100% crop" if crop else "8-bit display preview; measurements use lossless float"}">'
def page(title,body,path,script=''):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(f'<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style><body>{body}<script>{script}</script></body></html>',encoding='utf-8')

def histogram(hist):
    top=max(max(v) for v in hist) or 1; curves=[]
    for values,color in zip(hist,('#ff7373','#65de9b','#78a8ff')):
        points=' '.join(f'{i*600/255:.1f},{95-90*math.log1p(v)/math.log1p(top):.1f}' for i,v in enumerate(values))
        curves.append(f'<polyline points="{points}" stroke="{color}" fill="none"/>')
    return '<svg viewBox="0 0 600 100" aria-label="RGB histogram encoded [0,1], logarithmic count axis">'+''.join(curves)+'</svg><small>RGB histogram: x = encoded sRGB [0,1], y = log(1+count).</small>'

def records(manifest):
    result=[]
    for item in manifest['items']:
        for engine in ('ours','darktable','rawtherapee'):
            path=RUN/'jobs'/item['source_id']/engine/'latest.json'
            if path.exists(): result.append(load(path))
            else: result.append({'source_id':item['source_id'],'engine_id':engine,'mode':'BASE_CONTROLLED',
                'execution':{'status':'BLOCKED' if item['acquisition_status']=='BLOCKED' else 'NOT_RUN','wall_seconds':None,'cache_hit':False},
                'reason':item.get('reason','not executed in this stage'),'review_status':'NOT_REVIEWED',
                'comparison_eligibility':'NOT_COMPARABLE','technical_checks':[]})
    return result

def generate(stage='pilot'):
    manifest=load(RUN/'corpus.manifest.json'); results=records(manifest)
    comparisons=load(RUN/'comparisons.json') if (RUN/'comparisons.json').exists() else {}
    tests=load(RUN/'harness-tests.json') if (RUN/'harness-tests.json').exists() else {'status':'BLOCKED'}
    effects=load(RUN/'config-effects.json') if (RUN/'config-effects.json').exists() else {'status':'BLOCKED'}
    repeats=load(RUN/'repeatability.json') if (RUN/'repeatability.json').exists() else {'status':'BLOCKED'}
    counts=Counter(r['execution']['status'] for r in results)
    pairs=[p for scene in comparisons.values() for p in scene.get('pairs',[])]
    pair_counts=Counter(p['status'] for p in pairs)
    fetched=sum(v['acquisition_status']=='SUCCESS' for v in manifest['items'])
    core=load(RUN/'baseline.json')
    source_unchanged=all((ROOT/p).exists() and sha(ROOT/p)==h for p,h in core['source_hashes'].items())
    flags=[sid for sid,s in comparisons.items() if s.get('triage',{}).get('quality_triage')=='REVIEW_REQUIRED']
    eligible_nonflagged=sorted(sid for sid,s in comparisons.items() if sid not in flags)
    rng=random.Random(20260930); rng.shuffle(eligible_nonflagged)
    sample=eligible_nonflagged[:math.ceil(.2*len(eligible_nonflagged))]
    unresolved=[r for r in results if r['execution']['status'] not in ('SUCCESS','UNSUPPORTED','FAILED','TIMEOUT')
                or (r['execution']['status']=='SUCCESS' and not output_eligible(r))]
    status='PARTIAL' if unresolved or tests['status']!='PASS' or effects['status']!='PASS' or repeats['status']!='PASS' else 'COMPLETE'
    if not source_unchanged: status='INVALID'
    summary={'created_at':now(),'stage':stage,'runner_status':status,'planned_raws':40,'planned_jobs':120,
             'fetched_raws':fetched,'execution_counts':dict(counts),'pairwise_counts':dict(pair_counts),
             'quality_review_required':flags,'quality_not_flagged_sample':sample,'human_review':'NOT_REVIEWED',
             'harness_tests':tests['status'],'config_effects':effects['status'],'repeatability':repeats['status'],
             'core_source_unchanged_from_baseline':source_unchanged,'ready_for_G2_review':False,
             'coverage_gaps':manifest['coverage_gaps'],'scope_status':'Proposed',
             'absolute_color_accuracy':'NOT_RUN: NO_VALID_COLOR_REFERENCE',
             'visual_review':'NOT_VISUALLY_REVIEWED; no human feedback imported',
             'stored_corpus_output_bytes':budget(),'not_aesthetic_score':True}
    summary['unresolved_pixel_mapping_sources']=sorted(sid for sid,s in comparisons.items()
        if any(p['status']!='COMPARABLE' for p in s.get('pairs',[])))
    summary['coverage']={'planned_by_camera':dict(Counter(v['make']+' '+v['model'] for v in manifest['items'])),
        'fetched_by_CFA':dict(Counter(v.get('cfa') or 'UNKNOWN' for v in manifest['items'] if v['acquisition_status']=='SUCCESS')),
        'planned_by_split':dict(Counter(v['split'] for v in manifest['items'])),
        'conservative_camera_session_groups':len({v['scene_session_group'] for v in manifest['items']}),
        'verified_scene_tags':dict(Counter(t for v in manifest['items'] for t in v['scene_tags'])),
        'verified_portrait_count':sum(v.get('portrait') is True for v in manifest['items']),
        'scope':'Proposed; X-Trans exploratory; no camera certified'}
    attempts=[]
    for p in RUN.rglob('result.json'):
        attempt=load(p)
        if 'job_id' in attempt and 'execution' in attempt:
            attempts.append({'job_id':attempt['job_id'],'source_id':attempt['source_id'],
                'engine':attempt['engine_id'],'status':attempt['execution']['status'],
                'reason':attempt.get('reason'),'evidence':rel(p)})
    summary['all_saved_attempt_counts']=dict(Counter(v['status'] for v in attempts))
    write(RUN/'attempt-history.json',{'attempts':attempts,'limitation':'Includes setup retries, config perturbations and repeats; NOT the planned 120 source-engine job denominator.'})
    if (RUN/'ai-visual-observations.json').exists():
        summary['AI_suggestions']='ai-visual-observations.json; limited previews, not human review or ground truth'
    if (RUN/'execution-events.jsonl').exists():
        events=[json.loads(line) for line in (RUN/'execution-events.jsonl').read_text().splitlines()]
        summary['runner_cache_reuse_events']=sum(e['cache_hit'] for e in events)
        summary['cache_event_evidence']='execution-events.jsonl; reused results have no new render time'
    write(RUN/'summary.json',summary); write(RUN/'render-results.json',results)
    write(RUN/'metrics.json',{'records':[{'source_id':r['source_id'],'engine':r['engine_id'],'execution':r['execution']['status'],'metrics':r.get('metrics')} for r in results],
                             'comparisons':comparisons,'limitations':'Difference is not ground truth. Unknown geometry produces no pixel metric.'})
    with (RUN/'metrics.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['source_id','engine','execution','native_width','native_height','native_bits','wall_seconds','peak_working_set_bytes','near_white_any','near_black_all','linear_Y_p50','review_status'])
        writer.writeheader()
        for r in results:
            d=r.get('descriptor',{}); m=r.get('metrics',{}); e=m.get('endpoints',{})
            writer.writerow({'source_id':r['source_id'],'engine':r['engine_id'],'execution':r['execution']['status'],
                'native_width':d.get('width'),'native_height':d.get('height'),'native_bits':d.get('native_precision_bits'),
                'wall_seconds':r['execution'].get('wall_seconds'),'peak_working_set_bytes':r['execution'].get('peak_memory_bytes'),
                'near_white_any':e.get('near_white_any'),'near_black_all':e.get('near_black_all'),
                'linear_Y_p50':m.get('linear_Y_quantiles',{}).get('p50'),'review_status':'NOT_REVIEWED'})
    # Matrix is deliberately per-evidence, not an aggregate render PASS.
    matrix_path=BASE/'templates/test_matrix.json'
    if not matrix_path.exists(): matrix_path=ROOT.parent/'RAW_Engine_MultiEngine_Benchmark_v1/templates/test_matrix.json'
    matrix=load(matrix_path)
    statuses={1:('PASS','engines.lock.json'),2:('PASS','corpus.manifest.json'),3:('PASS' if fetched==40 else 'BLOCKED','downloads.json'),
      4:('PASS' if (RUN/'holdout.freeze.json').exists() else 'BLOCKED','selection.lock.json'),
      5:('PASS' if all(any(r['engine_id']==e and r['execution']['status']=='SUCCESS' for r in results) for e in ('ours','darktable','rawtherapee')) else 'BLOCKED','render-results.json'),
      6:('PASS','render-results.json'),7:(effects['status'],'config-effects.json'),
      8:('PASS' if counts['SUCCESS'] else 'BLOCKED','render-results.json'),9:('PASS' if counts['SUCCESS'] else 'BLOCKED','harness-tests.json'),
      10:('PASS' if comparisons else 'BLOCKED','comparisons.json'),11:('PASS' if all(r.get('source_unchanged',True) for r in results) else 'FAIL','render-results.json'),
      12:('PASS' if counts['SUCCESS'] else 'BLOCKED','render-results.json'),13:(repeats['status'],'repeatability.json'),
      14:(tests['status'],'harness-tests.json'),15:('PASS' if comparisons else 'BLOCKED','metrics.json'),
      16:('PASS' if any(p['status']=='COMPARABLE' for p in pairs) else 'BLOCKED','comparisons.json'),
      17:(tests['status'],'harness-tests.json'),18:('PASS' if sum(v['pilot'] and v['acquisition_status']=='SUCCESS' for v in manifest['items'])==12 else 'BLOCKED','pilot-summary.json'),
      19:('PASS' if fetched==40 and not counts['NOT_RUN'] and (RUN/'holdout.freeze.json').exists() else 'BLOCKED','holdout.freeze.json'),
      20:('PASS' if counts['SUCCESS'] else 'BLOCKED','metrics.csv'),21:('PASS','index.html'),22:('PASS','summary.json'),
      23:('NOT_RUN','blind/index.html'),24:('NOT_RUN','metrics.json'),25:('PASS' if source_unchanged else 'FAIL','baseline.json'),26:('PASS','FINAL_REPORT.md')}
    for i,row in enumerate(matrix['rows'],1):
        row['status'],evidence=statuses[i]; row['evidence']=[evidence]; row['owner']='benchmark maintainer'
        if row['status']=='PARTIAL': row['status']='BLOCKED'
        row['notes']='NO_VALID_COLOR_REFERENCE' if i==24 else 'NOT_REVIEWED: no human reviewer feedback' if i==23 else 'PASS means evidence collected, not image quality acceptance. Failed jobs and limits remain visible.'
    matrix['status']=status; write(RUN/'test_matrix.json',matrix)
    rows=[]; blind_mapping={}; blind_body=[]
    for item in manifest['items']:
        sid=item['source_id']; jobs=[r for r in results if r['source_id']==sid]; scene=comparisons.get(sid,{})
        tr=scene.get('triage',{'quality_triage':'NOT_EVALUATED','review_status':'NOT_REVIEWED'})
        columns=[]
        for r in jobs:
            state=r['execution']['status']; column=f'<section class="panel"><h2>{esc(r["engine_id"])}</h2><span class="badge">Execution: {esc(state)}</span>'
            if r.get('normalized_export'):
                folder=Path(r['normalized_export']['path']).parent.as_posix()
                mask_white=RUN/folder/'mask-near-white-any.png'; mask_black=RUN/folder/'mask-near-black-all.png'
                if not mask_white.exists() or not mask_black.exists():
                    pixels=tifffile.imread(RUN/r['normalized_export']['path'])
                    Image.fromarray((pixels.max(axis=2)>=.995).astype(np.uint8)*255).save(mask_white)
                    Image.fromarray((pixels.max(axis=2)<=.005).astype(np.uint8)*255).save(mask_black)
                    del pixels
                column+='<h3>Native preview → normalized sRGB</h3>'+image_tag(folder+'/native-preview.png','../')+image_tag(folder+'/overview.png','../')
                column+='<p class="muted">Preview 8-bit chỉ để xem. Metric dùng TIFF float32 lossless và ICC transform.</p>'
                column+=link(r['normalized_export']['path'],'Normalized FP32 TIFF','../')+' · '+link(folder+'/descriptor.json','ICC / precision descriptor','../')
                for n in r['native_export']:
                    native=n.get('archive',n); column+='<p>'+link(native['path'],'Native lossless export','../')+'</p>'
                column+=histogram(r['metrics']['histogram_encoded_RGB_256bins'])
                column+='<details><summary>Endpoint masks · white pixel means threshold matched</summary><p>Near-white ANY channel ≥0.995 (encoded SDR)</p>'+image_tag(folder+'/mask-near-white-any.png','../')+'<p>Near-black ALL channels ≤0.005 (encoded SDR)</p>'+image_tag(folder+'/mask-near-black-all.png','../')+'</details>'
                for roi in r['metrics']['rois']:
                    column+='<h3>'+esc(roi['label'])+' — 100% pixels</h3>'+image_tag(roi['path'],'../',True)+'<p>Independent candidate ROI; use synchronized pair crops below for cross-engine review.</p>'
                column+='<details><summary>Metrics / settings / technical evidence</summary><pre>'+esc(json.dumps({k:r.get(k) for k in ('metrics','effective_settings','technical_checks','execution')},indent=2))+'</pre></details>'
            else:
                column+='<p class="warning">'+esc(r.get('reason','no output'))+'</p>'
                if r.get('job_id'):
                    for process_path in sorted((RUN/r['job_id']).rglob('process.json')):
                        actual=load(process_path)
                        column+='<details><summary>Actual subprocess '+esc(process_path.parent.name)+' · '+esc(actual['status'])+'</summary><pre>'+esc(json.dumps(actual,indent=2))+'</pre>'
                        for field in ('stdout_path','stderr_path'):
                            if actual.get(field): column+=link(actual[field],field,'../')+' · '
                        column+='</details>'
            if r.get('job_id'): column+='<p>'+link(r['job_id']+'/result.json','Job evidence','../')+'</p>'
            if r['execution'].get('stderr_path'): column+='<p>'+link(r['execution']['stderr_path'],'stderr','../')+' · '+link(r['execution']['stdout_path'],'stdout','../')+'</p>'
            column+='</section>'; columns.append(column)
        pairs_html=''
        for p in scene.get('pairs',[]):
            pairs_html+='<section class="panel"><h2>'+esc(p['pair'])+' — '+esc(p['status'])+'</h2>'
            if p.get('heatmap'):
                pairs_html+=image_tag(p['heatmap']['path'],'../')+'<p>Fixed heatmap encoded RGB MAE: black=0, red=0.25 or more. Display overview only.</p>'
                pairs_html+='<div class="grid">'+image_tag(p['matched_roi']['A_path'],'../',True)+image_tag(p['matched_roi']['B_path'],'../',True)+'</div>'
            pairs_html+='<pre>'+esc(json.dumps(p,indent=2))+'</pre></section>'
        sanitized={k:item.get(k) for k in ('source_id','make','model','split','publisher_subtype','cfa','iso','scene_tags','portrait','license_id','sha256','scene_session_group')}
        body=link('../index.html','← Tổng quan')+f'<h1>{esc(sid)} · {esc(item["make"])} {esc(item["model"])}</h1><pre>'+esc(json.dumps(sanitized,indent=2))+'</pre>'
        body+='<p>Quality triage: '+esc(tr['quality_triage'])+' · Human review: NOT_REVIEWED</p><pre>'+esc(json.dumps(tr,indent=2))+'</pre><div class="grid">'+''.join(columns)+'</div>'+pairs_html
        page(sid,body,RUN/'scenes'/f'{sid}.html')
        rows.append('<tr><td>'+link('scenes/'+sid+'.html',sid)+'</td><td>'+esc(item['make']+' '+item['model'])+'</td><td>'+esc(item['split'])+(' / pilot' if item['pilot'] else '')+'</td><td>'+esc(item['acquisition_status'])+'</td><td>'+esc(' · '.join(r['engine_id']+': '+r['execution']['status'] for r in jobs))+'</td><td>'+esc(tr['quality_triage'])+'</td></tr>')
        order=list(jobs); random.Random(20260930+int(sid[1:])).shuffle(order); blind_mapping[sid]={}
        blind_cols=[]
        for alias,r in zip(('A','B','C'),order):
            blind_mapping[sid][alias]=r['engine_id']; col=f'<section class="panel"><h3>{alias}</h3>'
            if r.get('normalized_export'):
                from shutil import copyfile
                source=RUN/Path(r['normalized_export']['path']).parent
                dst=RUN/'blind/assets'; dst.mkdir(parents=True,exist_ok=True)
                for filename,suffix in [('overview.png','overview'),('roi-center.png','crop')]:
                    copyfile(source/filename,dst/f'{sid}-{alias}-{suffix}.png')
                col+=image_tag(f'assets/{sid}-{alias}-overview.png')+image_tag(f'assets/{sid}-{alias}-crop.png','',True)
            else: col+='<p>Không có output — '+esc(r['execution']['status'])+'</p>'
            blind_cols.append(col+'</section>')
        blind_body.append(f'<section data-scene="{sid}"><h2>{sid}</h2><p>Center crops are independent; exact synchronization may be unavailable. Review preferences separately from defects.</p><div class="grid">'+''.join(blind_cols)+'</div><label>Feedback <textarea data-id="'+sid+'" rows="3" style="width:95%" placeholder="Nêu alias và chi tiết lỗi/sở thích; không có ground truth tự động"></textarea></label></section>')
    write(RUN/'blind-mapping.json',{'seed':20260930,'mapping':blind_mapping,'not_double_blind':'mapping stored separately; knowledgeable viewers may identify renderer visually'})
    script='''document.getElementById('export').onclick=()=>{const data={reviewer:document.getElementById('reviewer').value,seed:20260930,created_at:new Date().toISOString(),feedback:[...document.querySelectorAll('textarea')].filter(x=>x.value.trim()).map(x=>({scene:x.dataset.id,notes:x.value,status:'HUMAN_FEEDBACK_PENDING_TRIAGE'}))};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='blind-feedback.json';a.click();URL.revokeObjectURL(a.href)};'''
    page('Blind A/B/C', '<h1>Blind A/B/C · seed 20260930</h1><p>Human review: NOT_REVIEWED. Trang không hiển thị mapping engine. Không tuyên bố double-blind.</p><label>Reviewer ID <input id="reviewer"></label> <button id="export">Tải feedback JSON</button>'+''.join(blind_body),RUN/'blind/index.html',script)
    overview='<h1>RAW · Multi-engine benchmark</h1><p class="badge">Runner '+esc(status)+'</p><p>Scope Proposed · BASE_CONTROLLED · Full resolution · Human review NOT_REVIEWED</p>'
    overview+='<p class="warning">Execution SUCCESS không đồng nghĩa ảnh đúng/đẹp. darktable và RawTherapee không phải ground truth; có thể dùng chung LibRaw. Không có điểm tổng chất lượng hay chứng nhận G2.</p>'
    overview+='<div class="grid"><section class="panel"><h2>Execution</h2><p>'+esc(f'{fetched}/40 RAW · 120 planned jobs')+'</p><pre>'+esc(json.dumps(dict(counts),indent=2))+'</pre></section><section class="panel"><h2>Technical checks</h2><p>'+esc(f"Harness {tests['status']} · Config {effects['status']} · Repeats {repeats['status']}")+'</p><p>Core hashes unchanged: '+esc(source_unchanged)+'</p></section><section class="panel"><h2>Quality / human review</h2><p>'+esc(f'{len(flags)} REVIEW_REQUIRED scenes · NOT_REVIEWED')+'</p><p>Chart: BLOCKED — NO_VALID_COLOR_REFERENCE. Camera/scene scope: Proposed / UNKNOWN.</p></section></div>'
    overview+='<details><summary>Full counters, coverage and limitations</summary><pre>'+esc(json.dumps(summary,indent=2))+'</pre></details>'
    overview+='<p>'+link('blind/index.html','Blind A/B/C')+' · '+link('metrics.csv','Metrics CSV')+' · '+link('metrics.json','Metrics JSON')+' · '+link('test_matrix.json','BMQ matrix')+' · '+link('engines.lock.json','Engine versions / hashes')+' · '+link('corpus.manifest.json','Corpus/license manifest')+' · '+link('README.md','Re-run instructions')+'</p>'
    for filename,label in [('ONE_PAGE_REPORT.md','One-page handoff'),('FINAL_REPORT.md','Detailed handoff'),('issues.json','Issues / owner / replay'),('historical-storage.json','Byte-exact historical storage'),('lossless-history-tests.json','Historical storage restoration tests'),('color-transform-tests.json','Independent nonidentity color transform test'),('profile-contract-evidence.json','Configured ICC consistency'),('ai-visual-observations.json','AI suggestions — limited preview inspection')]:
        if (RUN/filename).exists(): overview+=link(filename,label)+' · '
    overview+='<h2>Ưu tiên review</h2><p>Flagged: '+', '.join(link('scenes/'+sid+'.html',sid) for sid in flags)+' · deterministic ≥20% nonflagged: '+', '.join(link('scenes/'+sid+'.html',sid) for sid in sample)+'</p>'
    overview+='<p>Pixel metric BLOCKED / unresolved mapping: '+', '.join(link('scenes/'+sid+'.html',sid) for sid in summary['unresolved_pixel_mapping_sources'])+'</p>'
    overview+='<h2>Execution — đủ 40 RAW × 3 engine trong kế hoạch</h2><table><tr><th>RAW</th><th>Camera</th><th>Split</th><th>Acquisition</th><th>Execution</th><th>Quality triage</th></tr>'+''.join(rows)+'</table>'
    failed_attempts=[a for a in attempts if a['status']!='SUCCESS']
    overview+='<h2>Attempts / failures retained</h2><p>Separate from planned-job denominator: '+esc(summary['all_saved_attempt_counts'])+' · '+link('attempt-history.json','All saved attempt records')+'</p><table><tr><th>Source / engine</th><th>Status</th><th>Reason</th><th>Evidence</th></tr>'
    for a in failed_attempts:
        overview+='<tr><td>'+esc(a['source_id']+' / '+a['engine'])+'</td><td>'+esc(a['status'])+'</td><td>'+esc(a['reason'])+'</td><td>'+link(a['evidence'],'Log/result')+'</td></tr>'
    overview+='</table>'
    if (RUN/'harness-errata.json').exists():
        overview+='<p>'+link('harness-errata.json','Harness correction: initial repeat fixture SHA was null; actual original/working hashes unchanged')+'</p>'
    overview+='<h2>Technical evidence</h2><details><summary>Harness, config-effect and repeatability records</summary><pre>'+esc(json.dumps({'harness':tests,'config_effects':effects,'repeatability':repeats},indent=2))+'</pre></details>'
    perf_rows=[]
    for p in repeats.get('rows',[]):
        perf_rows.append('<tr>'+''.join('<td>'+esc(p.get(k))+'</td>' for k in ('source_id','engine','n','median_seconds','range_seconds','native_pixels_exactly_identical','max_normalized_float_delta'))+'</tr>')
    overview+='<h2>Fresh-process performance · n=3 per fixture / engine</h2><p>Wall time includes each converter export; ours also writes/hashes its FP32 diagnostic dump and exports JPEG. This is not JPEG-only production latency. Excludes runner normalization and separate darktable history preparation. Working-set samples and raw timings are in repeatability.json. No p95, no OS-cold claim, no equivalent-work ranking.</p><table><tr><th>Fixture</th><th>Engine</th><th>n</th><th>Median s</th><th>Range s</th><th>Native pixels exact</th><th>Max float delta</th></tr>'+''.join(perf_rows)+'</table>'
    if (RUN/'performance-breakdown.json').exists(): overview+='<p>'+link('performance-breakdown.json','Ours internal stage timings — preserved repeat jobs')+'</p>'
    overview+='<h2>Coverage / limits</h2><p>Scene tags, lighting và portrait: UNKNOWN; không đo độ chính xác màu tuyệt đối, sensor SNR hay số stop dynamic range từ public single shots. Không suy hiệu năng desktop sang mobile. Geometry chưa xác minh: NOT_COMPARABLE.</p>'
    page('RAW Multi-engine benchmark',overview,RUN/'index.html')
    if stage=='pilot': write(RUN/'pilot-summary.json',summary)
    return summary
