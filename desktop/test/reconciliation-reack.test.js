const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function load() {
  const context = vm.createContext({ H, esc: H.esc, page: 'interview', document: { addEventListener() {} }, window: {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  return context;
}

test('acknowledge control is offered for an unreviewed or stale review, never for a current one or before the checklist loads', () => {
  const c = load();
  assert.equal(vm.runInContext('typeof canAcknowledgeReconciliation', c), 'function');
  const can = status => vm.runInContext('canAcknowledgeReconciliation', c)(status);
  assert.equal(can(null), false);
  assert.equal(can({ reviewed: false, stale: false }), true);
  assert.equal(can({ reviewed: false, stale: true }), true);
  assert.equal(can({ reviewed: true, stale: false }), false);
});
