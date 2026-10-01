// Exercise the packaged feedback code without a browser or network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(process.argv[2]);
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'review.js'), 'utf8');
const ids = ['R007','R020','R011','R025','R039','R014','R018','R009','R037','R005','R036','R004'];
function input(attrs, value='') {
  return {dataset:attrs, value, listeners:{}, addEventListener(name, fn){this.listeners[name]=fn;}};
}
const controls = [...html.matchAll(/(?:<select|<textarea) ([^>]*data-feedback[^>]*)>/g)].map(match => {
  const dataset = {};
  for (const [,key,value] of match[1].matchAll(/data-([a-z]+)="([^"]*)"/g)) dataset[key]=value;
  return input(dataset, dataset.field==='assessment' ? 'UNREVIEWED' : dataset.field==='severity' ? 'UNSET' : '');
});
assert.equal(controls.length,108);
function session(saved=null, storageFails=false) {
  let current=saved, lastBlob=null, downloaded=null;
  const elements = Object.fromEntries(['save-status','progress','reviewer','export','export-status'].map(id=>[id,input({})]));
  elements.progress.textContent='';
  const context = {
    document:{getElementById:id=>elements[id],querySelectorAll:()=>controls,
      createElement:()=>({click(){downloaded=this.download;},remove(){}}),body:{appendChild(){}}},
    localStorage:{getItem(){if(storageFails)throw Error('denied');return current;},setItem(k,v){if(storageFails)throw Error('denied');current=v;}},
    Blob:class {constructor(parts){this.parts=parts;lastBlob=this;}},
    URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},
    setTimeout:fn=>{fn();}, Date, JSON
  };
  vm.runInNewContext(script,context,{filename:'review.js'});
  return {elements,change(sid,alias,field,value){const el=controls.find(x=>x.dataset.scene===sid&&x.dataset.alias===alias&&x.dataset.field===field);el.value=value;el.listeners.input();},saved:()=>current,
    export(){elements.export.listeners.click();return {data:JSON.parse(lastBlob.parts.join('')),downloaded};}};
}
const first=session();
let result=first.export();
assert.equal(result.data.cases.length,12);
assert.equal(result.data.cases.flatMap(x=>x.aliases).length,36);
assert.ok(result.data.cases.every(c=>c.aliases.every(a=>a.assessment==='UNREVIEWED'&&a.notes==='')));
first.elements.reviewer.value='AUTOMATED_TEST_ONLY';first.elements.reviewer.listeners.input();
first.change('R007','A','assessment','DEFECT_OBSERVED');
first.change('R007','A','severity','HIGH');
first.change('R007','A','notes','AUTOMATED_TEST_ONLY: vùng sáng <>& tiếng Việt');
first.change('R004','C','assessment','NO_OBVIOUS_DEFECT');
result=first.export();
assert.equal(result.data.reviewer,'AUTOMATED_TEST_ONLY');
assert.equal(result.data.cases.find(c=>c.source_id==='R007').aliases[0].notes,'AUTOMATED_TEST_ONLY: vùng sáng <>& tiếng Việt');
assert.equal(result.data.cases.find(c=>c.source_id==='R004').aliases[2].assessment,'NO_OBVIOUS_DEFECT');
assert.equal(result.downloaded,'RAW-review-12-run-v1-feedback.json');
assert.equal(first.elements.progress.textContent,'2/36 ô đã ghi nhận');
assert.ok(!/darktable|rawtherapee|photo-cli|LibRaw/i.test(JSON.stringify(result.data)));
const restored=session(first.saved());
assert.equal(restored.elements.reviewer.value,'AUTOMATED_TEST_ONLY');
assert.equal(restored.export().data.cases.find(c=>c.source_id==='R007').aliases[0].severity,'HIGH');
const denied=session(null,true);
denied.change('R025','B','assessment','INSUFFICIENT_EVIDENCE');
assert.equal(denied.export().data.cases.find(c=>c.source_id==='R025').aliases[1].assessment,'INSUFFICIENT_EVIDENCE');
assert.ok(denied.elements['save-status'].textContent.includes('Không lưu tự động'));
console.log(JSON.stringify({status:'PASS',checks:['108 real HTML feedback controls','36 initially unreviewed aliases','cross-case export','Vietnamese/special-character roundtrip','restored local state','blocked-storage fallback','download filename','no identities in feedback'],note:'Test data stayed in VM memory; no human feedback was written or submitted. Browser download itself was not exercised.'}));
