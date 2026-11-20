const test = require('node:test');
const assert = require('node:assert/strict');
const {call, tools} = require('../mcp/hmr-desk-mcp');
const read = async () => 'synthetic-token';
function fake(response = {}) { const calls = []; return {calls, fetch: async (url, opts) => { calls.push({url,opts}); return {ok:true,json:async()=>response}; }}; }
test('catalog, patient task filters, and typed actions preserve route contracts', async () => {
  assert.ok(tools.some(t => t.name === 'hmr_attention'));
  let f = fake({tasks:[],steps:[]}); await call('hmr_tasks',{patient_id:7},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/run\?patient_id=7$/);
  f = fake(); await call('hmr_patient_action',{id:7,action:'report_sent',fields:{date:'2026-01-01'}},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{date:'2026-01-01',action:'report_sent'});
  await assert.rejects(call('hmr_patient_action',{id:7,action:'archive',fields:{id:9}},f.fetch,read),/Invalid action/);
  await assert.rejects(call('hmr_patient_action',{id:7,action:'followup_claimed',fields:{kind:'bad'}},f.fetch,read),/Invalid action/);
  await assert.rejects(call('hmr_settings_set',{values:{outbox_mode:'live'}},f.fetch,read),/Restricted setting/);
});
test('workflow routes and patient message content', async () => {
  let f = fake({needs_you:[{direction:'in',body:'Patient asks about appointment',ai_summary:'Patient asks about appointment'}],recent:[]});
  const out = JSON.parse((await call('hmr_messages',{},f.fetch,read))[0].text);
  assert.equal(out.needs_you[0].body,'Patient asks about appointment');
  f = fake(); await call('hmr_followup_export',{id:3,number:2},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/patients\/3\/followup\/2\/export$/);
  await assert.rejects(call('hmr_followup_export',{id:3,number:3},f.fetch,read),/Invalid arguments/);
  f = fake(); await call('hmr_message_draft',{id:3,kind:'offer',date:'2026-11-20',time:'10:00'},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{kind:'offer',date:'2026-11-20',time:'10:00'});
  await assert.rejects(call('hmr_message_draft',{id:3,kind:'custom',body:'anything'},f.fetch,read),/Invalid arguments/);
});

test('message mutations require confirmation and an authoritative test-mode preflight', async () => {
  for (const name of ['hmr_message_approve','hmr_messages_check']) {
    const args = name === 'hmr_message_approve' ? {id:'draft',confirm_send:true} : {confirm_send:true};
    const calls=[];
    const allowed = async (url, opts) => { calls.push({url,opts}); return {ok:true,json:async()=>url.endsWith('/api/status') ? {outbox_mode:'test'} : {ok:true}}; };
    await call(name,args,allowed,read);
    assert.equal(calls.length,2); assert.match(calls[0].url,/\/api\/status$/);
    assert.equal(calls[0].opts.method,'GET'); assert.equal(calls[1].opts.method,'POST');
    assert.deepEqual(JSON.parse(calls[1].opts.body),{});
    let count=0;
    const live = async () => { count++; return {ok:true,json:async()=>({outbox_mode:'live'})}; };
    await assert.rejects(call(name,args,live,read),/test outbox mode/); assert.equal(count,1);
    await assert.rejects(call(name,{...args,confirm_send:false},allowed,read),/Invalid arguments/);
    const missing={...args}; delete missing.confirm_send;
    await assert.rejects(call(name,missing,allowed,read),/Invalid arguments/);
  }
});

test('agent selection, expiry confirmation and consent image use typed contracts', async () => {
  let f = fake();
  await call('hmr_agent_select',{default:'Agent A',per_step:{interview_assist:'Agent B',report_draft:null,report_assist:'Agent A'}},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{default:'Agent A',per_step:{interview_assist:'Agent B',report_draft:null,report_assist:'Agent A'}});
  await assert.rejects(call('hmr_agent_select',{per_step:{unknown:'Agent A'}},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_agent_select',{},f.fetch,read),/Invalid arguments/);
  let calls=[]; const fetcher=async (url,opts)=>{ calls.push({url,opts}); return {ok:true,json:async()=>url.endsWith('/api/status')?{outbox_mode:'test'}:{ok:true}}; };
  await call('hmr_message_approve',{id:'draft',confirm_send:true,confirm_expired:true},fetcher,read);
  assert.deepEqual(JSON.parse(calls[1].opts.body),{confirm_expired:true});
  await assert.rejects(call('hmr_message_approve',{id:'draft',confirm_send:true,confirm_expired:false},fetcher,read),/Invalid arguments/);
  f=fake({png:'c3ludGhldGlj',by:'patient',signed_file:'consent.pdf',revision:'synthetic-revision'});
  const content=await call('hmr_consent_preview',{id:1},f.fetch,read);
  assert.deepEqual(content[0],{type:'image',data:'c3ludGhldGlj',mimeType:'image/png'});
  assert.deepEqual(JSON.parse(content[1].text),{by:'patient',signed_file:'consent.pdf',revision:'synthetic-revision'});
  assert.ok(!content[1].text.includes('c3ludGhldGlj'));
});

test('medicine reconciliation, task evidence and referral review use explicit typed bodies', async () => {
  const taking = {name:'Synthetic 5mg',status:'taking',detail:'Taking',source:'Found during interview',directions:['daily','']};
  const stopped = {name:'Synthetic 10mg',status:'not_using',detail:'Not using',source:'Referral medicine',directions:['daily','']};
  let f = fake();
  const meds = {id:7, meds:[['synthetic','']], allergies:[], interview_usage:[stopped,taking], alternatives:[taking]};
  await call('hmr_medicines_save', meds, f.fetch, read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body), {meds:meds.meds,allergies:[],interview_usage:meds.interview_usage,alternatives:[taking]});
  await assert.rejects(call('hmr_medicines_save',{...meds,interview_usage:[{...taking,status:'invented'}]},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_medicines_save',{...meds,alternatives:[{...taking,extra:'x'}]},f.fetch,read),/Invalid arguments/);
  f = fake(); await call('hmr_task_result',{id:'abc',state:'done',mims_result:'MIMS interactions.txt'},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{state:'done',mims_result:'MIMS interactions.txt'});
  f = fake(); await call('hmr_referral_review',{paths:['C:\\synthetic\\referral.pdf']},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/referrals\/review$/);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{paths:['C:\\synthetic\\referral.pdf']});
  await assert.rejects(call('hmr_referral_review',{paths:[]},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_referral_review',{paths:Array(101).fill('x.pdf')},f.fetch,read),/Invalid arguments/);
  const token='a'.repeat(32), fields={name:'Synthetic Person',gp:'Test Doctor'};
  f = fake(); await call('hmr_referral_commit',{token,fields,confirm:true},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{token,fields});
  await assert.rejects(call('hmr_referral_commit',{token,fields,confirm:false},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_referral_commit',{token,fields},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_referral_commit',{token,fields:{name:'Synthetic',folder:'x'},confirm:true},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('hmr_referral_commit',{token:'../x',fields,confirm:true},f.fetch,read),/Invalid arguments/);
});

test('patient workspace options are only accepted for patient view', async () => {
  const f=fake({ok:true});
  await call('app_patient_focus',{id:7,view:'patient',tab:'Conversation',layout:'split'},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{id:7,view:'patient',tab:'Conversation',layout:'split'});
  await assert.rejects(call('app_patient_focus',{id:7,view:'report',tab:'Files'},f.fetch,read),/Invalid arguments/);
  await assert.rejects(call('app_patient_focus',{id:7,view:'patient',layout:'bad'},f.fetch,read),/Invalid arguments/);
});

test('report refresh and demographic decisions use enumerated routes and bodies', async () => {
  assert.ok(tools.some(t => t.name === 'hmr_report_refresh') && tools.some(t => t.name === 'hmr_report_demographics'));
  let f = fake(); await call('hmr_report_refresh',{id:4},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/patients\/4\/report\/refresh$/); assert.equal(f.calls[0].opts.method,'POST'); assert.deepEqual(JSON.parse(f.calls[0].opts.body),{});
  f = fake(); await call('hmr_report_refresh',{id:4,replace_demographics:['patient','dear']},f.fetch,read);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{replace_demographics:['patient','dear']});
  f = fake(); await call('hmr_report_demographics',{id:4,action:'keep',keys:['name']},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/patients\/4\/report\/demographics$/); assert.deepEqual(JSON.parse(f.calls[0].opts.body),{action:'keep',keys:['name']});
  for (const [n,a] of [['hmr_report_refresh',{id:4,replace_demographics:['bogus']}],['hmr_report_refresh',{id:4,replace_demographics:['name','name']}],['hmr_report_refresh',{id:4,extra:1}],
    ['hmr_report_demographics',{id:4,action:'delete',keys:['name']}],['hmr_report_demographics',{id:4,action:'keep',keys:[]}],['hmr_report_demographics',{id:4,action:'keep',keys:['x']}],['hmr_report_demographics',{id:4,action:'keep'}],['hmr_report_demographics',{id:4,action:'keep',keys:['name'],confirm:true}]])
    await assert.rejects(call(n,a,f.fetch,read),/Invalid arguments/);
});

test('medicine save forwards the reviewed snapshot digest and rejects a malformed one', async () => {
  const digest = 'a'.repeat(64);
  let f = fake(); await call('hmr_medicines_save',{id:5,meds:[['Synthetic A','Brand A']],allergies:[],medicine_snapshot_sha256:digest},f.fetch,read);
  assert.match(f.calls[0].url,/\/api\/patients\/5\/meds$/);
  assert.deepEqual(JSON.parse(f.calls[0].opts.body),{meds:[['Synthetic A','Brand A']],allergies:[],medicine_snapshot_sha256:digest});
  await assert.rejects(call('hmr_medicines_save',{id:5,meds:[],allergies:[],medicine_snapshot_sha256:'xyz'},f.fetch,read),/Invalid arguments/);
});
