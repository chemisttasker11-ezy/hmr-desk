const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');
const ready = (a, b, c) => ({ items: [{ key: 'consent_recorded', label: 'Patient consent recorded', state: a }, { key: 'medicines_reconciled', label: 'Medicine reconciliation reviewed for the current interview', state: b }, { key: 'demographics_match', label: 'Report patient, GP and date match the record', state: c }], clinically_ready: null });
test('outdated report names the reasons and never says approved', () => {
  const html = H.reportStatusHtml({ status: 'outdated', reasons: ['interview_changed', 'pathology_changed'], signed_off: false, signed_version_intact: null, readiness: ready('met', 'met', 'met') });
  assert.match(html, /Outdated/);
  assert.match(html, /interview changed/i);
  assert.match(html, /pathology changed/i);
  assert.doesNotMatch(html, /approved|ready to send|clinically ready/i);
});
test('current is shown as freshness only, with sign-off kept separate', () => {
  const html = H.reportStatusHtml({ status: 'current', reasons: [], signed_off: false, signed_version_intact: null, readiness: ready('met', 'met', 'met') });
  assert.match(html, /Matches the saved interview and pathology/);
  assert.match(html, /Not signed off/);
  assert.doesNotMatch(html, /approved|ready to send/i);
});
test('unknown and cannot-verify stay visibly uncertain', () => {
  const html = H.reportStatusHtml({ status: 'outdated', reasons: ['cannot_verify'], signed_off: false, signed_version_intact: null, readiness: ready('unknown', 'not_met', 'met') });
  assert.match(html, /could not be checked/i);
  assert.match(html, /Unknown/);
  assert.match(html, /Not done/);
});
test('signed version no longer intact is called out; missing or odd input is safe', () => {
  assert.match(H.reportStatusHtml({ status: 'current', reasons: [], signed_off: true, signed_version_intact: false, readiness: ready('met', 'met', 'met') }), /signed version.*changed|no longer intact/i);
  assert.match(H.reportStatusHtml({ status: 'not_generated', reasons: [], signed_off: false, readiness: ready('met', 'met', 'met') }), /No report has been built yet/);
  assert.equal(H.reportStatusHtml(null), '');
  assert.match(H.reportStatusHtml({ status: '<img>', reasons: ['<b>x'], signed_off: false, readiness: { items: [{ key: 'k', label: '<i>', state: 'met' }] } }), /^(?!.*<img>)(?!.*<b>)(?!.*<i>)/s);
});
