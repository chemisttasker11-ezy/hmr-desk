const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const vm = require('node:vm');
const { handle, tools } = require('../mcp/hmr-desk-mcp');
const { createHandler, pageScript } = require('../src/control');

test('MCP protocol and tool errors', async () => {
  const request = (method, params) =>
    handle(
      { jsonrpc: '2.0', id: 1, method, params },
      async () => {
        throw Error('offline');
      },
      async () => 'token',
    );
  assert.equal((await request('initialize')).result.protocolVersion, '2024-11-05');
  assert.equal((await request('tools/list')).result.tools.length, tools.length);
  assert.ok(tools.every((t) => t.inputSchema.type === 'object' && t.description));
  assert.match((await request('tools/call', { name: 'missing' })).result.content[0].text, /Unknown tool/);
  assert.match(
    (await request('tools/call', { name: 'hmr_patient', arguments: { id: 'x' } })).result.content[0].text,
    /Invalid arguments/,
  );
  assert.match((await request('tools/call', { name: 'hmr_status' })).result.content[0].text, /engine is not running/);
  assert.match((await request('tools/call', { name: 'app_state' })).result.content[0].text, /HMR Desk app is not open/);
  assert.match(
    (
      await request('tools/call', {
        name: 'hmr_patient_action',
        arguments: { id: 1, action: 'note', fields: { action: 'claimed' } },
      })
    ).result.content[0].text,
    /Invalid action/,
  );
});

test('control rejects unauthorized requests and non-JSON', async (t) => {
  const ctx = {
    getWindow: () => ({ isDestroyed: () => false }),
    views: {},
    state: {},
    armed: {},
    oneOffs: {},
    results: [],
  };
  const server = http.createServer(createHandler(ctx, 'secret'));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}/state`;
  assert.equal(
    (await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status,
    401,
  );
  assert.equal(
    (
      await fetch(url, {
        method: 'POST',
        headers: { 'X-HMR-Control': 'secret', 'Content-Type': 'text/plain' },
        body: '{}',
      })
    ).status,
    415,
  );
});

test('page guard refuses sign-in and arbitrary elements', () => {
  const element = {
    id: 'other',
    type: 'button',
    getClientRects: () => [1],
    hasAttribute: () => false,
    matches: () => true,
    getAttribute: () => null,
  };
  const doc = { querySelectorAll: () => [], getElementById: () => element };
  const context = { document: doc, getComputedStyle: () => ({ visibility: 'visible', display: 'block' }) };
  assert.throws(() => vm.runInNewContext(pageScript('click', 'other'), context), /Invalid helper element/);
  doc.querySelectorAll = () => [{ type: 'password', getClientRects: () => [1] }];
  assert.throws(() => vm.runInNewContext(pageScript('text', 100), context), /sign-in page/);
  doc.querySelectorAll = () => [{ type: 'text', autocomplete: 'one-time-code', getClientRects: () => [1] }];
  assert.throws(() => vm.runInNewContext(pageScript('buttons'), context), /sign-in page/);
});

test('injected MIMS and PPA helper buttons receive identifiable IDs', () => {
  const { assemble } = require('../src/injection');
  const source = [
    'const sleep = ms => new Promise(r => setTimeout(r, ms));',
    'async function add(input, name) {}', 'async function details() {}', 'async function runOne(list) {}',
    'for (const [i, list] of MIMS_LISTS.entries()) {}', "const b = document.createElement('button');",
  ].join('\n');
  assert.match(assemble('MIMS_LISTS', [], source, 'test-run'), /b.id = 'mims-run'/);
  assert.match(assemble('PPA_CLAIMS', [], '<button id=\"pch-fill\"></button>'), /ppa-fill/);
});

test('MCP accepts the new patient actions and forwards their fields', async () => {
  for (const [action, fields] of [
    ['move_declined', {}],
    ['expired', { note: 'Referral expired' }],
    ['claim_now', { visit_date: '2026-11-01', report_sent: '2026-11-02' }],
  ]) {
    let request;
    const reply = await handle(
      { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'hmr_patient_action', arguments: { id: 1, action, fields } } },
      async (url, options) => { request = { url, ...options }; return { ok: true, json: async () => ({ ok: true, moved: true }) }; },
      async () => 'token',
    );
    assert.equal(reply.result.isError, undefined);
    assert.match(request.url, /\/api\/patients\/1\/action$/);
    assert.deepEqual(JSON.parse(request.body), { ...fields, action });
  }
});
