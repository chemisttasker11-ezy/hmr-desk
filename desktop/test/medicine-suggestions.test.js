// Synthetic proposal lifecycle only. No catalogue licence or portal/network use.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const H=require('../renderer/helpers');
const source=fs.readFileSync(require.resolve('../renderer/medicine-lookup.js'),'utf8');
function setup(api) {
  const record={meds:[['Synthetic original 5 mg MR','one daily','','','']],details:{meds:[{item_id:'a'.repeat(32),use_status:'',source_evidence:{kind:'referral_text',lines:['<Synthetic original> 5 mg MR take one daily'],page_candidates:[[2]],text_sha256:'b'.repeat(64)}}]}};
  let changed=0;
  const c=vm.createContext({H,interviewId:'synthetic',interviewRecord:record,page:'interview',hmr:{api},
    interviewChanged:()=>changed++,renderInterview(){},document:{addEventListener(){},querySelector(){return null;}}});
  vm.runInContext(source,c);
  return {c,record,get changed(){return changed;}};
}
const candidate={source:'amt',code:'1001',display:'Synthetic chosen 5 mg MR tablet',kind:'MPUU',generic_name:'Synthetic generic 5 mg MR tablet',release:'20260101'};
function response(text='Synthetic original 5 mg MR') {return {installed:true,results:[{input_text:text,state:'review_candidates',truncated:false,candidates:[candidate]}]};}
test('auto proposal never sets reference or actual use; explicit choice preserves evidence and ID',async()=>{
  let request;const x=setup(async(...args)=>{request=args;return response();});const original=JSON.stringify(x.record);
  await x.c.medicinePrefillSuggestions();
  assert.equal(JSON.stringify(x.record),original);assert.equal(x.changed,0);
  assert.equal(request[0],'POST');assert.equal(request[1],'/api/medicines/suggest');
  const html=x.c.interviewLookupControls('meds',x.record.details.meds[0],0);
  assert.match(html,/Possible matches only/);assert.match(html,/Modelled generic/);assert.match(html,/&lt;Synthetic original&gt;/);
  assert.match(html,/Text located on page 2/);assert.doesNotMatch(html,/<Synthetic original>/);
  await x.c.medicineLookupClick({dataset:{medSuggestion:'meds',row:'0',candidate:'0'}});
  assert.equal(x.record.meds[0][0],candidate.display);assert.equal(x.record.details.meds[0].reference.code,'1001');
  assert.equal(x.record.details.meds[0].source_evidence.lines[0],'<Synthetic original> 5 mg MR take one daily');
  assert.equal(x.record.details.meds[0].item_id,'a'.repeat(32));assert.equal(x.record.details.meds[0].use_status,'');
  assert.equal(x.record.meds[0][1],'one daily');assert.equal(x.record.meds[0][2],'');assert.equal(x.changed,1);
});
for (const mode of ['name','patient','record','row']) test('late automatic response cannot attach after '+mode+' changes',async()=>{
  let finish;const x=setup(()=>new Promise(r=>{finish=r;}));const old=x.record.details.meds[0];
  const pending=x.c.medicinePrefillSuggestions();
  if(mode==='name')x.record.meds[0][0]='Edited';
  if(mode==='patient')x.c.interviewId='different';
  if(mode==='record')x.c.interviewRecord={meds:[],details:{meds:[]}};
  if(mode==='row')x.record.meds[0]=['Replacement'];
  finish(response());await pending;
  assert.equal(vm.runInContext('medicineSuggestions.get(interviewRecord.details.meds[0])',x.c),undefined);
  assert.equal(old.reference,undefined);
});
test('changed name rejects an already displayed proposal on click',async()=>{
  const x=setup(async()=>response());await x.c.medicinePrefillSuggestions();
  x.record.meds[0][0]='Edited';await x.c.medicineLookupClick({dataset:{medSuggestion:'meds',row:'0',candidate:'0'}});
  assert.equal(x.record.details.meds[0].reference,undefined);assert.equal(x.record.meds[0][0],'Edited');assert.equal(x.changed,0);
});
test('missing catalogue still shows free-text state without mutating record',async()=>{
  const x=setup(async()=>({installed:false,results:[{input_text:'Synthetic original 5 mg MR',state:'unavailable',candidates:[],truncated:false}]}));
  await x.c.medicinePrefillSuggestions();assert.match(x.c.interviewLookupControls('meds',x.record.details.meds[0],0),/Free text still works/);
  assert.equal(x.record.details.meds[0].reference,undefined);
});

const intakeCandidate={source:'amt',code:'1001',display:'Synthetic original 5 mg MR',kind:'MPUU',generic_name:'Synthetic generic 5 mg MR',brand_name:null,dose_form:'tablet',release:'20260101'};
function setupStored(api){const x=setup(api);x.record.details.meds[0].prefill_proposal={input_text:'Synthetic original 5 mg MR',candidate:intakeCandidate};return x;}
function exactResponse(){return {installed:true,results:[{input_text:'Synthetic original 5 mg MR',state:'exact_candidate',truncated:false,candidates:[{...intakeCandidate}]}]};}
test('stored intake proposal gains provenance label only when the batch revalidation matches it exactly',async()=>{
  const calls=[];const x=setupStored(async(...a)=>{calls.push(a);return exactResponse();});
  const original=JSON.stringify(x.record);
  await x.c.medicinePrefillSuggestions();
  assert.deepEqual(calls.map(a=>[a[0],a[1]]),[['POST','/api/medicines/suggest']]);
  assert.equal(JSON.stringify(x.record),original);
  const html=x.c.interviewLookupControls('meds',x.record.details.meds[0],0);
  assert.match(html,/Exact displayed-text candidate, not confirmed/);assert.match(html,/Prepared at intake from the referral text/);
  await x.c.medicineLookupClick({dataset:{medSuggestion:'meds',row:'0',candidate:'0'}});
  assert.equal(x.record.details.meds[0].reference.code,'1001');assert.equal(x.record.details.meds[0].item_id,'a'.repeat(32));
  assert.equal(x.record.details.meds[0].source_evidence.lines[0],'<Synthetic original> 5 mg MR take one daily');
});
for (const mode of ['contents changed','now ambiguous']) test('catalogue '+mode+' drops the intake provenance label, never the review',async()=>{
  const changed=mode==='contents changed';
  const x=setupStored(async()=>({installed:true,results:[changed
    ?{input_text:'Synthetic original 5 mg MR',state:'exact_candidate',truncated:false,candidates:[{...intakeCandidate,display:'Corrected name 5 mg MR'}]}
    :{input_text:'Synthetic original 5 mg MR',state:'ambiguous',truncated:false,candidates:[{...intakeCandidate},{...intakeCandidate,code:'1002'}]}]}));
  await x.c.medicinePrefillSuggestions();
  const html=x.c.interviewLookupControls('meds',x.record.details.meds[0],0);
  assert.doesNotMatch(html,/Prepared at intake/);
  assert.match(html,changed?/Exact displayed-text candidate/:/More than one exact text candidate/);
  assert.equal(x.record.details.meds[0].reference,undefined);
});
test('stored proposal inconsistent with the row text never earns the label',async()=>{
  const x=setupStored(async()=>exactResponse());
  x.record.details.meds[0].prefill_proposal={input_text:'Some other text',candidate:intakeCandidate};
  await x.c.medicinePrefillSuggestions();
  assert.doesNotMatch(x.c.interviewLookupControls('meds',x.record.details.meds[0],0),/Prepared at intake/);
});
test('row reorder during the batch wait applies nothing to moved rows',async()=>{
  let finish;const calls=[];
  const x=setupStored((...a)=>{calls.push(a);return new Promise(r=>{finish=r;});});
  x.record.meds.push(['Second med 10 mg','','','','']);x.record.details.meds.push({source_evidence:{kind:'referral_text',lines:['Second med 10 mg'],page_candidates:[[2]],text_sha256:'c'.repeat(64)}});
  const pending=x.c.medicinePrefillSuggestions();await new Promise(r=>setImmediate(r));
  x.record.meds.reverse();x.record.details.meds.reverse();
  finish({installed:true,results:[exactResponse().results[0],{input_text:'Second med 10 mg',state:'unmatched',truncated:false,candidates:[]}]});
  await pending;
  assert.equal(vm.runInContext('medicineSuggestions.get(interviewRecord.details.meds[0])',x.c),undefined);
  assert.equal(vm.runInContext('medicineSuggestions.get(interviewRecord.details.meds[1])',x.c),undefined);
});
test('rejected suggest after patient switch applies nothing',async()=>{
  let fail;const x=setupStored(()=>new Promise((_,rej)=>{fail=rej;}));
  const pending=x.c.medicinePrefillSuggestions();await new Promise(r=>setImmediate(r));
  x.c.interviewId='different';fail(Error('offline'));await pending;
  assert.equal(vm.runInContext('medicineSuggestions.get(interviewRecord.details.meds[0])',x.c),undefined);
  assert.equal(x.record.details.meds[0].reference,undefined);
});
test('fallback record without a stored proposal never earns the intake label',async()=>{
  // Records built on first interview open (fallback or pre-existing patients)
  // carry no prefill_proposal; an exact catalogue match renders the normal
  // live proposal with no intake provenance.
  const x=setup(async()=>exactResponse());
  await x.c.medicinePrefillSuggestions();
  const html=x.c.interviewLookupControls('meds',x.record.details.meds[0],0);
  assert.match(html,/Exact displayed-text candidate, not confirmed/);
  assert.doesNotMatch(html,/Prepared at intake/);
});
