"""Emit evidence-led status, file hashes and source patch; no acceptance decision."""
import argparse,json,sys,statistics,zipfile,difflib,shutil,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
from raw_benchmark.common import load,write,sha
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve();core=run/'core'
 refs=load(run/'reference/reference-results.json');reg=load(core/'regression.json');preview=load(core/'preview.json');head=load(core/'headroom-analysis.json');pairs=load(run/'comparisons.json')
 if not (run/'mobile-environment.json').exists():
  import os
  write(run/'mobile-environment.json',{'host':platform.platform(),'tools':{n:shutil.which(n) for n in ['adb','sdkmanager','xcodebuild']},
    'sdk_environment':{k:os.environ.get(k) for k in ['ANDROID_HOME','ANDROID_SDK_ROOT','ANDROID_NDK_HOME']},
    'mobile_measurement':'BLOCKED unless SDK and physical device are available; this replay does not measure mobile'})
 original_evidence=ROOT/'artifacts/next-step/run-v2/source-evidence'
 if not (run/'source-evidence').exists() and original_evidence.exists():shutil.copytree(original_evidence,run/'source-evidence')
 assert len(reg)==6 and all(r['status']=='VERIFIED' for r in reg)
 assert len(preview)==9 and all(len(r['rows'])==14 for r in preview)
 assert len(head)==3
 stats=[]
 for sid in ['R025','R039','R001']:
  runs=[r for r in preview if r['id']==sid]
  def values(name):return [next(v['wallRenderMs'] for v in r['rows'] if v['name']==name)/1000 for r in runs]
  peak=max(v['processLifetimePeakWorkingSetBytes'] for r in runs if r['rep']>0 for v in r['rows'])/1024**2
  stats.append({'id':sid,'n':3,'initial_seconds':values('initial'),'warm_look_seconds':values('lookA'),'ev_seconds':values('ev'),'wb_seconds':values('wb'),'peak_MiB_repetitions_without_uncached_validation':peak})
 write(run/'preview-measurements.json',stats)
 source_root=ROOT/'artifacts/multi-engine-benchmark/20261001/run-v1';zip_path=ROOT/'artifacts/review-packages/RAW-review-12-run-v1.zip'
 expected=load(ROOT.parent/'Danh_gia_RAW_Engine_Run_v1/AI_REVIEW_FINDINGS.json')['input_zip_sha256']
 actual_zip=sha(zip_path)
 delivery_hash=load(ROOT/'artifacts/review-packages/RAW-review-12-run-v1.delivery-check.json')['ZIP_SHA256']
 initial_inventory=ROOT/'artifacts/next-step/run-v2/zip-inventory.json'
 assert actual_zip==delivery_hash
 if initial_inventory.exists():assert actual_zip==load(initial_inventory)['sha256']
 zip_identity={'actual_sha256':actual_zip,'original_delivery_sha256':delivery_hash,'review_claim_sha256':expected,
   'review_claim_length':len(expected),'unchanged_since_initial_inventory':initial_inventory.exists(),
   'review_claim_match':actual_zip==expected,'status':'VERIFIED' if actual_zip==expected else 'FAILED_METADATA_IDENTITY',
   'limitation':'Local ZIP matches original delivery and initial investigation inventory. Supplied review JSON identifies a different or malformed hash; equivalence to its claimed ZIP identity is INCONCLUSIVE.'}
 write(run/'review-zip-identity.json',zip_identity)
 items={v['source_id']:v for v in load(source_root/'corpus.manifest.json')['items']}
 for sid in ['R001','R004','R007','R011','R020','R025','R039']:assert sha(source_root/items[sid]['path'])==items[sid]['sha256']
 summary={'review_type':'AI_SUGGESTION','human_review':'NOT_REVIEWED','g2_approved':False,'core_color_policy':'baseline-v0 unchanged',
  'VERIFIED':['RT invalid token root cause on two X-Trans, independently decoded native TIFF before normalization','RT neutral and cumulative BASE settings; valid method observed in verbose log','X-Trans and Bayer configuration effect','Six full-resolution pre-JPEG baseline numerical regressions','Persistent preview cache: look/LUT, exposure, WB invalidation, cancellation, A-B-A, full-size export','Production and diagnostic timing separation','Real stage headroom checkpoints with locked ROI','R011 RAW unpack succeeds while missing as-shot WB rejects recipe'],
  'FAILED':['Original RT X-Trans reference quality (original export execution remains SUCCESS)','Corrected RT X-Trans four-thread repeatability exceeds locked one-code tolerance; final scoped reference uses CPU1 uniformly','Initial preview harness fixture used unsupported LUT dimension 2; rejected before render, retained as failed test evidence'],
  'BLOCKED':['iOS: Windows host has no Xcode/device runtime','Android: no detected SDK/NDK/adb/device','Product approval for new WB fallback or highlight policy remains Proposed'],
  'NOT_RUN':['Remaining corpus rerender outside four-file corrected reference group','GPU implementation','Commercial looks','Physical chart accuracy, sensor DR or recovered stops','G2/human image acceptance'],
  'old_counts_modified':False,'reference_investigation_exports':len(refs),'new_mapping':[{k:r.get(k) for k in ['id','reference_engine','status']} for r in pairs],
  'opened_fixture_ids':['R001','R004','R007','R011','R020','R025','R039'],'review_zip_unchanged_sha256':actual_zip,
  'reference_repeatability_exports':8,'reference_final_cpu1_exports':6,'review_zip_identity':zip_identity}
 if actual_zip!=expected:summary['FAILED'].append('AI review ZIP identity mismatch; local ZIP unchanged, claimed review ZIP identity INCONCLUSIVE')
 write(run/'summary.json',summary)
 lines=['# NEXT_STEP_REPORT — run-v2','',
 'AI_SUGGESTION · Human review NOT_REVIEWED · **G2 chưa được phê duyệt**. Giữ core color baseline-v0; không sửa source RAW, recipe cũ, artifact hay số đếm run-v1. Không commit/push/upload ảnh hoặc dùng dịch vụ trả phí.','',
 '## VERIFIED — nhánh reference','',
 'Root cause R025/R039 đã được cô lập: `Method=3-pass` không khớp token RT 5.13 `3-pass (best)`, đi vào fallback `nodemosaic(false)`. Native TIFF cấu hình cũ giống **từng pixel** với `Method=none`, và tái hiện đúng native run-v1. Lưới/ám xanh đã có tại native TIFF, trước normalization. Sau sửa token, log ghi nhánh X-Trans `3-pass (best)`; PP3 sau khi thêm lại toàn bộ nhóm BASE còn lại khớp, nhưng thử nghiệm phát hiện thêm khác biệt pixel thưa ở 4 thread. Backend loader thực có bằng chứng “provided by libraw”.',
 '[Source RT đúng commit](https://github.com/Beep6581/RawTherapee/blob/1924179107995b01b73cdc7f4fe91e44fc8227a7/rtengine/rawimagesource.cc#L1844) · [token enum](https://github.com/Beep6581/RawTherapee/blob/1924179107995b01b73cdc7f4fe91e44fc8227a7/rtengine/procparams.cc#L3701). Build/version/source hashes và log được giữ trong run.',
 'Đường đọc độc lập libtiff giữ uint16 RGB, so byte-exact với tifffile; sentinel bắt đảo kênh/byte order/hạ 8-bit. LCMS nonidentity 4096 mức kiểm tra lại bằng hàm sRGB độc lập. Native → FP32 normalized → crop cũ khớp pixel. TIFF/FP32 giữ precision; PNG chỉ để xem.',
 f'{len(refs)} export RT điều tra/control, gồm neutral, thêm từng nhóm BASE, old token, none, fixed và EV+1. Config-effect có cả hai X-Trans và hai Bayer R001/R004. Nhóm bốn RAW cũng có ours và darktable chạy lại. Mapping dùng nguyên ba patch, correlation ≥0.80, chỉ integer translation; không warp/resize/nới ngưỡng.',
 'Kiểm chứng bổ sung: nhánh X-Trans 4 thread FAILED ở tolerance một mức uint16 (R025/R039); CPU1 giữ cùng method và khớp pixel qua các lượt lặp. Nhóm RT cuối dùng BASE_CONTROLLED + execution_variant CPU1_REFERENCE đồng nhất cho cả bốn RAW, có config-effect X-Trans/Bayer riêng. Output 4-thread giữ nguyên; eligibility số học của nhánh đó INCONCLUSIVE. Xem rt-repeatability/results.json và rt-stable/results.json; log metadata đợt threading đầu có erratum riêng, không thay pixel/số đo.',
 'Eligibility mới chỉ phục vụ so sánh kỹ thuật trong scope đã kiểm tra, không chứng nhận chất lượng reference hay camera. Export SUCCESS cũ giữ nguyên; anomaly/eligibility của hai reference cũ được ghi riêng trong `reference-trace.json`.','',
 '## VERIFIED — preview và regression','',
 'Cache một frame develop full-resolution đã normalize orientation trên mỗi source handle. Key gồm SHA256 source được kiểm lại, WB resolved, pipeline/version/build. Đổi LUT/amount/EV chỉ chạy downstream; WB đổi thì invalidate develop. Source bị sửa trả ASSET_MISMATCH; source khôi phục replay đúng. Export không dùng preview cache. API vẫn yêu cầu tuần tự trên mỗi source; generation tăng đơn điệu, 0 giữ chế độ không lọc generation.',
 'Sáu RAW so pre-JPEG với v0: max absolute difference = 0. Preview cached/uncached cũng exact ở các trường hợp được kiểm tra; giữ recipe, orientation, alpha=1. R007 orientation flip=5 có kiểm tra riêng. Cancellation lạnh/ấm trả PE_CANCELLED và image=null; A→B→A đúng hash, LUT switch thực có render, export ra full-resolution.',
 '| RAW | n | Mở đầu median (s) | Look warm median (s) | EV median (s) | WB median (s) | Peak MiB* |',
 '|---|---:|---:|---:|---:|---:|---:|']
 for s in stats:lines.append(f'| {s["id"]} | 3 | {statistics.median(s["initial_seconds"]):.3f} | {statistics.median(s["warm_look_seconds"]):.3f} | {statistics.median(s["ev_seconds"]):.3f} | {statistics.median(s["wb_seconds"]):.3f} | {s["peak_MiB_repetitions_without_uncached_validation"]:.1f} |')
 lines += ['', '*Desktop Windows, affinity bốn logical CPU; OS cache không cold, host không độc quyền. Preview 1200px sau develop/look full-res, không phải preview decoder giảm độ phân giải. Peak là lifetime working set của hai repetition không chạy uncached validation; vẫn gồm thao tác ghi evidence ngoài render timer. Lần mở source đo riêng. n nhỏ, không suy p95/mobile; range từng lần ở JSON. Preview ấm còn chậm, cache tăng RAM; chưa phù hợp để tuyên bố latency/RAM mobile.',
 'Timer read metadata/unpack/rawProcess/convert là các phần rời của develop; developMs là aggregate, không cộng hai lần. Transfer encode, LUT, transfer decode, geometry, resize, final encode, export, diagnostic dump/hash tách riêng. rawProcess chưa tách black scaling/demosaic/color matrix; hash source, validation recipe/look, process startup, preview packing là residual ngoài pipeline. Với headroom, rawProcess gồm I/O callback chẩn đoán, **không dùng để so tốc độ production**. Requested quality=3; CFA phân biệt Bayer/X-Trans; effective algorithm của ours = UNKNOWN do chưa instrument dispatch.',
 'Production CLI không scan endpoint chẩn đoán; diagnostic có scan/write/hash riêng, mỗi mode n=3 trên R025/R039. Chênh lệch giữa mode không được gọi là tối ưu thuật toán.','',
 '## VERIFIED quan sát headroom — giới hạn còn lại','',
 'Policy: ours highlight=0 clip-white; RT HLRecovery=false; darktable highlights disabled. Đây không phải ba phép xử lý tương đương. Giữ warning vùng trắng/hồng ở R007/R020; near_white_all thấp không chứng minh reference giữ chi tiết.',
 'ROI highlight/midtone/control được khóa trước thử. Checkpoint thật: D0 trước scale_colors sau black subtraction, D1 sau scale_colors, D2 trước chuyển RGB, D3 sau RGB; B0 sau develop/orientation, sau exposure, B1–B4 tới pre-JPEG. Native descriptor ghi dtype, stride, domain, CFA, WB/black/white và orientation; sparse camera slots không bị gắn nhãn RGB sRGB.',
 'So EV−2 sau develop với giảm mẫu integer camera còn 1/4 tại D0, trước clipping scale_colors. Hai đường có D0 giống nhau; D3 baseline khớp B0 thật; late exposure chỉ là B0×1/4. Thí nghiệm sớm không được ghi vào recipe v0, không phải mode USABLE_RENDER được duyệt. Nó có truncation và thay input demosaic, không phải developer P1 đã hoàn chỉnh.']
 for row in head:
  s=row['scale_colors'];lines.append(f'- {row["id"]}: {s["baseline_endpoint_samples"]:,} sample ở endpoint sau scale_colors baseline; tại cùng vị trí, đường sớm có {s["early_unique_values_where_baseline_clipped"]:,} giá trị khác nhau. Xem crops/ROI và dữ liệu đầy đủ; đây là evidence về stage làm gộp giá trị, không tự chứng minh chi tiết cảnh hữu ích.')
 lines += ['', 'Quan sát AI ở ROI cố định: R007 đường sớm xuất hiện biên/khối dạng mây tại vùng baseline gần phẳng, nhưng hue hồng/magenta vẫn sai lệch; R020 chủ yếu chuyển nền sáng sang magenta, chưa có bằng chứng chắc chắn thêm chi tiết trời. Đây chỉ hỗ trợ nghiên cứu headroom có mục tiêu, không xác nhận màu đúng.',
 'Có bằng chứng kiểm chứng được về giới hạn integer/clipping và sự khác nhau giữa giảm sớm/muộn. Chưa tự nghiệm thu “phục hồi chi tiết” hoặc chấp thuận thay developer. Không tuyên bố sensor DR/số stop recover từ single-shot; không tối toàn ảnh/giảm saturation để đạt tỷ lệ endpoint. Quyết định P1 vẫn Proposed, cần đánh giá cấu trúc/hue trong ROI và kiểm chứng phương án production trước khi đổi baseline.','',
 '## VERIFIED — R011 và policy WB','',
 'R011 open/unpack RAW thành công. Init asShot từ chối rõ `AS_SHOT_WB_UNAVAILABLE`, không tạo recipe, không fallback. Replay thiếu/null hoặc zero gains bị từ chối. Không gán custom gain thử nghiệm cho R011 để giả là asShot. Policy sản phẩm **Proposed**: thông báo chưa hỗ trợ as-shot WB; custom chỉ khi có gain được xác minh; auto nếu thêm cần opt-in và provenance/version riêng.','',
 '## FAILED / BLOCKED / NOT_RUN','',
 '- FAILED: chất lượng hai reference RT cũ, không phải export execution; repeatability X-Trans 4-thread sau sửa token vẫn FAILED, giữ nhánh đó INCONCLUSIVE và dùng group CPU1 riêng. Lượt harness preview đầu dùng LUT 2³ sai contract đã bị từ chối trước render; log giữ ở `core/preview-invalid-fixture`, không tính latency.',
 '- BLOCKED: Android thiếu SDK/NDK/adb/device; iOS trên Windows thiếu Xcode/device runtime. Chưa có số đo mobile. Chưa duyệt policy highlight/WB mới.',
 '- NOT_RUN: rerun phần corpus ngoài nhóm bốn reference; GPU; preset thương mại; chart/physical color accuracy; sensor DR; nghiệm thu G2.','',
 '## Thay đổi theo phạm vi','',
 '- Harness/reference: token RT đúng phiên bản; kiểm token PP3; giữ execution riêng với eligibility; reader độc lập; config-effect hai CFA; logs/hash/crops/report và script tái lập.',
 '- Core/performance: cache develop ở C API preview; generation guard; timers rời và diagnostic opt-in; báo quality/CFA/effective riêng. Cache giữ full-res và không đổi thứ tự toán học.',
 '- Core/color: không đổi phép toán màu production baseline-v0. Callback headroom và early quarter chỉ bật qua C++ harness với audit directory, không có public recipe/CLI fallback.',
 '- Build/UX: loại placeholder LibRaw *_ph.cpp khỏi build đầy đủ; CLI missing-WB có structured error. Giữ C ABI status và recipe schema.',
 '- Holdout: R001/R004/R007/R011/R020/R025/R039 đã mở trong investigation/regression. Giữ split lịch sử, không dùng chúng làm holdout xác nhận tiếp theo.','',
 '## Tái lập và mở demo','',
 'Từ thư mục `photo_engine`, chạy một lệnh (cần corpus/toolchain đã pin đang có trên máy):','',
 '```powershell','powershell -NoProfile -File tools/next_step/run.ps1','```','',
 'Lệnh tạo thư mục replay mới, build/test, nhóm reference + regression/preview/headroom/contracts, rồi HTML. Không ghi đè run-v1/v2. Để mở demo core chạy trong một process:','',
 '```powershell','python tools/next_step/demo.py --run artifacts/next-step/run-v2/core','```','',
 'Mở http://127.0.0.1:8766. Demo chỉ phục vụ loopback, dùng RAW fixture cục bộ, không upload; không phải UI sản phẩm hoàn chỉnh.','',
 '[Report HTML trước–sau](index.html) · [Trạng thái máy đọc](summary.json) · [Timings production/diagnostic](core/performance.json) · [Preview counts](core/preview.json) · [Headroom analysis](core/headroom-analysis.json) · [WB contract](contracts/wb/contract.json) · [Reference trace](reference-trace.json).']
 (run/'NEXT_STEP_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
 if actual_zip!=expected:
  report=run/'NEXT_STEP_REPORT.md'
  with report.open('a',encoding='utf-8') as out:
   out.write('\n\n## FAILED metadata identity — ZIP review\n\n')
   out.write(f'ZIP local SHA256 `{actual_zip}` khớp delivery-check cũ và inventory lúc bắt đầu điều tra. Giá trị trong AI_REVIEW_FINDINGS.json là `{expected}` ({len(expected)} ký tự), không khớp SHA256 local. Không sửa review JSON hay ZIP. Vì vậy identity ZIP được AI review nhắc tới là INCONCLUSIVE; đối chiếu native/crop/source trong báo cáo này dựa trên artifact local có hash đã kiểm chứng. Xem [review-zip-identity.json](review-zip-identity.json).\n')
 # Preserve deliverable source and executables separately from older snapshots.
 snapshot=run/'final-source.zip'
 files=list((ROOT/'benchmark').glob('*.py'))+[p for folder in ['engine','cli','tests','tools/next_step','raw_benchmark','benchmark/configs'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[ROOT/'CMakeLists.txt']
 with zipfile.ZipFile(snapshot,'w',zipfile.ZIP_DEFLATED) as z:
  for file in files:z.write(file,file.relative_to(ROOT))
 write(run/'final-source-hashes.json',{str(f.relative_to(ROOT)):sha(f) for f in files})
 binaries=run/'binaries';binaries.mkdir(exist_ok=True)
 for name in ['photo-cli.exe','next_step_harness.exe','photoengine_tests.exe']:shutil.copyfile(ROOT/'build-next'/name,binaries/name)
 if (run/'source-before.zip').exists():
  diff=[]
  with zipfile.ZipFile(run/'source-before.zip') as z:
   previous=set(z.namelist())
   for file in files:
    rel=str(file.relative_to(ROOT)).replace('\\','/')
    before=z.read(rel).decode('utf-8',errors='replace').splitlines(True) if rel in previous else []
    after=file.read_text(encoding='utf-8',errors='replace').splitlines(True)
    diff.extend(difflib.unified_diff(before,after,'before/'+rel,'after/'+rel))
  (run/'changes.patch').write_text(''.join(diff),encoding='utf-8')
 write(run/'delivery-hashes.json',{str(p.relative_to(run)):sha(p) for p in run.rglob('*') if p.is_file() and p.name!='delivery-hashes.json' and 'demo' not in p.parts})
 print(run/'NEXT_STEP_REPORT.md')
if __name__=='__main__':main()
