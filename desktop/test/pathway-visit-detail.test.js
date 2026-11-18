const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');

const visitDetail = (p) => H.patientPathway(p, {}, []).find((s) => s.id === 'visit').detail;

test('visit step says awaiting booking only when no visit is booked', () => {
  assert.equal(visitDetail({ stage: 'booking', state: 'offered', visit_date: '' }), 'Awaiting booking');
  assert.equal(visitDetail({ stage: 'intake', state: 'new' }), 'Awaiting booking');
});

test('a booked visit is never described as awaiting booking', () => {
  assert.equal(visitDetail({ stage: 'booking', state: 'confirmed', visit_date: '2999-01-01', visit_time: '09:00' }), 'Booked, awaiting visit day');
  assert.equal(visitDetail({ stage: 'booking', state: 'confirmed', visit_date: '2000-01-01', visit_time: '09:00' }), 'Visit due');
});

test('ready and visited keep their wording', () => {
  assert.equal(visitDetail({ stage: 'ready', state: 'confirmed', visit_date: '2999-01-01' }), 'Ready for visit');
  assert.equal(visitDetail({ stage: 'report', state: 'visited', visit_date: '2000-01-01' }), 'Visit recorded');
});
