const { test } = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers');

test('pages map to their sidebar sections', () => {
  for (const [section, pages] of Object.entries({ book: ['book', 'messages', 'intake', 'to_book'], visit: ['visit', 'calendar', 'interview'], report: ['report', 'reports', 'report_editor'], followup: ['followup', 'followup_editor'], activity: ['activity', 'run'], patients: ['patients'] }))
    for (const page of pages) assert.equal(H.sectionOf(page), section);
});
test('to book filters stages and puts passed offers before visit dates', () => {
  const rows = [{ id: 1, stage: 'booking', visit_date: '2026-11-20' }, { id: 2, stage: 'visit', visit_date: '2026-01-01' }, { id: 3, stage: 'intake', state: 'offered', visit_date: '2026-11-01' }, { id: 4, stage: 'booking', visit_date: '2026-11-15' }, { id: 5, stage: 'intake' }];
  assert.deepEqual(H.toBook(rows, new Date('2026-11-14T12:00:00')).map((p) => p.id), [3, 4, 1, 5]);
});
test('engine steps have friendly names', () => {
  for (const step of ['intake_dry', 'intake_apply', 'pathology', 'interview_assist', 'interview_sheet', 'interview_pack', 'report_extract', 'report_start', 'report_assist', 'report_draft', 'interactions', 'report_build', 'claim', 'register_xlsx']) {
    assert.ok(H.steps[step], step);
    assert.doesNotMatch(H.stepLabel(step), /_/);
  }
  assert.equal(H.stepLabel('unknown_step'), 'Unknown step');
});
