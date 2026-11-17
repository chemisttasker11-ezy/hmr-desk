const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
function setup() {
  const context=vm.createContext({H:{...H,autosaver:()=>({changed(){}})},esc:H.esc,
    page:'interview',document:{addEventListener(){},querySelector(){return null;}}});
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'),'utf8'),context);
  return context;
}
test('technical IDs created once in draft metadata and retained through name edits and JSON save payload',()=>{
  const c=setup();
  const out=vm.runInContext(`(()=>{const r=normalizeInterviewDetails({meds:[['Synthetic','','','','']],other_meds:[['Other','','','']]});
    const first=r.details.meds[0].item_id, other=r.details.other_meds[0].item_id;
    normalizeInterviewDetails(r);r.meds[0][0]='Changed name';return {first,other,r:JSON.parse(JSON.stringify(r))};})()`,c);
  assert.match(out.first,/^[a-f0-9]{32}$/);assert.notEqual(out.first,out.other);
  assert.equal(out.r.details.meds[0].item_id,out.first);
  assert.equal(out.r.details.meds[0].use_status,'');assert.equal(out.r.details.meds[0].reference,undefined);
});
test('old local drafts compare clinically equivalent without IDs but changes are not masked',()=>{
  const c=setup();const old={meds:[['Synthetic','','','','']],other_meds:[]};
  c.a=JSON.stringify(old);c.b=vm.runInContext('JSON.stringify(normalizeInterviewDetails(JSON.parse(a)))',c);
  assert.equal(vm.runInContext('interviewEquivalent(a,b)',c),true);
  const changed=JSON.parse(c.b);changed.meds[0][0]='Different';c.b=JSON.stringify(changed);
  assert.equal(vm.runInContext('interviewEquivalent(a,b)',c),false);
});
test('row removal retains surviving ID and added row gets different ID',async()=>{
  const c=setup();vm.runInContext(`interviewRecord=normalizeInterviewDetails({meds:[['A','','','',''],['B','','','','']],other_meds:[]});renderInterview=()=>{};interviewChanged=()=>{};`,c);
  const id=vm.runInContext('interviewRecord.details.meds[1].item_id',c);
  await vm.runInContext(`interviewClick({dataset:{interviewRemove:'meds',row:'0'}})`,c);
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].item_id',c),id);
  await vm.runInContext(`interviewClick({dataset:{interviewAdd:'meds'}})`,c);
  assert.notEqual(vm.runInContext('interviewRecord.details.meds[1].item_id',c),id);
});
