const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
const source = fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8');
const localDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

test('appointment ranges use local calendar days and Monday to Sunday weeks', () => {
  const c = vm.createContext({ H, localDate });
  vm.runInContext(source, c);
  const bounds = (range, day) => Array.from(c.appointmentBounds(range, day));
  assert.deepEqual(bounds('today', new Date(2026, 11, 31, 23, 30)), ['2026-12-31', '2026-12-31']);
  assert.deepEqual(bounds('week', new Date(2027, 0, 3)), ['2026-12-28', '2027-01-03']);
  assert.deepEqual(bounds('month', new Date(2028, 1, 29)), ['2028-02-01', '2028-02-29']);
  assert.equal(c.appointmentBounds('all'), null);
});

test('sorts names without titles and dates with missing values last', () => {
  const c = vm.createContext({ H, localDate });
  vm.runInContext(source, c);
  const rows = [
    { id: 3, name: 'Mrs Zoe Alpha', visit_date: '2026-11-02', visit_time: '10:00', referral_date: '2026-01-01' },
    { id: 2, name: 'Dr Amy Zulu', visit_date: '2026-11-02', visit_time: '09:00', referral_date: '2026-02-01' },
    { id: 1, name: 'Ben Beta' },
  ];
  const ids = sort => { vm.runInContext(`patientSort = '${sort}'`, c); return rows.slice().sort(c.patientSortCompare).map(p => p.id); };
  assert.deepEqual(ids('first'), [2, 1, 3]);
  assert.deepEqual(ids('last'), [3, 1, 2]);
  assert.deepEqual(ids('referral'), [2, 3, 1]);
  assert.deepEqual(ids('appointment'), [2, 3, 1]);
});

test('actual list combines search, stage and appointment range without disturbing open form or checked patients', () => {
  const now = new Date(), today = localDate(now);
  const detail = { hidden: false, unsaved: 'keep this' };
  const nodes = { search: { value: 'alex' }, chips: {}, bulk: { querySelector: () => null }, detail, 'patient-list': {} };
  const c = vm.createContext({ H, localDate, esc: H.esc, date: H.date, $: id => nodes[id],
    selected: '1', detailTab: 'Conversation', formOpen: true, page: 'patients', filter: 'Booking',
    patients: [
      { id: 1, name: 'Alex Zulu', stage: 'booking', visit_date: today, referral_date: '2026-01-01' },
      { id: 2, name: 'Alex Alpha', stage: 'booking', visit_date: today, referral_date: '2026-02-01' },
      { id: 3, name: 'Alex Other', stage: 'report', visit_date: today },
      { id: 4, name: 'Alex No date', stage: 'booking' },
      { id: 5, name: 'Ben Other', stage: 'booking', visit_date: today },
    ],
    document: { querySelector: () => null },
  });
  vm.runInContext(source, c);
  vm.runInContext("patientSort = 'last'; appointmentRange = 'today'; checkedPatients.add(1); setPatientLayout = () => {}; selectedSteps = () => []; stepCheckboxes = () => ''", c);
  c.runPending = false;
  c.renderPatients();
  const html = nodes['patient-list'].innerHTML;
  assert(html.indexOf('Alex Alpha') < html.indexOf('Alex Zulu'));
  assert.doesNotMatch(html, /Alex Other|Alex No date|Ben Other/);
  assert.match(html, /2 patients/);
  assert.equal(detail.unsaved, 'keep this');
  assert.equal(c.selected, '1'); assert.equal(c.detailTab, 'Conversation'); assert.equal(c.formOpen, true);
  assert.equal(vm.runInContext('checkedPatients.has(1)', c), true);
  vm.runInContext("patientSort = 'referral'; appointmentRange = 'all'; filter = 'All active'", c);
  c.renderPatients();
  assert.match(nodes['patient-list'].innerHTML, /<th>Referral<\/th>/);
  assert.match(nodes['patient-list'].innerHTML, /01\/02\/2026/);
  assert.match(nodes['patient-list'].innerHTML, /Alex No date/);
});
