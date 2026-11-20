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
