const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

function load(tasksByCall, overrides = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/reports.js'), 'utf8');
  const calls = { api: 0, reports: 0 };
  const context = { H, esc: H.esc, document: { addEventListener() {} }, window: {}, page: 'reports', formOpen: false, setTimeout: (fn) => fn(), ...overrides,
    hmr: { api: async () => { const t = tasksByCall[Math.min(calls.api++, tasksByCall.length - 1)]; return { tasks: t }; } } };
  vm.createContext(context);
  vm.runInContext(source + '\nthis.refreshReportsAfterTask = refreshReportsAfterTask; reports = async () => { counters.reports++; };', context);
  context.counters = calls;
  return { context, calls };
}

test('a Reports card is redrawn once the queued job stops running', async () => {
  const run = (state) => [{ patient_id: 2, step: 'report_start', state }];
  const { context, calls } = load([run('queued'), run('running'), run('done')]);
  assert.equal(await context.refreshReportsAfterTask('report_start', 2, 30, 0), true);
  assert.equal(calls.reports, 1); assert.equal(calls.api, 3);
});

test('no redraw when the user left the Reports page, a medicine form is open, or a form is dirty', async () => {
  const done = [[{ patient_id: 2, step: 'report_start', state: 'done' }]];
  for (const set of [{ page: 'patients' }, { formOpen: true }]) {
    const { context, calls } = load(done, set);
    assert.equal(await context.refreshReportsAfterTask('report_start', 2, 5, 0), false); assert.equal(calls.reports, 0);
  }
  const { context, calls } = load(done);
  vm.runInContext('medicinePatient = "2"', context);
  assert.equal(await context.refreshReportsAfterTask('report_start', 2, 5, 0), false); assert.equal(calls.reports, 0);
});

test('a job for another patient or step does not hold the redraw', async () => {
  const { context, calls } = load([[{ patient_id: 3, step: 'report_start', state: 'running' }, { patient_id: 2, step: 'report_build', state: 'running' }]]);
  assert.equal(await context.refreshReportsAfterTask('report_start', 2, 5, 0), true); assert.equal(calls.reports, 1);
});
