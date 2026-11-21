// Row-image source evidence button. Synthetic data only; the engine is stubbed.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const H=require('../renderer/helpers');
const source=fs.readFileSync(require.resolve('../renderer/medicine-lookup.js'),'utf8');
const loc={page:1,box:[50,90,400,105],pdf_sha256:'c'.repeat(64)};
function fakeElement(tag){return {tag,children:[],className:'',dataset:{},isConnected:true,replaceChildren(...n){this.children=n;},set textContent(v){this._t=v;},get textContent(){return this._t;}};}
function setup(api,state={}){
  const record={meds:[['Synthetic one 5 mg tablet','daily','','',''],['Synthetic two 10 mg tablet','nightly','','','']],details:{meds:[
    {source_evidence:{kind:'referral_text',lines:['Synthetic one 5 mg tablet | daily'],page_candidates:[[1]],text_sha256:'a'.repeat(64),location:loc}},
    {source_evidence:{kind:'referral_text',lines:['Synthetic two 10 mg tablet | nightly'],page_candidates:[[1]],text_sha256:'a'.repeat(64)}}]}};
  const box=fakeElement('div');
  const c=vm.createContext({H,interviewId:'7',interviewRecord:record,page:'interview',hmr:{api},interviewChanged(){},renderInterview(){},
    document:{addEventListener(){},querySelector(){return null;},createElement:fakeElement},...state});
  vm.runInContext(source,c);
  return {c,record,box,button:i=>({dataset:{medPageImage:'meds',row:String(i)},parentElement:{querySelector:()=>box}})};
}
test('the control is offered on rows with source evidence and says it is not current use',()=>{
  const x=setup(async()=>({}));
  const html=x.c.interviewLookupControls('meds',x.record.details.meds[0],0);
  assert.match(html,/data-med-page-image="meds" data-row="0"/);assert.match(html,/Show page image for this row/);assert.match(html,/not current use/);
});
test('the row sends its own evidence and shows the returned image with the honest note',async()=>{
  let call;const x=setup(async(...a)=>{call=a;return {kind:'row',page:1,png:'AAAA',note:'Region of page 1. For comparison only.'};});
  await x.c.medicineLookupClick(x.button(0));
  assert.equal(call[0],'POST');assert.equal(call[1],'/api/patients/7/interview/medicine-row-image');
  assert.equal(JSON.stringify(call[2]),JSON.stringify({source_evidence:x.record.details.meds[0].source_evidence}));
  const [img,note]=x.box.children;assert.equal(img.src,'data:image/png;base64,AAAA');assert.equal(img.className,'med-row-image');assert.match(img.alt,/page 1/);assert.match(note.textContent,/comparison only/);
  await x.c.medicineLookupClick(x.button(1));assert.equal(JSON.stringify(call[2]),JSON.stringify({source_evidence:x.record.details.meds[1].source_evidence}));   // each row sends only its own evidence
});
test('no image and engine failure both say so and point to the original',async()=>{
  let x=setup(async()=>({kind:'none',note:'The referral PDF is not the file this row was read from.'}));
  await x.c.medicineLookupClick(x.button(0));assert.equal(x.box.children.length,1);assert.match(x.box.children[0].textContent,/not the file/);
  x=setup(async()=>{throw new Error('Patient Name leaked here');});
  await x.c.medicineLookupClick(x.button(0));assert.equal(x.box.children.length,1);assert.match(x.box.children[0].textContent,/Open the original PDF/);assert.doesNotMatch(x.box.children[0].textContent,/leaked/);
});
test('a result for a patient or record that is no longer shown is dropped',async()=>{
  const x=setup(async()=>({kind:'page',page:1,png:'AAAA',note:'n'}));
  const pending=x.c.medicineLookupClick(x.button(0));x.c.interviewId='8';await pending;
  assert.equal(x.box.children.length,1);assert.match(x.box.children[0].textContent,/Loading/);
});
test('the control never changes the record',async()=>{
  const x=setup(async()=>({kind:'page',page:1,png:'AAAA',note:'n'}));const before=JSON.stringify(x.record);
  await x.c.medicineLookupClick(x.button(0));assert.equal(JSON.stringify(x.record),before);
});
