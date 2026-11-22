// Fail-closed default policy: every registered tool is classified; unclassified and blocked ones are refused before any request.
const test = require('node:test');
const assert = require('node:assert/strict');
process.env.HMR_MCP_RESTRICT = '1';
const { call, tools } = require('../mcp/hmr-desk-mcp');
const policy = require('../mcp/tool-policy');
const never = async () => { throw new Error('fetch must not be reached'); };

test('every registered tool is classified and every classified tool is registered', () => {
  const names = tools.map((t) => t.name).sort();
  assert.deepEqual(names.filter((n) => !policy.CLASS[n]), [], 'unclassified tools');
  assert.deepEqual(Object.keys(policy.CLASS).filter((n) => !names.includes(n)), [], 'classified but not registered');
});

test('blocked tools are refused before any request', async () => {
  for (const n of Object.keys(policy.CLASS).filter((k) => policy.CLASS[k] === 'blocked'))
    await assert.rejects(call(n, {}, never, never), /Restricted|Invalid/, n);
});

test('state-changing patient actions are refused, local record actions reach the engine', async () => {
  for (const action of ['book_phone', 'move', 'decline_phone', 'move_declined', 'expired', 'hold', 'visited', 'report_drafted', 'call', 'archive', 'resume', 'not_visited', 'pathology_outcome', 'followup_done'])
    assert.equal(policy.refusal('hmr_patient_action', { action }), 'patient state change', action);
  for (const action of policy.SAVE_PATIENT_ACTIONS) assert.equal(policy.refusal('hmr_patient_action', { action }), null);
});

test('read, ui and local save tools are not refused by the policy', () => {
  for (const [n, c] of Object.entries(policy.CLASS).filter(([, c]) => c !== 'blocked' && c !== 'save')) assert.equal(policy.refusal(n, {}), null, n + ' ' + c);
  assert.equal(policy.CLASS.hmr_patients, 'read');
  assert.equal(policy.CLASS.app_ui_snapshot, 'ui');
});

test('an unclassified tool name is refused', () => { assert.equal(policy.refusal('hmr_new_tool', {}), 'unclassified tool'); });

test('hmr_job_start: only local-only jobs reach the engine; AI and unknown jobs are refused before any request', async () => {
  for (const job of ['report_start', 'report_build']) assert.equal(policy.refusal('hmr_job_start', { job, patient_id: 1 }), null, job);
  for (const job of ['interview_pack', 'interview_sheet', 'report_assist', 'report_draft', 'interview_assist', 'report_extract', 'import_history', 'intake_apply', '', undefined])
    assert.equal(policy.refusal('hmr_job_start', { job, patient_id: 1 }), 'job that is not local-only', String(job));
  assert.equal(policy.refusal('hmr_job_start', undefined), 'job that is not local-only');
  for (const job of ['report_assist', 'report_draft', 'interview_assist', 'report_extract'])
    await assert.rejects(call('hmr_job_start', { job, patient_id: 1 }, never, never), /Restricted/, job);
  let seen;
  const fetcher = async (url, opt) => { seen = { url, body: opt && opt.body }; return { ok: true, status: 200, json: async () => ({ id: 'j1' }) }; };
  await call('hmr_job_start', { job: 'report_start', patient_id: 1 }, fetcher, async () => 'token');
  assert.match(String(seen.url), /\/api\/jobs$/);
  assert.match(String(seen.body), /report_start/);
});

test('allowing local jobs does not touch send, sign-off, claim, message or settings restrictions', () => {
  for (const n of ['hmr_message_approve', 'hmr_messages_check', 'hmr_run', 'hmr_task_result', 'hmr_settings_set', 'hmr_agent_select', 'hmr_report_refresh', 'hmr_referral_commit', 'app_proda_login'])
    assert.equal(policy.CLASS[n], 'blocked', n);
  for (const action of ['signed_off', 'report_sent', 'claimed', 'claim_now']) assert.equal(policy.refusal('hmr_patient_action', { action }), 'patient state change', action);
});
