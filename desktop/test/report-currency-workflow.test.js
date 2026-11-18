const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

const historical = { name: 'report_build', done: true, ready: false, reason: 'already done' };
const currency = (status, reasons = []) => ({ status, reasons, signed_off: false, readiness: { items: [] } });

test('a historical built flag is not a current report after clinical changes', () => {
  const stale = H.reportWorkflowStatus('report_drafted', historical, currency('outdated', ['interview_changed']));
  assert.equal(stale.build.done, false);
  assert.equal(stale.build.ready, true, 'rebuild should remain available');
  assert.equal(stale.canSign, false);
  assert.match(stale.signReason, /outdated/i);
  assert.equal(H.patientPathway({ stage: 'report', state: 'report_drafted' }, {},
    [{ ...historical, ...stale.build }]).find(s => s.id === 'report').detail, 'Draft in progress');
});

test('only verified current reports can surface sign-off as available', () => {
  const current = H.reportWorkflowStatus('report_drafted', historical, currency('current'));
  assert.equal(current.build.done, true);
  assert.equal(current.canSign, true);
  for (const status of [null, currency('not_generated'), currency('outdated'), { status: 'unknown' }]) {
    const result = H.reportWorkflowStatus('report_drafted', historical, status);
    assert.equal(result.build.done, false);
    assert.equal(result.canSign, false);
    assert.ok(result.signReason);
  }
  assert.equal(H.reportWorkflowStatus('signed_off', historical, currency('current')).canSign, false);
});

function reportCard(status) {
  const context = vm.createContext({ H, esc: H.esc });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/reports.js'), 'utf8'), context);
  const patient = { id: 7, name: 'Synthetic Patient', state: 'report_drafted', stage: 'report', next_step: 'sign off' };
  return context.reportRow(patient, {
    reportCurrency: status,
    reportSpec: { issues: [{ text: 'synthetic finding' }] },
    steps: [
      { name: 'report_start', ready: false, done: true, reason: '' },
      { name: 'report_build', ready: false, done: true, reason: 'already done' },
    ],
  }, 'No agent selected');
}

test('reports list offers rebuilding rather than signing an outdated historical report', () => {
  const html = reportCard(currency('outdated', ['pathology_changed']));
  assert.match(html, /Outdated:/);
  assert.match(html, /pathology changed/);
  assert.match(html, /data-report-open="7" data-build="build"/);
  assert.match(html, /data-sign-off="7" disabled/);
  assert.doesNotMatch(html, /Build Word &#10003; Done/);
});

test('reports list fails closed when freshness cannot be fetched', () => {
  const html = reportCard(null);
  assert.match(html, /Report currency could not be verified/);
  assert.match(html, /data-sign-off="7" disabled/);
  assert.doesNotMatch(html, /Build Word &#10003; Done/);
});

test('reports list enables sign-off only for a verified current build', () => {
  const html = reportCard(currency('current'));
  assert.match(html, /data-sign-off="7">Signed off/);
  assert.match(html, /Build Word &#10003; Done/);
});
