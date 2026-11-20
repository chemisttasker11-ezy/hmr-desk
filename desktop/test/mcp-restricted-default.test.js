// The stdio MCP refuses sending and clinical-authorisation actions unless explicitly allowed for the run. TEST outbox
// mode is not treated as a safety control: it can still send to the test number.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
process.env.HMR_MCP_RESTRICT = '1';
const { call } = require('../mcp/hmr-desk-mcp');
const never = async () => { throw new Error('fetch must not be reached'); };
const RESTRICTED = [
  ['hmr_message_approve', { id: 'x', confirm: true }],
  ['hmr_messages_check', { confirm: true }],
  ['hmr_patient_action', { id: 1, action: 'signed_off', fields: {} }],
  ['hmr_patient_action', { id: 1, action: 'report_sent', fields: { date: '2026-11-21' } }],
  ['hmr_patient_action', { id: 1, action: 'claimed', fields: { date: '2026-11-21' } }],
  ['hmr_patient_action', { id: 1, action: 'claim_now', fields: { visit_date: '2026-11-21', report_sent: '2026-11-21' } }],
];

test('restricted tools and actions are refused before any request', async () => {
  for (const [name, args] of RESTRICTED) await assert.rejects(call(name, args, never, never), /Restricted|Invalid/, name + ' ' + (args.action || ''));
});

test('ordinary local actions are not caught by the restriction', async () => {
  let reached = false;
  const fetcher = async () => { reached = true; return { ok: true, status: 200, json: async () => ({ ok: true }) }; };
  await call('hmr_patient_action', { id: 1, action: 'note', fields: { text: 'synthetic note' } }, fetcher, async () => 'token');
  assert.equal(reached, true);
});

test('the real stdio process applies the restriction by default and lifts it only with the explicit variable', async () => {
  const run = async (extra) => {
    const child = spawn(process.execPath, [path.join(__dirname, '../mcp/hmr-desk-mcp.js')], { env: { ...process.env, HMR_MCP_RESTRICT: '', HMR_MCP_ALLOW_RESTRICTED: '', USERPROFILE: path.join(__dirname, 'no-such-profile'), ...extra }, stdio: ['pipe', 'pipe', 'inherit'] });
    let out = ''; child.stdout.on('data', (d) => (out += d));
    child.stdin.end(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'hmr_patient_action', arguments: { id: 1, action: 'signed_off', fields: {} } } }) + '\n');
    await new Promise((r) => child.on('close', r));
    return JSON.parse(out.trim()).result.content[0].text;
  };
  assert.match(await run({}), /Restricted/);
  assert.doesNotMatch(await run({ HMR_MCP_ALLOW_RESTRICTED: '1' }), /Restricted/);
});
