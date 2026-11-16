const test = require('node:test');
const assert = require('node:assert/strict');
const {Readable} = require('node:stream');
const {createHandler, pageScript} = require('../src/control');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
test('focus routes use only named renderer functions and positive IDs', async () => {
  const scripts=[]; const win={isDestroyed:()=>false,webContents:{executeJavaScript:async s=>{scripts.push(s);return {ok:true};}}};
  const handler=createHandler({getWindow:()=>win,views:{},state:{},armed:{},oneOffs:{}},'synthetic');
  async function request(body) { const req=Readable.from([Buffer.from(JSON.stringify(body))]); req.headers={'x-hmr-control':'synthetic','content-type':'application/json'}; req.method='POST'; req.url='/patient/focus'; let status; const res={writeHead:s=>status=s,end:()=>{}}; await handler(req,res); return status; }
  assert.equal(await request({id:7,view:'followup',number:2}),200); assert.match(scripts[0],/openFollowup\(7,2\)/);
  assert.equal(await request({id:'7);evil()',view:'report'}),400);
  assert.equal(await request({id:7,view:'report',number:1}),400);
  assert.equal(await request({id:7,view:'patient',tab:'Conversation',layout:'split'}),200);
  assert.equal(scripts[1],'openPatientWorkspace(7,"Conversation","split")');
  assert.equal(await request({id:7,view:'interview',tab:'Files'}),400);
  assert.equal(await request({id:7,view:'patient',layout:'split);evil()'}),400);
  assert.equal(await request({id:7,view:'patient',tab:'Other'}),400);
});
test('patient focus preserves renderer cancellation', async () => {
  const win={isDestroyed:()=>false,webContents:{executeJavaScript:async()=>({cancelled:true})}};
  const handler=createHandler({getWindow:()=>win,views:{},state:{},armed:{},oneOffs:{}},'synthetic');
  for (const body of [{id:7,view:'patient',tab:'Files',layout:'patient'}, {id:7,view:'interview'}, {id:7,view:'report'}, {id:7,view:'followup',number:2}]) {
    const req=Readable.from([Buffer.from(JSON.stringify(body))]);
    req.headers={'x-hmr-control':'synthetic','content-type':'application/json'}; req.method='POST'; req.url='/patient/focus';
    let status, payload; await handler(req,{writeHead:s=>status=s,end:text=>payload=JSON.parse(text)});
    assert.equal(status,200); assert.deepEqual(payload,{cancelled:true});
  }
});
test('editor focus reports cancelled switches and refused navigation without losing records', async () => {
  let leaveCalls=0;
  const saver={leave:async()=>{leaveCalls++; return false;},dirty:()=>true};
  const ctx=vm.createContext({H:{...H,autosaver:()=>saver},page:'interview',document:{addEventListener(){},querySelector(){return null;}},$:()=>({}),
    navigate:async()=>{},errorText:e=>String(e)});
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'),'utf8'),ctx);
  vm.runInContext("interviewId='1'; interviewRecord={note:'unsaved'}",ctx);
  assert.equal((await ctx.openInterview(2)).cancelled,true);
  assert.equal(leaveCalls,1);
  assert.equal(vm.runInContext("interviewId + ':' + interviewRecord.note",ctx),'1:unsaved');
  ctx.page='report_editor'; vm.runInContext("reportId='1'; reportRecord={note:'unsaved'}",ctx);
  assert.equal((await ctx.openReport(2)).cancelled,true);
  assert.equal(vm.runInContext("reportId + ':' + reportRecord.note",ctx),'1:unsaved');
  ctx.page='followup_editor'; vm.runInContext("followupId='1'; followupNumber=1; followupRecord={note:'unsaved'}",ctx);
  assert.equal((await ctx.openFollowup(2,2)).cancelled,true);
  assert.equal(vm.runInContext("followupId + ':' + followupNumber + ':' + followupRecord.note",ctx),'1:1:unsaved');
  ctx.page='patients';
  assert.equal((await ctx.openInterview(2)).cancelled,true);
  assert.equal(vm.runInContext('interviewId',ctx),'1');
  assert.equal((await ctx.openReport(2)).cancelled,true);
  assert.equal(vm.runInContext('reportId',ctx),'1');
  assert.equal((await ctx.openFollowup(2,2)).cancelled,true);
  assert.equal(vm.runInContext('followupId + ":" + followupNumber',ctx),'1:1');
  assert.equal(leaveCalls,3);
});
test('editor focus reports success only for the requested loaded record', async () => {
  const ctx=vm.createContext({H:{...H,autosaver:()=>({leave:async()=>true})},page:'patients',document:{addEventListener(){},querySelector(){return null;}},$:()=>({}), errorText:e=>String(e)});
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'),'utf8'),ctx);
  ctx.navigate=async dest=>{ctx.page=dest; vm.runInContext(dest==='interview'?'interviewRecord={}':dest==='report_editor'?'reportRecord={}':'followupRecord={}',ctx);};
  assert.equal((await ctx.openInterview(7)).ok,true);
  ctx.page='patients'; assert.equal((await ctx.openReport(7)).ok,true);
  ctx.page='patients'; assert.equal((await ctx.openFollowup(7,2)).ok,true);
  ctx.page='patients'; vm.runInContext('reportRecord=null',ctx);
  ctx.navigate=async dest=>{ctx.page=dest;};
  assert.equal((await ctx.openReport(8)).ok,false);
});
test('sign-in page remains unavailable to generic inspection', () => {
  const context={document:{querySelectorAll:()=>[{type:'password',getClientRects:()=>[1]}]},getComputedStyle:()=>({visibility:'visible',display:'block'})};
  assert.throws(()=>vm.runInNewContext(pageScript('text',100),context),/sign-in page/);
});
