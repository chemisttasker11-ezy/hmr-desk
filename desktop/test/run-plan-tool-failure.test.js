const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { run, toolLevelFailure } = require('../mcp/run-plan');

test('toolLevelFailure recognises ok:false and an error string, and ignores normal results', () => {
  assert.equal(toolLevelFailure('{"ok":false,"error":"Report could not be opened"}'), 'Report could not be opened');
  assert.equal(toolLevelFailure('{"ok":false}'), 'ok is false');
  assert.equal(toolLevelFailure('{"error":"x"}'), 'x');
  assert.equal(toolLevelFailure('{"ok":true}'), '');
  assert.equal(toolLevelFailure('{"patients":[]}'), '');
  assert.equal(toolLevelFailure('not json'), '');
  assert.equal(toolLevelFailure('[{"ok":false}]'), '');
});

function fakeServer(dir) {
  const file = path.join(dir, 'fake-server.js');
  fs.writeFileSync(file, `
const rl = require('node:readline').createInterface({ input: process.stdin });
rl.on('line', (line) => { const m = JSON.parse(line); let result = {};
  if (m.method === 'tools/call') { const t = m.params.name; result = { content: [{ type: 'text', text: t === 'bad' ? '{"ok":false,"error":"Report could not be opened"}' : t === 'errstr' ? '{"error":"nope"}' : '{"ok":true}' }] };
    if (t === 'iserr') result = { isError: true, content: [{ type: 'text', text: 'Refused: blocked tool' }] }; }
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result }) + '\\n'); });
`);
  return file;
}

test('the runner fails a step whose result says ok:false even though the call succeeded, unless allowed or required', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const server = fakeServer(dir);
  const plan = (steps) => { const f = path.join(dir, 'plan.json'); fs.writeFileSync(f, JSON.stringify({ steps })); return f; };
  const quiet = console.log; console.log = () => {};
  try {
    const a = await run(plan([{ name: 'good', tool: 'good' }, { name: 'bad', tool: 'bad' }, { name: 'after', tool: 'good' }]), path.join(dir, 'a'), server);
    assert.equal(a.failed, true); assert.equal(a.report.length, 2);
    assert.equal(a.report[0].ok, true); assert.equal(a.report[1].ok, false); assert.match(a.report[1].problem, /tool-level failure/);
    const b = await run(plan([{ name: 'bad', tool: 'bad', allowToolFailure: true }, { name: 'after', tool: 'good' }]), path.join(dir, 'b'), server);
    assert.equal(b.failed, false); assert.equal(b.report.every((r) => r.ok), true);
    const c = await run(plan([{ name: 'must fail', tool: 'good', allowToolFailure: 'require' }]), path.join(dir, 'c'), server);
    assert.equal(c.failed, true); assert.match(c.report[0].problem, /expected a tool-level failure/);
    const d = await run(plan([{ name: 'must fail', tool: 'bad', allowToolFailure: 'require' }]), path.join(dir, 'd'), server);
    assert.equal(d.failed, false);
    // an MCP isError result is a real failure even when tool-level failures are allowed or required
    for (const flag of [undefined, true, 'require']) {
      const e = await run(plan([{ name: 'refused', tool: 'iserr', ...(flag === undefined ? {} : { allowToolFailure: flag }) }]), path.join(dir, 'e'), server);
      assert.equal(e.failed, true); assert.match(e.report[0].problem, /Refused/); assert.doesNotMatch(e.report[0].problem, /tool-level/);
    }
    // an error string alone is a tool-level failure; required failures are satisfied by it
    const f = await run(plan([{ name: 'err', tool: 'errstr' }]), path.join(dir, 'f'), server);
    assert.equal(f.failed, true); assert.match(f.report[0].problem, /nope/);
    const g = await run(plan([{ name: 'err', tool: 'errstr', allowToolFailure: 'require' }]), path.join(dir, 'g'), server);
    assert.equal(g.failed, false);
  } finally { console.log = quiet; }
});
