const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

test('Interview tab targets the open patient detail on calendar, today and patients only', () => {
  assert.equal(H.interviewTabTarget('calendar', '2'), '2');
  assert.equal(H.interviewTabTarget('today', 7), '7');
  assert.equal(H.interviewTabTarget('patients', '12'), '12');
  assert.equal(H.interviewTabTarget('calendar', null), '');
  assert.equal(H.interviewTabTarget('calendar', ''), '');
  assert.equal(H.interviewTabTarget('calendar', 'abc'), '');
  assert.equal(H.interviewTabTarget('reports', '2'), '');
  assert.equal(H.interviewTabTarget('interview', '2'), '');
});

test('Interview tab uses the highlighted calendar stop patient when no detail is open', () => {
  assert.equal(H.interviewTabTarget('calendar', null, '2'), '2');
  assert.equal(H.interviewTabTarget('calendar', '5', '2'), '5');
  assert.equal(H.interviewTabTarget('calendar', null, ''), '');
  assert.equal(H.interviewTabTarget('today', null, '2'), '');
  assert.equal(H.interviewTabTarget('patients', null, '2'), '');
});

test('the default interview id still ignores a selection (documents the old path)', () => {
  const visits = [{ id: 1, visit_date: '2026-11-20', visit_time: '09:00', state: 'confirmed' }, { id: 2, visit_date: '2026-11-20', visit_time: '11:00', state: 'confirmed' }];
  assert.equal(H.defaultInterviewId(visits, new Date(2026, 10, 20, 8, 0)), '1');
});

test('applying a usage preset to an other-medicine row keeps the previous directions in Notes', () => {
  const document = { querySelector: () => null, addEventListener() {}, getElementById: () => null };
  const context = vm.createContext({ H: { ...H, autosaver: () => ({ changed() {} }) }, esc: H.esc, page: 'interview', document, window: {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({meds:[], other_meds:[['Fish oil','Take 2 with food','why','']], details:{meds:[],other_meds:[{}]}}); interviewChanged = () => {}; renderInterview = () => {};`, context);
  vm.runInContext(`interviewApplyPreset('other_meds', 0, ['PRN', 'When required'])`, context);
  assert.equal(vm.runInContext('interviewRecord.other_meds[0][1]', context), 'When required');
  assert.match(vm.runInContext('interviewRecord.other_meds[0][3]', context), /Previous directions: Take 2 with food/);
  vm.runInContext(`interviewApplyPreset('other_meds', 0, ['PRN', 'When required'])`, context);
  assert.doesNotMatch(vm.runInContext('interviewRecord.other_meds[0][3]', context), /Previous directions: When required/);
});

test('interview screen with no explicit patient shows the picker and loads no record', async () => {
  const calls = [], screen = { innerHTML: '' };
  const document = { querySelector: () => null, addEventListener() {}, getElementById: () => null };
  const hmr = { api: async (method, path) => { calls.push(path); if (path === '/api/patients') return { patients: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }] }; if (path === '/api/today') return { visits: [{ id: 1, visit_date: '2026-11-20', visit_time: '09:00', state: 'confirmed' }] }; return {}; } };
  const context = vm.createContext({ patients: [], H: { ...H, autosaver: () => ({ changed() {} }) }, esc: H.esc, page: 'interview', document, hmr, window: {}, $: id => id === 'screen' ? screen : null, errorText: String, navigate: async () => {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  await vm.runInContext('interviewScreen()', context);
  assert.ok(!calls.some(p => /\/interview$/.test(p)), calls.join(','));
  assert.match(screen.innerHTML, /Pick a patient to open their interview form/);
  assert.equal(vm.runInContext('interviewRecord', context), null);
  assert.equal(vm.runInContext('interviewId', context), '');
});

test('calendar stop highlight remembers a single-patient stop and resets on render', () => {
  const rows = [{ dataset: { stop: '0' }, classList: { toggle() {} } }, { dataset: { stop: '1' }, classList: { toggle() {} } }];
  const document = { querySelectorAll: () => rows, getElementById: () => null };
  const context = vm.createContext({ H, esc: H.esc, document, patients: [], hmr: {}, window: {}, $: () => null, L: undefined, dayMap: null });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/today.js'), 'utf8'), context);
  vm.runInContext(`selectedDay = '2026-11-20'; renderDayMap({ stops: [{ names: ['A'], patient_ids: [1] }, { names: ['B', 'C'], patient_ids: [2, 3] }, { names: ['D'] }] });`, context);
  assert.equal(vm.runInContext('highlightedStopPatient', context), '');
  vm.runInContext('highlightStop(0, [])', context);
  assert.equal(vm.runInContext('highlightedStopPatient', context), '1');
  vm.runInContext('highlightStop(1, [])', context);
  assert.equal(vm.runInContext('highlightedStopPatient', context), '');
  vm.runInContext('highlightStop(0, [])', context);
  vm.runInContext(`renderDayMap({ stops: [{ names: ['A'], patient_ids: [1] }] })`, context);
  assert.equal(vm.runInContext('highlightedStopPatient', context), '');
});
