const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const H = require('../renderer/helpers.js');

function load(file, extra = {}) {
  const ctx = { esc: H.esc, H, ...extra };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../renderer', file), 'utf8'), ctx);
  return ctx;
}

test('Today card never says plain Sign off, it names the report check', () => {
  const { nextButton } = load('today.js');
  const html = nextButton({ id: 4, next_step: 'sign off' });
  assert.match(html, /Check report, then sign off/);
  assert.match(html, /data-step="sign off"/);
  assert.equal(H.stepLabel('sign off'), 'Check report, then sign off');
  assert.doesNotMatch(nextButton({ id: 5, next_step: 'build report' }), /Check report/);
});

test('Reports list limits concurrent patient loads and keeps order and failures', async () => {
  const { settledPool } = load('reports.js');
  let active = 0, peak = 0;
  const res = await settledPool([1, 2, 3, 4, 5, 6, 7], 3, async (n) => {
    active++; peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, 5));
    active--;
    if (n === 4) throw new Error('boom');
    return n * 2;
  });
  assert.equal(peak, 3);
  assert.deepEqual(Array.from(res, (r) => r.status), ['fulfilled', 'fulfilled', 'fulfilled', 'rejected', 'fulfilled', 'fulfilled', 'fulfilled']);
  assert.equal(res[6].value, 14);
  assert.equal(res[3].reason.message, 'boom');
  assert.equal((await settledPool([], 3, async () => 1)).length, 0);
});

test('Today attention row detail for a sign-off item names the report check', () => {
  assert.match(H.attentionDetail({ detail: 'sign off' }, 'reports'), /Check report, then sign off/);
  assert.equal(H.attentionDetail({ detail: 'Phone gateway offline' }, 'stuck'), 'Phone gateway offline');
});
