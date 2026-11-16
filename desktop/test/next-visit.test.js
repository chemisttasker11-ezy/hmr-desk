const test = require('node:test');
const assert = require('node:assert/strict');
const { nextVisitText, defaultInterviewId } = require('../renderer/helpers');
const now = new Date(2026, 10, 14, 8, 40);
const visit = (date, time, state = 'confirmed') => ({ id: 4, visit_date: date, visit_time: time, state, suburb: 'Pimpama' });
test('next visit shows a later visit today and its remaining time', () => {
  assert.equal(nextVisitText([visit('2026-11-14', '10:00')], now), 'Next visit 10:00 &middot; Pimpama &middot; in 1 h 20 min');
});
test('next visit shows tomorrow without a countdown', () => {
  assert.equal(nextVisitText([visit('2026-11-15', '10:00', 'sheet_ready')], now), 'Next visit tomorrow 10:00 &middot; Pimpama');
});
test('next visit excludes unconfirmed and other days', () => {
  assert.equal(nextVisitText([visit('2026-11-14', '10:00', 'offered'), visit('2026-11-16', '10:00')], now), 'No visit today or tomorrow');
});
test('next visit skips one that has already started', () => {
  assert.equal(nextVisitText([visit('2026-11-14', '08:00'), visit('2026-11-15', '10:00')], now), 'Next visit tomorrow 10:00 &middot; Pimpama');
});
test('interview default only picks a confirmed visit today', () => {
  assert.equal(defaultInterviewId([visit('2026-11-15', '10:00'), visit('2026-11-14', '10:00', 'offered')], now), '');
  assert.equal(defaultInterviewId([visit('2026-11-14', '10:00', 'pathology_ready')], now), '4');
});
