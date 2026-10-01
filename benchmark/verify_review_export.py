"""Verify source fidelity and standalone review subset without modifying baseline."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import subprocess
from PIL import Image
from .export_review import ROOT, RUN, DEST, SELECTED, REQUIRED, CONTROLS, sha, read, write


def main():
    checks = []
    def check(name, condition):
        checks.append({'name':name,'status':'PASS' if condition else 'FAIL'})
        if not condition: raise AssertionError(name)
    manifest = read(DEST/'package-manifest.json')
    check('12 cases exactly match the required five plus seven fixed controls',manifest['selected_sources']==SELECTED and len(set(SELECTED))==12)
    comparisons = read(RUN/'comparisons.json')
    for sid in CONTROLS: check(sid+' is actually NO_FLAG',comparisons[sid]['triage']['quality_triage']=='NO_FLAG')
    check('36 planned rows with 34 success + 1 failed + 1 blocked',manifest['execution_counts']=={'SUCCESS':34,'FAILED':1,'BLOCKED':1})
    check('29 verified pairs + 4 mapping blocked + 3 missing reference',manifest['pair_counts']=={'COMPARABLE':29,'NOT_COMPARABLE':4,'PARTIAL_REFERENCE':3})
    data = read(DEST/'curator/media-provenance.json')
    for item in data:
        source = RUN/item['source']; target = DEST/item['path']
        check('media source hash: '+item['source'],sha(source)==item['source_sha256'])
        check('packaged media hash: '+item['path'],sha(target)==item['sha256'])
        with Image.open(source) as a, Image.open(target) as b:
            check('dimensions/ICC: '+item['path'],a.size==b.size and a.info.get('icc_profile')==b.info.get('icc_profile'))
            if item['kind']!='overview':
                check('byte-exact native crop: '+item['path'],sha(source)==sha(target) and a.tobytes()==b.tobytes() and a.size==(512,512))
    for entry in read(DEST/'curator/source-copy-provenance.json'):
        source=ROOT/entry['source'];target=DEST/entry['path']
        check('unaltered evidence: '+entry['path'],sha(source)==entry['sha256']==sha(target))
    text=(DEST/'index.html').read_text(encoding='utf-8')
    script=(DEST/'review.js').read_text(encoding='utf-8')
    for identity in ['darktable','rawtherapee','photo-cli','LibRaw']:
        check('identity hidden from primary HTML/JS: '+identity,identity.lower() not in (text+script).lower())
    check('single offline document contains 36 feedback cells',text.count('<textarea')==36 and text.count('data-field="assessment"')==36 and text.count('data-field="severity"')==36)
    check('all 12 review scenes in primary HTML',all(text.count('id="'+sid+'"')==1 for sid in SELECTED))
    check('34 overviews + 102 independent crops + 58 verified matched crops',text.count('class="overview"')==34 and text.count('class="crop"')==160)
    for row in read(DEST/'evidence/render-results.json'):
        if row['source_id']=='R011' and row['execution']['status']!='SUCCESS':
            folder=DEST/'evidence/jobs'/row['source_id']/row['engine_id']
            check('R011 preserves '+row['engine_id']+' process/logs',any(folder.rglob('process.json')) and any(folder.rglob('stderr.log')))
    baseline=read(RUN/'baseline.json')
    for source, digest in baseline['source_hashes'].items():check('baseline core unchanged: '+source,sha(ROOT/source)==digest)
    for item in read(DEST/'evidence/corpus.manifest.json')['items']:
        check('original RAW unchanged: '+item['source_id'],sha(RUN/item['path'])==item['sha256'])
    feedback=subprocess.run(['node',str(ROOT/'benchmark/review_feedback_check.cjs'),str(DEST)],text=True,capture_output=True,check=True)
    feedback_result=json.loads(feedback.stdout)
    check('feedback JS interaction and export checks',feedback_result['status']=='PASS')
    copy=DEST/'curator/review_feedback_check.cjs';copy.write_bytes((ROOT/'benchmark/review_feedback_check.cjs').read_bytes())
    (DEST/'curator/verify_review_export.py').write_bytes(Path(__file__).read_bytes())
    offline=subprocess.run(['python',str(DEST/'verify_package.py')],text=True,capture_output=True,check=True)
    write(DEST/'package-verification.json',{'status':'PASS','checks':len(checks),'results':checks,
        'offline_hash_link_check':json.loads(offline.stdout),'feedback_js':feedback_result,
        'visual_browser_QA':{'status':'BLOCKED','reason':'Browser automation security policy disallows file://. No browser-policy bypass attempted. Static link/media checks and JS VM checks passed; actual browser rendering/download not exercised.'}})
    print(json.dumps({'status':'PASS','source_fidelity_checks':len(checks),'offline_hash_link_checks':json.loads(offline.stdout)['checks'],'feedback_js':feedback_result['status']},indent=2))


if __name__=='__main__':main()
