// Synthetic portal DOM only. No eMIMS network, patient data or clinical rules.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const {assemble} = require('../src/injection');
const source = fs.readFileSync(path.join(__dirname, '../../MIMS Interaction Helper/content.js'), 'utf8');
const option = label => ({querySelector: () => null, innerText: label});
function setup({before='Ready',after='Pending',fields=2,clear=true,check=true,allergyPanel='',button=false}={}) {
  function HTMLInputElement() {}
  Object.defineProperty(HTMLInputElement.prototype, 'value', {set() {}});
  const messages=[], buttons=[];
  const body = {innerText: before, appendChild: b=>buttons.push(b)};
  const controls = [];
  if(check) controls.push({innerText:'Check Interaction',click(){body.innerText=after;}});
  controls.push({innerText:'Drug Interactions',click(){}});
  const context=vm.createContext({HTMLInputElement, setTimeout: fn=>fn(),
    Event:function(){}, KeyboardEvent:function(){}, console:{warn(){}},
    location:{pathname:'/interactions'},
    document:{body, createElement:()=>({style:{}}),
      getElementById:id=>id==='ClearAll' && clear ? {click(){}}:id==='allergies'?{innerText:allergyPanel}:null,
      querySelectorAll:selector=>selector==='button'?controls:selector==='#Interaction-Search input[role=combobox]'?Array(fields).fill({}):[],
      querySelector:()=>null},
    chrome:{runtime:{sendMessage:m=>{messages.push(m);return m;}}},
    ...(button?{MIMS_LISTS:[{folder:'SYNTHETIC',meds:['Synthetic medicine'],allergies:[]}]}:{})});
  vm.runInContext(source,context);
  // Isolate readiness/control behavior. Matching separately exercises actual pick().
  vm.runInContext('add = async () => "Synthetic exact medicine";',context);
  return {context,messages,body,controls,buttons};
}
const list='{folder:"SYNTHETIC",meds:["Synthetic medicine"],allergies:[]}';
for (const [name,labels,query,want] of [
  ['exact',['Syntheticmed'],'syntheticmed','Syntheticmed'],
  ['case and whitespace',[' Syntheticmed   sodium '],'syntheticmed sodium',' Syntheticmed   sodium '],
  ['no unrelated fallback',['Different drug'],'Syntheticmed',null],
  ['no prefix or salt inference',['Syntheticmed sodium'],'Syntheticmed',null],
  ['no formulation inference',['Syntheticmed 10 mg MR'],'Syntheticmed 10 mg',null],
  ['duplicate exact ambiguous',['Syntheticmed','Syntheticmed'],'Syntheticmed',null]]) {
  test(name,()=>{const {context}=setup();context.options=labels.map(option);context.query=query;
    assert.equal(vm.runInContext('pick(options,query)?.innerText ?? null',context),want);});
}
for (const after of ['Pending','Showing results','No interactions cannot be guaranteed','Loading\nNo interactions found']) {
  test('unknown/incomplete UI never saves: '+after, async()=>{
    const {context,messages}=setup({after});
    await assert.rejects(vm.runInContext(`runOne(${list})`,context),/not verified/);
    assert.equal(messages.length,0);
  });
}
test('explicit newly displayed empty result saves original wording and coverage',async()=>{
  const {context,messages}=setup({after:'No interactions found'});
  await vm.runInContext(`runOne(${list})`,context);
  assert.equal(messages.length,1);
  const text=decodeURIComponent(messages[0].url.split(',').slice(1).join(','));
  assert.match(text,/none listed by MIMS/);assert.match(text,/ENTERED:/);assert.match(text,/NOT FOUND IN MIMS/);
});
test('unchanged prior empty message is not accepted as fresh',async()=>{
  const {context,messages}=setup({before:'No interactions found',after:'No interactions found'});
  await assert.rejects(vm.runInContext(`runOne(${list})`,context),/not verified/);
  assert.equal(messages.length,0);
});
for (const config of [{fields:1},{clear:false},{check:false}]) test('missing controls fail closed '+JSON.stringify(config),async()=>{
  const {context,messages}=setup(config);
  await assert.rejects(vm.runInContext(`runOne(${list})`,context),/unavailable/);
  assert.equal(messages.length,0);
});
test('unmatched medicine fails before check/save and explains missing identity',async()=>{
  const {context,messages}=setup({after:'No interactions found'});
  vm.runInContext('add = async () => null;',context);
  await assert.rejects(vm.runInContext(`runOne(${list})`,context),/no unique exact match.*Synthetic medicine/);
  assert.equal(messages.length,0);
});
test('missing allergy panel cannot become completed result',async()=>{
  const {context,messages,controls}=setup({after:'No interactions found'});
  controls.push({innerText:'Allergy Check',click(){},getAttribute:()=> 'allergies'});
  await assert.rejects(vm.runInContext('runOne({folder:"SYNTHETIC",meds:["Synthetic medicine"],allergies:["Synthetic allergy"]})',context),/Allergy result not verified/);
  assert.equal(messages.length,0);
});
test('batch failure visibly incomplete rather than Done',async()=>{
  const {buttons,messages}=setup({button:true});
  await buttons[0].onclick();
  assert.match(buttons[0].textContent,/^Incomplete: 1\/1/);assert.equal(messages.length,0);
});
test('current helper still assembles with existing run-token/cancellation transforms',()=>{
  const script=assemble('MIMS_LISTS',[],source,'synthetic-run');
  assert.match(script,/hmrRun: token/);assert.match(script,/if \(!isCurrent\(\)\) break/);
  assert.doesNotThrow(()=>new vm.Script(script));
});
test('ready interaction row keeps synthetic portal wording through actual details parser',async()=>{
  const {context,messages,body,controls}=setup();
  let checked=false,modal=null;
  const popup={innerText:'Synthetic portal summary\nSeverity\nMajor\nActions to be taken\nSynthetic action wording\nDrug interactions details\nSynthetic detail wording\nReferences\nSynthetic reference',
    querySelectorAll:()=>[{click(){modal=null;}}]};
  const tr={cells:['Synthetic A','','Synthetic B','','Major','Synthetic documentation'].map(innerText=>({innerText})),
    querySelector:()=>({closest:()=>({click(){modal=popup;}})})};
  controls[0].click=()=>{checked=true;body.innerText='Showing results';};
  context.document.querySelectorAll=selector=>selector==='button'?controls:selector==='#Interaction-Search input[role=combobox]'?[{},{}]:selector==='table tr'&&checked?[{},tr]:[];
  context.document.querySelector=()=>modal;
  await vm.runInContext(`runOne(${list})`,context);
  assert.equal(messages.length,1);
  const text=decodeURIComponent(messages[0].url.split(',').slice(1).join(','));
  assert.match(text,/Synthetic A \+ Synthetic B \| Major \| Synthetic documentation/);
  assert.match(text,/Action: Synthetic action wording/);assert.match(text,/Detail: Synthetic detail wording/);
});
