"""Export a small, self-contained review subset from an immutable benchmark run.

No renderer is invoked. Measurement buffers, settings and baseline remain unchanged.
"""
from pathlib import Path
import hashlib
import html
import json
import shutil
import zipfile
from collections import Counter
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'artifacts/multi-engine-benchmark/20261001/run-v1'
DEST = ROOT / 'artifacts/review-packages/RAW-review-12-run-v1'
REQUIRED = ['R007', 'R020', 'R011', 'R025', 'R039']
CONTROLS = ['R014', 'R018', 'R009', 'R037', 'R005', 'R036', 'R004']
SELECTED = REQUIRED + CONTROLS
PACKAGE_ID = 'RAW-review-12-run-v1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def esc(value):
    return html.escape(str(value), quote=True)


CSS = '''
:root{color-scheme:dark}body{font:16px system-ui,sans-serif;line-height:1.5;background:#111821;color:#e7edf5;margin:24px auto;padding:0 20px;max-width:1800px}a{color:#9bcaff}h1,h2,h3{line-height:1.25}header{position:sticky;top:0;background:#111821ee;padding:12px 0;z-index:2;border-bottom:1px solid #394554}button,select,input,textarea{font:inherit;padding:8px;background:#223040;color:#e7edf5;border:1px solid #66778a;border-radius:4px}button{cursor:pointer}textarea{width:95%;min-height:84px}label{display:block;margin:10px 0}table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #425066}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.panel{background:#1c2938;padding:16px;border-radius:8px;min-width:0}.overview{display:block;width:100%;height:auto;max-height:700px;object-fit:contain;background:#0a1118}.scroll{overflow:auto;background:#101720}.crop{display:block;width:512px;height:512px;max-width:none;object-fit:none}.badge{display:inline-block;border:1px solid #8594a8;padding:3px 8px}.warning{color:#ffd48b}.muted{color:#b7c4d3}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#202d3c;padding:14px}.fieldrow{display:flex;gap:12px;flex-wrap:wrap}details{margin:14px 0}.notice{padding:12px;border-left:3px solid #83b9ed;background:#1c2938}@media(max-width:1000px){.grid{grid-template-columns:1fr}.pair{grid-template-columns:1fr}body{padding:0 12px}}
'''

JS = r'''
const packageId='RAW-review-12-run-v1', storageKey=packageId+'-feedback';
const sourceIds=['R007','R020','R011','R025','R039','R014','R018','R009','R037','R005','R036','R004'];
let state={schema_version:1,package_id:packageId,reviewer:'',cases:{}};
const memoryWarning=document.getElementById('save-status');
try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved&&saved.package_id===packageId)state=saved;}catch(e){memoryWarning.textContent='Trình duyệt không cho lưu tự động. Hãy tải JSON trước khi rời trang.';}
function persist(){try{localStorage.setItem(storageKey,JSON.stringify(state));memoryWarning.textContent='Đã lưu trên trình duyệt này. Tải JSON để bàn giao.';}catch(e){memoryWarning.textContent='Không lưu tự động được; hãy tải JSON trước khi rời trang.';}updateProgress();}
function updateProgress(){let n=0;for(const sid of sourceIds)for(const a of ['A','B','C'])if(state.cases[sid]?.[a]?.assessment&&state.cases[sid][a].assessment!=='UNREVIEWED')n++;const el=document.getElementById('progress');if(el)el.textContent=n+'/36 ô đã ghi nhận';}
for(const input of document.querySelectorAll('[data-feedback]')){
 const sid=input.dataset.scene,alias=input.dataset.alias,field=input.dataset.field;
 input.value=state.cases[sid]?.[alias]?.[field]||input.value;
 input.addEventListener('input',()=>{state.cases[sid]??={};state.cases[sid][alias]??={};state.cases[sid][alias][field]=input.value;persist();});
}
const reviewer=document.getElementById('reviewer');reviewer.value=state.reviewer||'';reviewer.addEventListener('input',()=>{state.reviewer=reviewer.value;persist();});
document.getElementById('export').addEventListener('click',()=>{
 const cases=sourceIds.map(sid=>({source_id:sid,aliases:['A','B','C'].map(alias=>({alias,assessment:'UNREVIEWED',severity:'UNSET',notes:'',...state.cases[sid]?.[alias]}))}));
 const data={schema_version:1,package_id:packageId,reviewer:state.reviewer,created_at:new Date().toISOString(),status:'HUMAN_FEEDBACK_PENDING_TRIAGE',cases};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=packageId+'-feedback.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
 document.getElementById('export-status').textContent='Đã yêu cầu tải file JSON. Kiểm tra thư mục Downloads trước khi đóng trang.';
});
updateProgress();
'''

VERIFY_SCRIPT = r'''"""Offline standard-library check: python verify_package.py"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import hashlib, json, sys
root=Path(__file__).resolve().parent
manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
errors=[];checks=0
for item in manifest['files']:
 p=root/item['path'];checks+=1
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:errors.append('Hash/file: '+item['path'])
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  for k,v in attrs:
   if k in ('src','href') and v:self.links.append(v)
for page in root.rglob('*.html'):
 parser=Links();parser.feed(page.read_text(encoding='utf-8'))
 for ref in parser.links:
  if ref.startswith('#'):continue
  checks+=1;parts=urlsplit(ref)
  if parts.scheme or parts.netloc:errors.append('External dependency: '+str(page.relative_to(root))+': '+ref);continue
  p=(page.parent/unquote(parts.path)).resolve()
  if not p.is_relative_to(root.resolve()) or not p.exists():errors.append('Broken link: '+str(page.relative_to(root))+': '+ref)
result={'status':'PASS' if not errors else 'FAIL','checks':checks,'errors':errors,'limitation':'Integrity/link check; image-quality acceptance requires a reviewer.'}
print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(bool(errors))
'''


def page(path, title, body, reviewer=False, prefix=''):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    script = f'<script src="{prefix}review.js"></script>' if reviewer else ''
    Path(path).write_text('<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(title)}</title><link rel="stylesheet" href="{prefix}style.css"></head>'
        f'<body>{body}{script}</body></html>', encoding='utf-8')


def controls(prefix=''):
    return f'''<header><a href="{prefix}index.html">← Danh sách 12 ảnh</a>
      <div class="fieldrow"><label>Người review <input id="reviewer" autocomplete="name"></label>
      <button id="export" type="button">Tải nhận xét JSON</button><span id="progress"></span></div>
      <small id="save-status">Nhận xét chưa được gửi đi.</small><p id="export-status" aria-live="polite"></p></header>'''


def form(sid, alias):
    attrs = f'data-feedback data-scene="{sid}" data-alias="{alias}"'
    return f'''<label>Đánh giá {alias}
      <select {attrs} data-field="assessment">
      <option value="UNREVIEWED">Chưa xem</option><option value="NO_OBVIOUS_DEFECT">Chưa thấy lỗi rõ</option>
      <option value="DEFECT_OBSERVED">Có dấu hiệu lỗi</option><option value="PREFERENCE_ONLY">Khác biệt / sở thích màu</option>
      <option value="INSUFFICIENT_EVIDENCE">Chưa đủ bằng chứng</option><option value="NO_OUTPUT">Không có ảnh</option></select></label>
      <label>Mức ảnh hưởng <select {attrs} data-field="severity"><option value="UNSET">Chưa xác định</option>
      <option value="NONE">Không thấy</option><option value="LOW">Nhẹ</option><option value="MEDIUM">Vừa</option>
      <option value="HIGH">Nặng</option></select></label>
      <label>Nhận xét / vùng ảnh / crop / alias ưu tiên
      <textarea {attrs} data-field="notes" placeholder="Ví dụ: vùng sáng mất chi tiết; nhiễu; viền màu; texture; sở thích. Ghi rõ vị trí và bằng chứng."></textarea></label>'''


def main():
    rows = read(RUN/'render-results.json')
    comparisons = read(RUN/'comparisons.json')
    manifest = read(RUN/'corpus.manifest.json')
    mapping = read(RUN/'blind-mapping.json')['mapping']
    baseline = read(RUN/'baseline.json')
    assert all(sha(ROOT/p) == digest for p, digest in baseline['source_hashes'].items())
    assert len(SELECTED) == len(set(SELECTED)) == 12
    assert all(comparisons[s]['triage']['quality_triage'] == 'NO_FLAG' for s in CONTROLS)
    subset = [r for r in rows if r['source_id'] in SELECTED]
    assert len(subset) == 36
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST/'assets').mkdir(exist_ok=True)
    (DEST/'curator').mkdir(exist_ok=True)
    (DEST/'style.css').write_text(CSS, encoding='utf-8')
    (DEST/'review.js').write_text(JS, encoding='utf-8')
    (DEST/'verify_package.py').write_text(VERIFY_SCRIPT, encoding='utf-8')
    provenance = []
    source_copies = []

    def copy(src, rel):
        target = DEST/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        source_copies.append({'source':str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
                              'path':rel,'sha256':sha(src)})
        return rel

    def asset(src, kind):
        original_hash = sha(src)
        suffix = '.jpg' if kind == 'overview' else '.png'
        rel = 'assets/'+original_hash+suffix
        dst = DEST/rel
        with Image.open(src) as image:
            dimensions = list(image.size)
            icc = image.info.get('icc_profile')
            if not dst.exists():
                if kind == 'overview':
                    image.convert('RGB').save(dst, quality=85, subsampling=0, optimize=True, icc_profile=icc)
                else:
                    shutil.copyfile(src, dst)
            with Image.open(dst) as output:
                assert list(output.size) == dimensions
                assert output.info.get('icc_profile') == icc
                if kind != 'overview':
                    assert sha(dst) == original_hash
                    assert output.tobytes() == image.tobytes()
        provenance.append({'source':src.relative_to(RUN).as_posix(), 'source_sha256':original_hash,
            'path':rel, 'sha256':sha(dst), 'kind':kind, 'dimensions':dimensions,
            'transform':'existing overview PNG → JPEG quality85 4:4:4; dimensions and ICC preserved' if kind == 'overview' else 'byte-exact original PNG; no resize/re-encode',
            'icc_sha256':hashlib.sha256(icc).hexdigest() if icc else None})
        return rel

    def img(rel, crop=False):
        return f'<div class="scroll"><img class="{"crop" if crop else "overview"}" loading="lazy" decoding="async" src="../{rel}" alt="{"Crop 100%: 1 pixel ảnh = 1 CSS pixel ở zoom 100%" if crop else "Toàn cảnh sRGB, JPEG xem nhẹ"}"></div>'

    selection = {'package_id':PACKAGE_ID, 'baseline_run':'20261001/run-v1', 'required_cases':REQUIRED,
        'NO_FLAG_controls':CONTROLS, 'selection_method':'Reuse the seven genuinely NO_FLAG cases from the previously frozen/report-selected nonflagged review sample; exclude R011 already in required cases. No selection from visual quality.',
        'limitations':'Subset chosen for review, not a new independent statistical benchmark. NO_FLAG is exploratory triage, not acceptance.',
        'expected_job_counts':dict(Counter(r['execution']['status'] for r in subset)),
        'expected_pair_counts':dict(Counter(q['status'] for s in SELECTED for q in comparisons[s]['pairs']))}
    write(DEST/'curator/selection.json', selection)
    write(DEST/'curator/alias-mapping.json', {'mapping':{s:mapping[s] for s in SELECTED},
          'note':'Reveal only after blind feedback has been exported; aliases vary by scene.'})
    write(DEST/'evidence/render-results.json', subset)
    write(DEST/'evidence/comparisons.json', {s:comparisons[s] for s in SELECTED})
    write(DEST/'evidence/corpus.manifest.json', {'items':[i for i in manifest['items'] if i['source_id'] in SELECTED], 'coverage_gaps':manifest['coverage_gaps']})
    write(DEST/'evidence/metrics.json', {'records':[{'source_id':r['source_id'],'engine':r['engine_id'],'execution':r['execution']['status'],'metrics':r.get('metrics')} for r in subset], 'limitation':'Metric values copied unchanged from baseline; JPEGs in this review bundle are not measurement input.'})
    for name in ['summary.json','FINAL_REPORT.md','ONE_PAGE_REPORT.md','engines.lock.json','environment.json',
                 'baseline.json','holdout.freeze.json','artifact-verification.json','harness-errata.json',
                 'repeatability.json','performance-breakdown.json','issues.json','decoder-dependencies.json',
                 'profile-contract-evidence.json','color-transform-tests.json','config-effects.json','harness-tests.json']:
        copy(RUN/name, 'evidence/context/'+name)
    copy(ROOT/'benchmark/benchmark.policy.json', 'evidence/benchmark.policy.json')
    copy(ROOT.parent/'RAW_Engine_MultiEngine_Benchmark_v1/BENCHMARK_PROTOCOL.md', 'evidence/BENCHMARK_PROTOCOL.md')
    for f in (ROOT/'fixtures/looks/identity-technical-fixture').iterdir():
        if f.is_file(): copy(f, 'evidence/identity-look/'+f.name)

    evidence_rows = []
    safe_suffixes = {'.json','.log','.xmp','.pp3','.icc','.icm','.txt','.rc'}
    for r in subset:
        sid, engine = r['source_id'], r['engine_id']
        folder = RUN/r['job_id']
        for f in sorted(folder.rglob('*')):
            if f.is_file() and (f.suffix.lower() in safe_suffixes or f.name in ('darktablerc','darktablerc-common')):
                assert f.stat().st_size < 5*1024*1024, f
                copy(f, f'evidence/jobs/{sid}/{engine}/'+f.relative_to(folder).as_posix())
        alias = next(a for a, e in mapping[sid].items() if e == engine)
        evidence_rows.append(f'<tr><td>{sid}</td><td>{alias}</td><td>{engine}</td><td>{esc(r["execution"]["status"])}</td>'
                            f'<td><a href="jobs/{sid}/{engine}/result.json">Result / số đo / cấu hình / argv gốc</a></td></tr>')
    review_sections = []
    for sid in SELECTED:
        item = next(i for i in manifest['items'] if i['source_id'] == sid)
        by_engine = {r['engine_id']:r for r in subset if r['source_id'] == sid}
        reverse = {e:a for a,e in mapping[sid].items()}
        body = controls('../')+f'<h1>{sid} · {esc(item["make"])} {esc(item["model"])}</h1>'
        body += '<p class="notice">Alias A/B/C thay đổi theo từng ảnh. Toàn cảnh là JPEG xem nhẹ; crop PNG giữ nguyên 512 × 512 pixel. Đặt zoom trình duyệt 100% để xem crop ở 1:1 CSS pixel. Các converter là nguồn đối chiếu; chưa có ground truth màu.</p><div class="grid">'
        for alias in ['A','B','C']:
            r = by_engine[mapping[sid][alias]]
            body += f'<section class="panel"><h2>{alias}</h2><span class="badge">{esc(r["execution"]["status"])}</span>'
            if r['execution']['status'] == 'SUCCESS':
                body += '<h3>Toàn cảnh</h3>'+img(asset(RUN/r['job_id']/'overview.png','overview'))
                for roi in r['metrics']['rois']:
                    body += f'<h3>Crop độc lập: {esc(roi["label"])}</h3>'+img(asset(RUN/roi['path'],'crop'),True)
                    body += '<p class="muted">Tọa độ [x, y, w, h] trên ảnh native đã định hướng: '+esc(roi['native_pixel_rectangle'])+'. Vùng này chưa mặc nhiên tương ứng giữa các alias.</p>'
                m, d, e = r['metrics'], r['descriptor'], r['execution']
                alias_metrics = {'native_size':[d['width'],d['height']], 'near_white_any':m['endpoints']['near_white_any'],
                    'near_white_all':m['endpoints']['near_white_all'], 'near_black_all':m['endpoints']['near_black_all'],
                    'linear_Y_quantiles':m['linear_Y_quantiles'], 'wall_seconds':e.get('wall_seconds'),
                    'peak_sampled_working_set_MiB':e.get('peak_memory_bytes',0)/2**20}
                body += '<details><summary>Số đo của alias (khác biệt chưa phải lỗi)</summary><pre>'+esc(json.dumps(alias_metrics,ensure_ascii=False,indent=2))+'</pre><p>Thời gian / bộ nhớ là một lượt desktop, khác lượng công việc; chưa dùng để xếp hạng. Near-white/black là ngưỡng thăm dò.</p></details>'
            else:
                reason = ('Không xuất được ảnh: as-shot white balance không xác định được vì cam_mul không hợp lệ. Khởi tạo recipe thất bại; chưa render.' if r['execution']['status']=='FAILED' else
                          'Không xuất được ảnh: bước khởi tạo mặc định thất bại vì decoder không đọc được file RAW; export bị BLOCKED.')
                body += '<p class="warning">'+esc(reason)+'</p><p>Giữ nguyên trạng thái và nguyên nhân. Log nguyên văn có trong evidence, mở sau khi hoàn thành review ẩn tên.</p>'
            body += form(sid,alias)+'</section>'
        body += '</div><h2>Crop cùng vùng đã xác minh</h2><p>Chỉ dùng mapping orientation + dịch pixel nguyên đã PASS trong baseline; không resize/warp. Tọa độ dưới đây thuộc lưới ảnh đã định hướng.</p>'
        for q in comparisons[sid]['pairs']:
            engine_a, engine_b = q['pair'].split('-')
            alias_a, alias_b = reverse[engine_a], reverse[engine_b]
            body += f'<section class="panel"><h3>{alias_a} ↔ {alias_b} · {q["status"]}</h3>'
            if q['status'] == 'COMPARABLE':
                dx, dy = q['offset_B_minus_A']
                ox, oy, w, h = q['matched_roi']['overlap_rectangle']
                mx, my = q['mask_A'][:2]
                rectangle_a = [mx+ox, my+oy, w, h]
                rectangle_b = [mx+ox+dx, my+oy+dy, w, h]
                body += '<div class="pair">'+f'<div><h3>{alias_a}</h3>'+img(asset(RUN/q['matched_roi']['A_path'],'matched-crop'),True)+f'<p>Tọa độ: {rectangle_a}</p></div>'
                body += f'<div><h3>{alias_b}</h3>'+img(asset(RUN/q['matched_roi']['B_path'],'matched-crop'),True)+f'<p>Tọa độ: {rectangle_b}</p></div></div>'
                neutral_q = {'status':q['status'], 'alias_pair':[alias_a,alias_b], 'offset_second_minus_first':q['offset_B_minus_A'],
                    'MAE':q['MAE'], 'RMSE':q['RMSE'], 'units':q['units'], 'geometry_evidence':q['evidence']}
                body += '<details><summary>Số đo / bằng chứng mapping</summary><pre>'+esc(json.dumps(neutral_q,ensure_ascii=False,indent=2))+'</pre></details>'
            else:
                reason = 'Thiếu ảnh đầu ra ở ít nhất một alias; không có metric pixel.' if q['status']=='PARTIAL_REFERENCE' else 'Ba patch chưa cùng xác minh được mapping hoặc correlation dưới 0,80. Chỉ xem crop độc lập ở trên; không có metric pixel cho cặp này.'
                body += '<p class="warning">'+reason+'</p>'
            body += '</section>'
        position = SELECTED.index(sid)
        nav = []
        if position: nav.append(f'<a href="{SELECTED[position-1]}.html">← {SELECTED[position-1]}</a>')
        if position < len(SELECTED)-1: nav.append(f'<a href="{SELECTED[position+1]}.html">{SELECTED[position+1]} →</a>')
        body += '<p>'+' · '.join(nav)+'</p>'
        # One document owns every feedback field: file:// storage is not reliably
        # shared between pages, so the primary standalone UI must remain single-page.
        section = body[len(controls('../')):]
        section = section.replace('src="../assets/', 'src="assets/')
        for source_id in SELECTED:
            section = section.replace(f'href="{source_id}.html"', f'href="#{source_id}"')
        review_sections.append(f'<section id="{sid}" data-scene="{sid}">{section}</section>')
        evidence_scene = '<p><a href="../index.html#'+sid+'">← Ghi nhận xét tại trang review chính</a></p>'+body[len(controls('../')):]
        for alias in ['A','B','C']:
            evidence_scene = evidence_scene.replace(form(sid,alias), '')
        page(DEST/'scenes'/f'{sid}.html', sid+' · A/B/C views', evidence_scene,False,'../')
        print('Exported', sid, flush=True)

    intro = controls()+'<h1>RAW · Review 12 ảnh A/B/C</h1><p>Gói offline: giải nén toàn bộ, mở index.html. Không cần server, cài thư viện hoặc kết nối mạng.</p>'
    intro += '<p class="notice">Xem toàn cảnh, ba crop độc lập và crop cặp cùng vùng đã xác minh. Phân biệt dấu hiệu lỗi với sở thích màu; ghi rõ vị trí. NO_FLAG chưa có nghĩa là ảnh đã được nghiệm thu. Nhận xét được lưu cục bộ nếu trình duyệt cho phép; luôn tải JSON để bàn giao.</p>'
    intro += '<p>Ảnh toàn cảnh: JPEG quality 85, sRGB, giữ kích thước preview và ICC. Crop: PNG byte-exact, 100% lưới pixel; zoom trình duyệt 100%. Measurement FP32/TIFF gốc nằm trong bộ benchmark đầy đủ.</p><table><thead><tr><th>Ảnh</th><th>Máy ảnh</th><th>A/B/C</th></tr></thead><tbody>'
    for sid in SELECTED:
        item = next(i for i in manifest['items'] if i['source_id'] == sid)
        intro += f'<tr><td><a href="#{sid}">{sid}</a></td><td>{esc(item["make"])} {esc(item["model"])}</td><td><a href="#{sid}">Xem và ghi nhận xét</a></td></tr>'
    intro += '</tbody></table><details><summary>Hướng dẫn hoàn tất review</summary><p>Tải JSON nhận xét trước khi mở evidence/index.html hoặc curator/alias-mapping.json. Hai nơi này có tên engine. Mỗi alias chỉ có ý nghĩa trong một ảnh.</p></details>'
    page(DEST/'index.html','RAW · Review 12 ảnh A/B/C',intro+''.join(review_sections),True)
    evidence_body = '<h1>Bằng chứng kỹ thuật · có tên engine</h1><p class="warning">Mở phần này sau khi đã tải nhận xét A/B/C. Chứa cấu hình, log nguyên văn và mapping.</p><p><a href="../index.html">Trang review</a> · <a href="../curator/alias-mapping.json">Mapping A/B/C</a> · <a href="../curator/selection.json">Cách chọn 12 trường hợp</a></p>'
    evidence_body += '<p>Trường hợp lỗi giữ result.json và toàn bộ subprocess logs thực. Các đường dẫn trong argv/result gốc là provenance của máy benchmark, không phải đường dẫn cần có để mở gói này.</p><table><tr><th>Ảnh</th><th>Alias</th><th>Engine</th><th>Trạng thái</th><th>Bằng chứng</th></tr>'+''.join(evidence_rows)+'</table><h2>Toàn bộ file bằng chứng trong gói</h2><ul>'
    for f in sorted((DEST/'evidence').rglob('*')):
        if f.is_file():
            rel = f.relative_to(DEST/'evidence').as_posix()
            evidence_body += f'<li><a href="{esc(rel)}">{esc(rel)}</a></li>'
    evidence_body += '</ul>'
    page(DEST/'evidence/index.html','Bằng chứng kỹ thuật',evidence_body,False,'../')
    write(DEST/'curator/media-provenance.json',provenance)
    write(DEST/'curator/source-copy-provenance.json',source_copies)
    write(DEST/'feedback-template.json', {'schema_version':1,'package_id':PACKAGE_ID,'reviewer':'','status':'NOT_REVIEWED',
        'cases':[{'source_id':s,'aliases':[{'alias':a,'assessment':'UNREVIEWED','severity':'UNSET','notes':''} for a in 'ABC']} for s in SELECTED]})
    readme = '''# RAW review · 12 cases · baseline run-v1

Giải nén toàn bộ ZIP rồi mở **index.html** bằng trình duyệt. Không cần mạng/server/Python.
Trang chính chứa cả 12 ảnh và toàn bộ bảng nhận xét trong cùng một HTML để hoạt động
độc lập qua file://. Mở từng ảnh, đặt zoom 100%, xem toàn cảnh và crop; điền nhận xét A/B/C rồi bấm
**Tải nhận xét JSON**. Kiểm tra file đã tải trước khi đóng trình duyệt. Nếu localStorage
không hoạt động với file://, tải JSON trước khi đóng trang; feedback-template.json
cũng có thể điền bằng tay. Đổi vị trí giải nén/trình duyệt có thể mất dữ liệu lưu cục bộ.

Chỉ sau khi ghi nhận xét mới mở **evidence/index.html** hoặc curator/alias-mapping.json:
chúng có tên engine. Bảng review, tên media và dữ liệu JS dùng alias; alias thay đổi
theo từng trường hợp. Các log nguyên văn có thể nhận diện engine; giữ chúng riêng
trong evidence để bảo toàn bằng chứng. Đây là ẩn tên trong giao diện, không phải cơ chế
bảo mật đối với người chủ động đọc thư mục bằng chứng.

5 trường hợp yêu cầu: R007, R020, R011, R025, R039.
7 NO_FLAG: R014, R018, R009, R037, R005, R036, R004; lấy từ sample review đã lưu trước.
Không chọn lại dựa vào ảnh đẹp/xấu. NO_FLAG không phải chấp nhận chất lượng.

34 output có ảnh, 1 FAILED, 1 BLOCKED. R011 giữ nguyên lỗi init WB và lỗi decoder.
29 cặp COMPARABLE, 4 NOT_COMPARABLE, 3 PARTIAL_REFERENCE; cặp chưa xác minh mapping
không có crop giả cùng vùng và không có metric pixel. Ba crop độc lập ở center,
top-left, bottom-right là ứng viên quan sát; không mặc nhiên cùng vùng giữa engine.

Toàn cảnh dùng JPEG quality85 4:4:4 từ preview sRGB có sẵn, giữ kích thước/ICC, tối đa
1600px cạnh dài. JPEG chỉ để nhìn tổng thể, không đo nhiễu/chi tiết/độ chính xác màu.
Crop PNG giữ byte-exact từ baseline; 512x512 pixel, không resize hoặc nén mất dữ liệu.
Mỗi pixel crop = 1 CSS pixel khi zoom 100%; màn hình HiDPI có thể dùng nhiều pixel vật lý.
Media trùng byte được lưu một lần, không thay đổi vùng ảnh hoặc số đo.

Số đo, settings, argv, hashes, original stdout/stderr và process records được giữ.
Root full-run reports/verification trong evidence/context là ngữ cảnh 40 RAW, không
phải chứng nhận chất lượng riêng cho 12 case. Record gốc có thể chứa đường dẫn máy
benchmark và đường dẫn native RAW/FP32/TIFF không nằm trong ZIP; chúng là provenance.
ZIP này phục vụ review độc lập; để rerender cần repository, RAW, binaries và README
của benchmark đầy đủ. Không chứa RAW/native full-res/JPEG output full-res để giữ gọn.
Không sửa engine hoặc chạy lại renderer để tạo gói. Baseline giữ nguyên.

Nếu có Python, có thể kiểm tra file/hash/liên kết offline:
    python verify_package.py

Kiểm tra nguồn/media, hash/liên kết và logic nhập/xuất JSON đã PASS. Kiểm tra giao diện
bằng trình duyệt tự động: BLOCKED vì công cụ chặn file://; việc render giao diện và
download thực trong trình duyệt chưa được kiểm chứng. Không dùng workaround để vượt
chính sách trình duyệt. Xem package-verification.json để biết phạm vi kiểm tra thực.

Các giới hạn baseline còn nguyên: references không phải ground truth, chart/reference
màu và human acceptance chưa hoàn tất. ASan/UBSan/fuzz/mobile được hoãn theo yêu cầu.
'''
    (DEST/'README.md').write_text(readme,encoding='utf-8')
    copy(Path(__file__), 'curator/export_review.py')
    assert all(sha(ROOT/p) == digest for p,digest in baseline['source_hashes'].items())
    files = [{'path':f.relative_to(DEST).as_posix(),'bytes':f.stat().st_size,'sha256':sha(f)}
             for f in sorted(DEST.rglob('*')) if f.is_file() and f.name != 'package-manifest.json']
    write(DEST/'package-manifest.json', {'package_id':PACKAGE_ID,'selected_sources':SELECTED,'files':files,
        'execution_counts':selection['expected_job_counts'],'pair_counts':selection['expected_pair_counts'],
        'media_reference_count':len(provenance),'unique_media_count':len({a['path'] for a in provenance}),
        'baseline_core_unchanged':True})
    zip_path = DEST.with_suffix('.zip')
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(DEST.rglob('*')):
            if f.is_file(): z.write(f, DEST.name+'/'+f.relative_to(DEST).as_posix())
    with zipfile.ZipFile(zip_path) as z: assert z.testzip() is None
    assert zip_path.stat().st_size < 64*1024*1024, 'Package exceeded 64 MiB size target'
    write(zip_path.with_suffix('.delivery.json'), {'zip':zip_path.name,'sha256':sha(zip_path),
        'bytes':zip_path.stat().st_size,'MiB':zip_path.stat().st_size/2**20,'source_root':str(DEST),
        'execution_counts':selection['expected_job_counts'],'pair_counts':selection['expected_pair_counts']})
    print(json.dumps({'zip':str(zip_path),'MiB':zip_path.stat().st_size/2**20,
        'media_references':len(provenance),'unique_media':len({a['path'] for a in provenance}),
        'execution_counts':selection['expected_job_counts'],'pair_counts':selection['expected_pair_counts']},indent=2),flush=True)


if __name__ == '__main__':
    main()
