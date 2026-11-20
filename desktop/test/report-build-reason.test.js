const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');

test('a Build button that is grey because of an engine prerequisite keeps that reason', () => {
  const out = H.reportWorkflowStatus('visited', { name: 'report_build', ready: false, done: false, reason: 'Confirm the medicine list first' }, { status: 'not_generated' });
  assert.equal(out.build.ready, false);
  assert.equal(out.build.reason, 'Confirm the medicine list first');
  // Sign-off stays blocked with the currency reason, never enabled.
  assert.equal(out.canSign, false);
  assert.match(out.signReason, /No current generated report/);
});

test('when the engine gives no build reason, the currency reason is used', () => {
  const out = H.reportWorkflowStatus('visited', { name: 'report_build', ready: false, done: false }, { status: 'not_generated' });
  assert.match(out.build.reason, /No current generated report/);
});

test('a ready build with a stale report still explains the stale state and cannot sign', () => {
  const out = H.reportWorkflowStatus('report_drafted', { name: 'report_build', ready: true, done: true }, { status: 'outdated' });
  assert.equal(out.build.ready, true);
  assert.equal(out.build.done, false);
  assert.match(out.build.reason, /outdated/);
  assert.equal(out.canSign, false);
});
