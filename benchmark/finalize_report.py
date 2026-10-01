"""Produce the handoff from actual saved results, never from intended counts."""
import json
from collections import Counter
import statistics
from raw_benchmark.common import *
from raw_benchmark.report import generate

def main():
    manifest=load(RUN/'corpus.manifest.json')
    from shutil import copyfile
    copyfile(BASE/'README.md',RUN/'README.md')
    import tifffile
    for item in manifest['items']:
        item.setdefault('author',None)
        item.setdefault('author_evidence','Not provided in the verified publisher listing; no attribution invented.')
        job=RUN/'jobs'/item['source_id']/'darktable/latest.json'
        if not job.exists(): continue
        record=load(job)
        if not output_eligible(record): continue
        path=RUN/record['native_export'][0]['path']
        with tifffile.TiffFile(path) as t:
            tag=t.pages[0].tags.get('ExifTag'); exif=tag.value if tag else {}
            iso=exif.get('ISOSpeedRatings')
        if isinstance(iso,(int,float)):
            item['iso']=iso; item['iso_evidence']={'origin':'source EXIF preserved by darktable export; no scene-label inference','path':rel(path),'tag':'ISOSpeedRatings'}
        info=load(RUN/item['probe_evidence']) if item.get('probe_evidence') else {}
        item['dng_assessment']={'libraw_dngVersion':info.get('format',{}).get('dngVersion'),
            'publisher_subtype':item['publisher_subtype'],'original_vs_converted':'publisher CHDK subtype; camera firmware-generated DNG indicated, not Adobe-converted' if 'CHDK' in item['publisher_subtype'] else 'NOT_VERIFIED' if info.get('format',{}).get('dngVersion') else 'NON_DNG'}
    write(RUN/'corpus.manifest.json',manifest)
    # Accurate display metadata only; never use these 8-bit PNGs for measurement.
    from PIL import Image
    for result_path in (RUN/'jobs').rglob('latest.json'):
        r=load(result_path)
        if not output_eligible(r): continue
        folder=RUN/r['job_id']; descriptor=r['descriptor']
        native_icc=(RUN/'profiles'/f"{descriptor['icc_sha256']}.icc").read_bytes()
        target_icc=(RUN/'profiles/target-sRGB.icc').read_bytes()
        for filename,icc in [('native-preview.png',native_icc),('overview.png',target_icc),
                            ('roi-center.png',target_icc),('roi-top-left.png',target_icc),('roi-bottom-right.png',target_icc)]:
            path=folder/filename
            with Image.open(path) as image:
                pixels=image.copy()
            pixels.save(path,icc_profile=icc)
    summary=generate('standard')
    results=load(RUN/'render-results.json'); comparisons=load(RUN/'comparisons.json')
    repeated=load(RUN/'repeatability.json'); issues=[]
    stages=[]
    for p in repeated['rows']:
        if p['engine']!='ours': continue
        actual=[load(RUN/j/'engine-report.json') for j in p['jobs']]
        samples={key:[r['timings'].get(key) for r in actual] for key in
                 ('developMs','orientationMs','exposureMs','lookMs','geometryMs','resizeMs','encodePrepMs','totalPipelineMs','exportTotalMs','renderAndExportMs')}
        nonoverlapping=('developMs','orientationMs','exposureMs','lookMs','geometryMs','resizeMs','encodePrepMs')
        unattributed=[r['timings']['totalPipelineMs']-sum(r['timings'][k] for k in nonoverlapping) for r in actual]
        stages.append({'source_id':p['source_id'],'n':len(actual),'evidence':[j+'/engine-report.json' for j in p['jobs']],
            'median_ms':{k:statistics.median(v) for k,v in samples.items() if all(x is not None for x in v)},
            'samples_ms':samples,'pipeline_executions':[r['timings'].get('pipelineExecutions') for r in actual],
            'unattributed_inside_pipeline_ms':unattributed,'median_unattributed_ms':statistics.median(unattributed),
            'unattributed_scope':'Includes untimed look-encoded -> linear sRGB decode loop plus pipeline overhead; not a direct decode-stage measurement.'})
    write(RUN/'performance-breakdown.json',{'created_at':now(),'engine':'ours','rows':stages,
        'scope':'Existing actual n=3 repeat reports; no extra performance runs or algorithm changes',
        'limits':'Stage timers do not include all process setup, source hashing or diagnostic dump overhead. CLI wall includes JPEG and FP32 dump/write/hash. No mobile/OS-cold/p95 or equivalent-work ranking.',
        'next_step':'Profile actual develop and encode-preparation stages and buffer lifetimes on target devices before optimization; preserve before/after quality and recipe behavior.'})
    for sid,scene in comparisons.items():
        for p in scene['pairs']:
            if p['status']!='COMPARABLE':
                issues.append({'id':f'GEO-{sid}-{p["pair"]}','priority':'P1 review','source_id':sid,
                    'owner':'benchmark / imaging maintainer','status':'BLOCKED_PIXEL_METRICS',
                    'observation':p.get('reason'),'evidence':f'scenes/{sid}.html',
                    'hypothesis':'Framing/demosaic/edge-content differences; integer mapping not sufficiently verified. Not a confirmed engine bug.',
                    'confidence':'High confidence that metric is blocked by the frozen mapping gate; root cause unconfirmed.',
                    'next_step':'Inspect native crops and calibration landmarks. Verify crop offsets/module geometry without resampling; otherwise keep NOT_COMPARABLE.'})
        for flag in scene['triage'].get('flags',[]):
            engine_record=next((r for r in results if r['source_id']==sid and r['engine_id']=='ours'),{})
            stage_report=RUN/engine_record.get('job_id','')/'engine-report.json'
            diagnostics=load(stage_report) if stage_report.is_file() else {}
            issues.append({'id':f'IQ-{sid}-{len(issues)+1}','priority':'P1 review','source_id':sid,
                'owner':'imaging maintainer','status':'REVIEW_REQUIRED','observation':flag,
                'evidence':f'scenes/{sid}.html','hypothesis':'Exposure/WB/camera matrix/downstream clipping differs; references are not ground truth.',
                'confidence':'Threshold exceedance measured on verified overlap; physical color correctness unassessed.',
                'engine_stage_evidence':rel(stage_report) if stage_report.is_file() else None,
                'recorded_highlight_diagnostics':diagnostics.get('highlightDiagnostics'),
                'recorded_exposure_EV':diagnostics.get('resolved',{}).get('exposureEV'),
                'next_step':'Inspect native/matched ROI, validate camera/profile calibration; collect a controlled bracket/chart before changing core algorithms.'})
    for r in results:
        if not output_eligible(r):
            subprocesses=[]
            if r.get('job_id'):
                for p in sorted((RUN/r['job_id']).rglob('process.json')):
                    subprocesses.append({'path':rel(p),'actual_process':load(p)})
            owner='undetermined'
            observation=r.get('reason')
            next_step='Replay same immutable source and saved settings, inspect logs; do not substitute another selected sample silently.'
            if r['source_id']=='R011' and r['engine_id']=='ours':
                owner='input / engine CLI contract'
                observation='init-recipe rejects unresolved as-shot WB: cam_mul R=0, G=1, B=0, G2=0. Publisher CRW has no verified WB; probe succeeds. No render occurred.'
                next_step='Define scope and missing-WB UX/fallback contract; require a verified custom WB or mark unsupported. Do not invent per-image gains for BASE.'
            elif r['source_id']=='R011' and r['engine_id']=='darktable':
                owner='reference decoder / input'
                observation='Default initialization actually attempted and exited 1: Exiv2 unknown image type, RawSpeed No decoder found. Neither default nor BASE export available.'
                next_step='Validate original format/subtype provenance against decoder support. Keep BLOCKED; a default render attempt already failed in the preserved logs.'
            issues.append({'id':f'EXEC-{r["source_id"]}-{r["engine_id"]}','priority':'P0 harness/input investigation',
                'owner':owner,'status':r['execution']['status'],'observation':observation,
                'benchmark_render_status':'BLOCKED' if r['source_id']=='R011' and r['engine_id'] in ('ours','darktable') else r['execution']['status'],
                'evidence':r.get('job_id','scenes/'+r['source_id']+'.html'),
                'actual_subprocess_evidence':subprocesses,'next_step':next_step})
    issues += [
        {'id':'WB-R011','priority':'P1 input / comparator policy','owner':'imaging maintainer','status':'INCONCLUSIVE',
         'observation':'RawTherapee exported R011 with Camera WB policy while ours probe reports invalid cam_mul. RT effective numeric gains/fallback are not instrumented; this output is not evidence of verified as-shot WB.',
         'evidence':'scenes/R011.html','next_step':'Inspect RT source/backend effective gains before claiming equivalent WB. Keep quality NOT_EVALUATED with missing references.'},
        {'id':'COV-01','priority':'P1 scope decision','owner':'product owner / imaging lead','status':'BLOCKED',
         'observation':'Verified portrait, lighting and low-light labels absent. Corpus is a format/camera fixture sample, not representative aesthetic coverage.',
         'evidence':'corpus.manifest.json','next_step':'Approve production camera/scene scope and acquire rights-cleared labeled scenes.'},
        {'id':'COLOR-01','priority':'P1 controlled measurement','owner':'imaging lead','status':'BLOCKED',
         'observation':'NO_VALID_COLOR_REFERENCE; physical color accuracy and recovery stops unassessed.',
         'evidence':'metrics.json','next_step':'Acquire measured chart/brackets with known illumination/reference and ROI.'},
        {'id':'REVIEW-01','priority':'P1 human review','owner':'project owner / reviewer','status':'BLOCKED',
         'observation':'No human blind feedback. Review status remains NOT_REVIEWED.',
         'evidence':'blind/index.html','next_step':'Review all flags, unresolved geometry, and deterministic >=20% nonflagged samples; export feedback JSON.'},
        {'id':'PERF-01','priority':'P2 dedicated profiling','owner':'engine maintainer','status':'OBSERVED_NOT_DEVICE_CERTIFIED',
         'observation':'Desktop n=3 fresh-process timings and sampled process working sets; no OS-cold cache/thermal/mobile/p95 conclusions.',
         'evidence':'repeatability.json','next_step':'Use measured process-stage timings and native buffer lifetimes to prioritize optimization on target devices after scope approval.'},
        {'id':'PERF-02','priority':'P2 timing attribution / transfer profiling','owner':'engine maintainer','status':'OBSERVED_NOT_AN_ALGORITHM_FIX',
         'observation':'totalPipelineMs exceeds the sum of reported nonoverlapping stage timers. Source render.cpp has a look-encoded -> linear sRGB decode loop outside those timers. Residual includes that loop and overhead, not a directly measured decode duration.',
         'evidence':'performance-breakdown.json','source_evidence':'engine/src/render.cpp:171',
         'next_step':'Add separate transfer/decode timing, profile on target devices, then evaluate redundant transfer elimination or vectorization in a separate change with pre-JPEG/recipe/cancellation and before/after baseline checks.'}]
    issues.sort(key=lambda i:(i['priority'].split()[0],i.get('source_id',''),i['id']))
    write(RUN/'issues.json',{'created_at':now(),'items':issues,'repro':'python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage standard --resume',
                           'no_engine_algorithm_changes':True})
    perf=['| RAW | Engine | n | Median s | Range s | Peak sampled MiB (max of 3) | Native pixels identical |',
          '|---|---|---:|---:|---|---:|---|']
    for p in repeated['rows']:
        peak=max((v or 0) for v in p['sampled_peak_working_set_bytes'])/2**20
        perf.append(f"| {p['source_id']} | {p['engine']} | {p['n']} | {p['median_seconds']:.3f} | {p['range_seconds'][0]:.3f}–{p['range_seconds'][1]:.3f} | {peak:.1f} | {p['native_pixels_exactly_identical']} |")
    count=summary['execution_counts']; groups=len({v['scene_session_group'] for v in manifest['items']})
    pair_counts=summary['pairwise_counts']; flags=summary['quality_review_required']
    failed_cases=[r['source_id']+'/'+r['engine_id']+': '+r.get('reason',r['execution']['status']) for r in results if r['execution']['status']!='SUCCESS']
    sha_policy=sha(BASE/'benchmark.policy.json'); unique_raws=len({v['sha256'] for v in manifest['items'] if v['sha256']})
    report=f'''# RAW multi-engine benchmark — bàn giao 01/10/2026

Run: `20261001/run-v1` · Runner: **{summary['runner_status']}** · Scope: **Proposed**.
Policy SHA-256: `{sha_policy}`.

Đã tải/xác minh **{unique_raws}/40 RAW** và thực hiện ma trận xử lý với ours,
darktable 5.6.1 và RawTherapee 5.13. Có **{count.get('SUCCESS',0)} export BASE_CONTROLLED
full resolution thành công**. Execution counts: `{json.dumps(count)}` trên
denominator **120 jobs**. Pairwise: `{json.dumps(pair_counts)}`. Có {groups} nhóm
camera/session thận trọng; **không** gọi đó là {groups} scene độc lập đã xác minh.
Split cố định 28 development / 12 holdout, pilot 12 development trước holdout.

**Chưa nghiệm thu G2.** Human review: NOT_REVIEWED. Hai converter không phải ground truth;
LibRaw có thể là dependency chung. Chưa có chart/reference/lighting hợp lệ để kết luận
độ chính xác màu, dynamic range hay màu đúng của cảnh. Thiếu scope portrait/low-light
được ghi BLOCKED trong issues.json, không gán nhãn từ tên file. X-Trans là exploratory.

## Bằng chứng đã xác minh

- Snapshot source + binary baseline được lưu trước render: baseline.json,
  baseline-source.zip, baseline-photo-cli.exe và smoke/. **Không sửa thuật toán core**;
  hashes source vẫn khớp. Các lỗi thử setup/XMP/path được giữ nguyên ở attempts/logs.
- Từng RAW có evidence CC0 publisher row + URL + hash/byte thật. Original không đổi,
  mỗi job dùng copy độc lập. FiveK: PENDING_LICENSE_REVIEW, không tải.
- Ours đo FP32 production trước JPEG, RT/darktable TIFF RGB 16-bit thật. Native và
  normalized FP32 lossless được giữ; JPEG chỉ cung cấp ICC metadata cho ours.
- LCMS float transform thực, ICC pin bằng hash; H01–H14: {summary['harness_tests']}.
  Test nonidentity gamma độc lập: color-transform-tests.json. Config-effect cả ba:
  {summary['config_effects']}; repeatability: {summary['repeatability']}.
- Geometry chỉ orientation/integer translation/crop có evidence. Không resize/warp
  để tạo metric. Thiếu mapping → NOT_COMPARABLE; không fill missing reference bằng 0.
  Endpoint domain encoded sRGB, Y quantiles linear sRGB; ngưỡng chỉ tạo review.
- Ma trận BMQ01–26, metrics JSON/CSV, đầy đủ planned rows và log/exact argv trong artifact.
  Cache kiểm actual binary/dependency + config/source/profile/normalizer/metric hashes.

## Cần xem / chưa chạy được

Flagged bởi rule thăm dò: `{flags}`. Sample nonflagged để kiểm false negative:
`{summary['quality_not_flagged_sample']}`. Trường hợp mapping bị chặn và toàn bộ issue,
owner/repro/next-step: **issues.json**. Report từng ảnh giữ lỗi và nguyên nhân.
Nhánh không xuất được: `{failed_cases}`. R011/ours: as-shot cam_mul không hợp lệ;
R011/darktable: default init đã thử nhưng decoder không đọc được, BASE bị BLOCKED.
Absolute chart accuracy: **NOT_RUN — NO_VALID_COLOR_REFERENCE (BLOCKED input)**.
Human feedback: **NOT_REVIEWED (BLOCKED reviewer)**. Scope scene/lighting: **UNKNOWN**.
AI đã xem overview R001 và R007, nhãn AI_SUGGESTION, không thay phiếu người dùng.
ASan/UBSan, fuzz và mobile của audit trước được hoãn theo yêu cầu người dùng.
Decoder dependency evidence: decoder-dependencies.json (ours và RT release source
đều LibRaw 0.22.2; RT EnableLibRaw=true; backend fallback theo file chưa instrument).

## Hiệu năng quan sát, n=3

{chr(10).join(perf)}

Process mới ≠ OS/disk cache lạnh. Peak là working set process-tree lấy mẫu ~50ms,
không phải peak tuyệt đối và không phải memory runner Python. Thời gian export mỗi
converter không gồm normalize và lượt darktable sinh history riêng. Pipeline làm
khác lượng công việc, **không dùng bảng này để xếp hạng tối ưu engine**. Không có p95
hay suy luận mobile. Host: i3-10105F, 16 GiB RAM, Windows 10; ứng dụng khác vẫn mở.
Wall time ours bao gồm JPEG + ghi/hash dump FP32 diagnostic, không phải latency
production JPEG-only. Stage timers n=3 của ours: performance-breakdown.json,
trích trực tiếp từ engine-report.json; không trộn vào wall time của converter khác.

## Chạy lại / mở kết quả

HTML offline: **index.html**, gallery: scenes/, blind A/B/C: blind/index.html;
mapping riêng blind-mapping.json, feedback JSON tải tại trang blind. Không CDN.
README.md chứa lệnh chính xác, package/dependency/install evidence và hạn chế.

```powershell
Set-Location -LiteralPath G:\\zalo_mini_app\\app\\photo_engine
python -m raw_benchmark doctor --policy benchmark/benchmark.policy.json
python -m benchmark.check_color_transform
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage pilot --resume
python -m raw_benchmark run --policy benchmark/benchmark.policy.json --stage standard --resume
python -m benchmark.verify_evidence
```

Holdout freeze: holdout.freeze.json; actual source/engine/ICC/metric settings được khóa
trước holdout. Artifact integrity/link/count verification: artifact-verification.json.
Storage compaction, nếu có: storage-deduplication.json, chỉ hardlink derivative đã
xác minh byte-identical; không hardlink RAW, không recompress mất dữ liệu.
historical-storage.json ghi native container cũ được lưu bằng metadata nguyên gốc
+ payload nén byte-identical từ export giữ lại. Manifest *.history.json và README.md
có lệnh khôi phục từng byte; artifact-verification.json kiểm lại SHA toàn container.
Native latest và normalized measurement vẫn là file TIFF/ZIP thông thường.

**Việc kế tiếp quan trọng nhất:** project owner/imaging reviewer xem các case trong
issues.json cùng sample nonflagged và export feedback trước quyết định sửa thuật toán.
'''
    (RUN/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    one_page=f'''# Bàn giao RAW benchmark — 01/10/2026

**Runner {summary['runner_status']} · scope Proposed · chưa nghiệm thu G2.**
Đã lấy {unique_raws}/40 RAW CC0; {count.get('SUCCESS',0)} export BASE_CONTROLLED full
resolution thành công qua ours, darktable 5.6.1 và RawTherapee 5.13.
Planned: 120 jobs; execution: {json.dumps(count)}. Nhánh không xuất được giữ trong denominator.
R011: ours không khởi tạo được as-shot WB; darktable không đọc được file, BASE BLOCKED.
Split 28 development / 12 holdout; {groups} nhóm camera/session thận trọng,
scene độc lập chưa xác minh. Pairwise: {json.dumps(pair_counts)}.

**Baseline giữ nguyên:** snapshot source/binary trước render, source hashes còn khớp.
H01–H14: {summary['harness_tests']}; cấu hình có hiệu lực: {summary['config_effects']};
lặp 3 process mới × 3 fixture × 3 engine: {summary['repeatability']}.
Thời gian/RSS là quan sát desktop, không chứng nhận mobile hoặc xếp hạng cùng công việc.

**Cần xem:** flagged {flags}; sample ≥20% nonflagged {summary['quality_not_flagged_sample']}.
Các cặp NOT_COMPARABLE không có metric pixel. Issue/owner/repro: issues.json.
**BLOCKED:** human reviewer (NOT_REVIEWED), chart/illuminant/reference màu,
scope portrait/lighting/low-light chưa có dữ liệu có căn cứ. Reference không là ground truth.
ASan/UBSan, fuzz, mobile được hoãn theo yêu cầu hiện tại.

**Mở:** index.html (offline), scenes/, blind/index.html. **Chạy lại:** README.md.
Raw logs/argv/config/ICC/hash: từng job; metrics.json/CSV, test_matrix.json,
holdout.freeze.json và artifact-verification.json giữ bằng chứng. Native/FP32 lossless
được giữ; native của attempt cũ có thể khôi phục byte-exact bằng *.history.json.
Không commit/push/upload ảnh. Việc tiếp theo: reviewer xem ảnh và feedback trước sửa core.
'''
    (RUN/'ONE_PAGE_REPORT.md').write_text(one_page,encoding='utf-8')
    docs=ROOT/'docs/qa/MULTI_ENGINE_BENCHMARK_20261001.md'; docs.write_text(report,encoding='utf-8')
    # Refresh links only after their handoff targets exist.
    generate('standard')
    # Save replayable runner/config sources separately from unchanged engine baseline.
    import zipfile
    with zipfile.ZipFile(RUN/'benchmark-source.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for base in (ROOT/'raw_benchmark',BASE):
            for p in sorted(base.rglob('*')):
                if not p.is_file(): continue
                if base==BASE and p.relative_to(BASE).parts[0] in ('tools','python-deps'): continue
                if '__pycache__' in p.parts: continue
                z.write(p,str(p.relative_to(ROOT)))
        z.write(BASE/'tools/downloads.json','benchmark/tools/downloads.json')
        for p in sorted((ROOT/'fixtures/looks/identity-technical-fixture').rglob('*')):
            if p.is_file(): z.write(p,str(p.relative_to(ROOT)))
        cms_root=ROOT/'artifacts/engine-improvements/20261001/reference-lcms'
        for filename in ('lcms2.dll','provenance.json','build.log','lcms2.17.tar.gz'):
            p=cms_root/filename
            z.write(p,str(p.relative_to(ROOT)))
    write(RUN/'delivery-lock.json',{'created_at':now(),'runner_source_zip_sha256':sha(RUN/'benchmark-source.zip'),
         'policy_sha256':sha_policy,'baseline_sha256':sha(RUN/'baseline.json'),
         'core_source_unchanged':summary['core_source_unchanged_from_baseline'],'no_commit_or_push':True})
    print(json.dumps({'runner':summary['runner_status'],'execution':count,'pairs':pair_counts,'issues':len(issues)},indent=2))

if __name__=='__main__': main()
