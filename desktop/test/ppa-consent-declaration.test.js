const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', '..', 'PPA Claim Helper', 'content.js'), 'utf8');

function run(claim) {
  const boxes = {};
  const element = (id) => (boxes[id] ||= { id, checked: false, style: {}, focus() {}, click() { this.checked = !this.checked; }, dispatchEvent() {}, value: '' });
  const ctx = {
    document: { getElementById: element, documentElement: {}, body: { appendChild() {} } },
    location: { pathname: '/x' }, Event: function Event() {}, MutationObserver: function () { this.observe = () => {}; },
  };
  vm.createContext(ctx);
  vm.runInContext(source + '\nglobalThis.__fill = fill;', ctx);
  const missing = ctx.__fill(claim);
  return { missing, ticked: boxes.writtenPatientConsentHeld_0 ? boxes.writtenPatientConsentHeld_0.checked : false };
}
const base = { given: 'A', family: 'B', reasons: ['polypharmacy'], outcomes: ['change'] };

test('written consent held is ticked only when signed consent is recorded', () => {
  const held = run({ ...base, consentHeld: true });
  assert.equal(held.ticked, true);
  assert.equal(held.missing.some((m) => m.startsWith('written consent held')), false);
});
test('without recorded consent the box stays unticked and is listed as still to check', () => {
  for (const claim of [{ ...base }, { ...base, consentHeld: false }, { ...base, consentHeld: 'true' }]) {
    const r = run(claim);
    assert.equal(r.ticked, false);
    assert.equal(r.missing.some((m) => m.startsWith('written consent held')), true);
  }
});
