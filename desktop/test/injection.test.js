const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { matches, assemble } = require('../src/injection');
test('matches manifest schemes, hosts and paths', () => {
  const p = ['https://*.example.com/portal/*'];
  assert(matches('https://example.com/portal/search?q=1', p));
  assert(matches('https://a.example.com/portal/x', p));
  assert(!matches('https://evil-example.com/portal/x', p));
  assert(!matches('http://example.com/portal/x', p));
  assert(!matches('https://example.com/login', p));
});
test('assembles a scoped script with data before content', () => {
  const script = assemble('HMR_PATIENTS', [{ folder: 'Synthetic' }], 'globalThis.answer = HMR_PATIENTS[0].folder;');
  new vm.Script(script);
  const ctx = { window: { hmrBridge: { sendMessage() {} } } };
  vm.runInNewContext(script, ctx);
  assert.equal(ctx.answer, 'Synthetic');
});

test('assembles the installed helper scripts when available', () => {
  const fs = require('node:fs'),
    path = require('node:path');
  const base = path.join(process.env.USERPROFILE || '', 'OneDrive', 'Documents', 'Desktop', 'HMR Ongoing');
  for (const [dir, key] of [
    ['Pathology Chrome Helper', 'HMR_PATIENTS'],
    ['MIMS Interaction Helper', 'MIMS_LISTS'],
    ['PPA Claim Helper', 'PPA_CLAIMS'],
  ]) {
    const file = path.join(base, dir, 'content.js');
    if (fs.existsSync(file)) new vm.Script(assemble(key, [], fs.readFileSync(file, 'utf8')));
  }
});

test('PPA helper reports a fill and escapes claim names', () => {
  const source = 'const missing = fill(c); `${c.given} ${c.family} ${c.interview}`';
  const script = assemble('PPA_CLAIMS', [], source);
  assert.match(script, /type: "filled"/);
  assert.match(script, /escapeText\(c.given\)/);
  new vm.Script(script);
});


test('MIMS injection rejects changed helper scripts without required cancellation anchors', () => {
  assert.throws(() => assemble('MIMS_LISTS', [], 'unrecognised helper', 'synthetic-token'), /Unsupported MIMS helper version/);
});
