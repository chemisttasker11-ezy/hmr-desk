const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers');
test('stage text and flag words describe engine data', () => {
  assert.equal(H.stageText({ stage: 'booking', stage_step: 'offered' }), 'Booking &middot; offered');
  assert.deepEqual(H.flagWords({ stage: 'hold', flags: ['reply_waiting', 'folder_mismatch'], folder_check: { actual: 'Scheduled', expected: 'Visited' } }), ['Reply waiting', 'Folder is in Scheduled, expected Visited', 'On hold']);
});
test('actions follow the stage and follow-up milestones', () => {
  assert.deepEqual(H.stageActions({ stage: 'hold' }), ['resume']);
  assert.ok(H.stageActions({ stage: 'ready' }).includes('pathology_outcome'));
  assert.ok(!H.stageActions({ stage: 'booking' }).includes('visited'));
  assert.ok(H.stageActions({ stage: 'done', flags: ['archive_suggested'] }, { followup1_done: '2026-01-01' }).includes('followup1_claimed'));
});
test('urgent patients precede dates and names', () => {
  const rows = [{ name: 'Z', visit_date: '2026-01-01', flags: [] }, { name: 'B', flags: ['reply_waiting'] }, { name: 'A', flags: ['offer_passed'] }].sort(H.urgencySort);
  assert.deepEqual(rows.map(p => p.name), ['A', 'B', 'Z']);
});

test('stage classes and patient next steps', () => {
  for (const [stage, expected] of Object.entries({ intake: 'booking', booking: 'booking', ready: 'ready', report: 'report', claim: 'report', followup: 'followup', hold: 'hold', declined: 'declined', expired: 'declined', done: 'done', archived: 'done' })) assert.equal(H.stageClass(stage), expected);
  for (const stage of ['declined', 'expired', 'done', 'hold', 'archived']) assert.equal(H.hasNextStep({ stage, next_step: 'visit' }), false);
  assert.equal(H.hasNextStep({ stage: 'booking' }), false);
  assert.equal(H.hasNextStep({ stage: 'booking', next_step: 'visit' }), true);
});
