const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');

const base = () => ({
  pathology: { collection: { at: '2026-11-21T09:00:00', status: 'found' }, recheck_pending: false, report: 'changed_since_build', source_pdfs: [{ name: 'Path <1>.pdf', modified: 1763683200 }],
    records: [{ test: 'eGFR', value: '48', unit: 'mL/min', reference_interval: '>60', sample_date: '2026-11-10', source: 'MHR', verified: false }] },
  interactions: { evidence_state: 'stale', report: 'used_by_report', files: [{ kind: 'automated', saved_at: '2026-11-20T10:00:00', current: false }] },
  note: 'Display only.',
});

test('results view shows rows, honest basis wording and both repeat buttons', () => {
  const html = H.resultsHtml(base(), 7);
  assert.match(html, /eGFR/);
  assert.match(html, /Not verified/);
  assert.match(html, /changed after the report was built/);
  assert.match(html, /whole saved pathology record/);
  assert.match(html, /no current result/);
  assert.match(html, /describes the report, not the medicine list/);
  assert.match(html, /not an all-clear/);
  assert.match(html, /data-results-recheck-pathology="7"/);
  assert.match(html, /data-results-run-interactions="7"/);
  assert.doesNotMatch(html, /approved|signed off by/i);
});
test('results view escapes file names and never disables the repeat buttons', () => {
  const html = H.resultsHtml(base(), 7);
  assert.doesNotMatch(html, /<1>/);
  const b = base(); b.interactions.evidence_state = 'automated_current';
  assert.doesNotMatch(H.resultsHtml(b, 7), /data-results-run-interactions="7"[^>]*disabled/);
});
test('missing results say so and reason text names changed interactions', () => {
  assert.match(H.resultsHtml(null, 1), /could not be loaded/);
  const ready = { pathology: 'met', interactions: 'met', report: 'met' };
  assert.match(H.reportStatusHtml({ status: 'outdated', reasons: ['interactions_changed'], signed_off: false, signed_version_intact: null, readiness: ready }), /interaction results changed/);
});

test('acknowledgement needs a named pharmacist and never fills one in', () => {
  assert.equal(H.reconciliationReviewer({ pharmacist: '   ' }).ok, false);
  assert.match(H.reconciliationReviewer({}).hint, /box above the Acknowledge button/);
  assert.equal(H.reconciliationReviewer({ pharmacist: 'x'.repeat(121) }).ok, false);
  assert.deepEqual(H.reconciliationReviewer({ pharmacist: ' A Pharmacist ' }), { ok: true, reviewer: 'A Pharmacist', hint: '' });
});
