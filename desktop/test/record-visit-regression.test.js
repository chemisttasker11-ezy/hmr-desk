const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const helpers = require('../renderer/helpers');

test('Record visit saves the interview, opens the date form, and posts for that patient', async () => {
  const calls = [], alerts = [];
  let submit;
  const button = { disabled: false };
  const nodes = {
    detail: { querySelector: () => null },
    'offer-form': { addEventListener() {} },
    'action-area': {}, 'action-error': {},
    'action-form': { scrollIntoView() {}, querySelector: selector => selector === 'input, select' ? { focus() {} } : button, addEventListener: (_, fn) => { submit = fn; } },
  };
  const patient = { id: 42, name: 'Synthetic', state: 'confirmed', stage: 'booking', visit_date: '2026-11-01' };
  const hmr = { api: async (method, url, body) => {
    calls.push([method, url, body]);
    if (url === '/api/patients') return { patients: [patient] };
    if (url.endsWith('/timeline')) return { entries: [], milestones: {} };
    if (url === '/api/messages/board' || url === '/api/agents') return {};
    if (url === '/api/patients/42') return patient;
    return {};
  } };
  const H = { ...helpers, stageActions: () => ['visited'], autosaver: ({ endpoint, getId, getRecord }) => ({
    save: async () => { await endpoint(getId(), getRecord()); return true; },
  }) };
  const context = vm.createContext({ H, hmr, esc: H.esc, date: H.date, localDate: () => '2026-11-16',
    page: 'interview', selected: '', detailTab: 'Overview', formOpen: false, patients: [patient],
    actionFields: { visited: ['date'] }, actionLabels: { visited: 'Mark visited' },
    $: id => nodes[id], renderPatients() {}, messageComposer: () => '',
    document: { addEventListener() {}, querySelector: () => null },
    FormData: class { constructor() { return [['date', '2026-11-01']]; } },
    errorText: e => e.message, alert: text => alerts.push(text),
    refresh: async () => { throw Error('refresh unavailable'); },
    navigate: async id => { await hmr.api('GET', '/api/patients'); context.page = id; },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext("interviewId = '42'; interviewRecord = { notes: 'Synthetic' }; setPatientLayout = () => {}", context);
  await vm.runInContext("interviewClick({dataset:{interviewRecordVisit:''}})", context);
  assert.deepEqual(calls.slice(0, 4).map(x => x.slice(0, 2)), [
    ['POST', '/api/patients/42/interview'], ['GET', '/api/patients'],
    ['GET', '/api/patients/42'], ['GET', '/api/patients/42/timeline'],
  ]);
  assert.match(nodes['action-area'].innerHTML, /name="date"/);
  assert.equal(typeof submit, 'function');
  context.selected = '99';
  await submit({ preventDefault() {}, target: { querySelector: () => button } });
  const post = calls.find(x => x[1].endsWith('/action'));
  assert.equal(post[1], '/api/patients/42/action');
  assert.deepEqual(JSON.parse(JSON.stringify(post[2])), { action: 'visited', date: '2026-11-01' });
  assert.match(alerts[0], /Visit recorded, but the patient view could not be refreshed/);
  assert.equal(button.disabled, true);
});

test('error text preserves patient and unknown-route errors without claiming an update is needed', () => {
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('function errorText(error)'), source.indexOf('async function health()')), context);
  assert.equal(context.errorText({ status: 404, message: 'patient not found' }), 'patient not found');
  assert.equal(context.errorText({ status: 404, message: 'not found' }), 'not found');
  assert.equal(context.errorText({ status: 400, message: 'file not found' }), 'file not found');
});

test('an acknowledged visit reports a refresh that swallowed its own error', async () => {
  let submit, postCount = 0;
  const alerts = [], button = {};
  const nodes = { detail: {}, 'action-area': {}, 'action-error': {},
    'action-form': { scrollIntoView() {}, querySelector: selector => selector === 'input, select' ? { focus() {} } : button, addEventListener: (_, fn) => { submit = fn; } } };
  const c = vm.createContext({ H: helpers, esc: helpers.esc, date: helpers.date, localDate: () => '2026-11-16',
    $: id => nodes[id], page: 'patients', selected: '42', formOpen: false, detailTab: 'Overview',
    patients: [], actionFields: { visited: ['date'] }, actionLabels: { visited: 'Mark visited' },
    FormData: class { constructor() { return [['date', '2026-11-01']]; } },
    hmr: { api: async method => { if (method === 'POST') postCount++; return { id: 42 }; } },
    refresh: async () => { delete nodes.detail; }, alert: text => alerts.push(text), errorText: e => e.message,
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), c);
  c.openForm('visited', { id: 42 });
  await submit({ preventDefault() {}, target: { querySelector: () => button } });
  assert.equal(postCount, 1);
  assert.equal(button.disabled, true);
  assert.match(alerts[0], /Visit recorded, but the patient view could not be refreshed/);
});

test('real navigation refresh targets the interview patient even with a missing previous selection', async () => {
  async function run(useOldHandler) {
    const calls = [];
    const nodes = {
      screen: { dataset: {}, removeAttribute() {}, set innerHTML(value) { this.html = value; if (value.includes('class="error"')) delete nodes.detail; }, get innerHTML() { return this.html || ''; } },
      detail: { hidden: false, contains: () => false, querySelector: () => null },
      search: {}, 'offer-form': { addEventListener() {} }, 'action-area': {},
      'action-form': { scrollIntoView() {}, querySelector: () => null, addEventListener() {} },
    };
    for (const id of ['nav', 'title', 'section-tabs', 'toolbar', 'save-sign-in', 'results']) nodes[id] = {};
    const patient = { id: 42, name: 'Synthetic', state: 'confirmed', stage: 'booking', visit_date: '2026-11-01' };
    const hmr = { tab: async () => {}, api: async (method, url) => {
      calls.push([method, url]);
      if (url === '/api/patients/99') throw Object.assign(Error('patient not found'), { status: 404 });
      if (url === '/api/patients') return { patients: [patient] };
      if (url === '/api/run') return {};
      if (url.endsWith('/timeline')) return { entries: [], milestones: {} };
      if (url === '/api/patients/42') return patient;
      return {};
    } };
    const H = { ...helpers, stageActions: () => ['visited'], autosaver: ({ endpoint, getId, getRecord }) => ({
      save: async () => { await endpoint(getId(), getRecord()); return true; }, leave: async () => true,
    }) };
    const main = { scrollTop: 0 };
    const context = vm.createContext({ H, hmr, document: { getElementById: id => nodes[id], querySelector: () => main, addEventListener() {}, activeElement: null },
      clearInterval() {}, clearTimeout() {}, setTimeout() {}, alert() {}, confirm: () => true,
      runTimer: null, pickerOpen: false, reportId: '', followupId: '', followupNumber: '',
      health: async () => {}, leaveReport: async () => true, messageComposer: () => '',
    });
    const renderer = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
    vm.runInContext(renderer.slice(0, renderer.indexOf('async function health()')) + renderer.slice(renderer.indexOf('async function refresh()'), renderer.indexOf('async function runJob(')), context);
    vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
    let interview = fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8');
    if (useOldHandler) interview = interview.replace("navigate('patients', { selected: String(id), detailTab: 'Overview', scroll: 0 })", "navigate('patients')");
    vm.runInContext(interview, context);
    vm.runInContext("page = 'interview'; selected = '99'; interviewId = '42'; interviewRecord = {notes:'Synthetic'}; renderPatients = () => {}; setPatientLayout = () => {}", context);
    await vm.runInContext("interviewClick({dataset:{interviewRecordVisit:''}})", context);
    return { calls, nodes, selected: vm.runInContext('selected', context) };
  }
  const before = await run(true);
  assert(before.calls.some(([, url]) => url === '/api/patients/99'));
  assert.equal(before.nodes.screen.innerHTML.includes('class="error"'), false, 'stale selection no longer wipes the patients page');
  assert.equal(before.selected, '42', 'intended patient still opens after the stale selection failure');
  assert.match(before.nodes['action-area'].innerHTML, /name="date"/, 'old handler path now heals and renders the patient actions');
  const after = await run(false);
  assert(!after.calls.some(([, url]) => url === '/api/patients/99'));
  assert.match(after.nodes['action-area'].innerHTML, /name="date"/);
  assert.equal(after.nodes.screen.innerHTML.includes('class="error"'), false);
});

test('a saved booking redraws the patient even when refresh skips a focused form, and clears the old error', async () => {
  let submit, shown = 0, posts = 0, failFirst = true;
  const button = {}, error = { textContent: '' };
  const nodes = { detail: {}, 'action-area': {}, 'action-error': error,
    'action-form': { scrollIntoView() {}, querySelector: selector => selector === 'input, select' ? { focus() {} } : button, addEventListener: (_, fn) => { submit = fn; } } };
  const c = vm.createContext({ H: helpers, esc: helpers.esc, date: helpers.date, localDate: () => '2026-11-18',
    $: id => nodes[id], page: 'patients', selected: '7', formOpen: false, detailTab: 'Overview',
    patients: [], actionFields: { book_phone: ['date', 'time', 'end'] }, actionLabels: { book_phone: 'Book by phone' },
    FormData: class { constructor() { return [['date', '2026-11-18'], ['time', '09:00'], ['end', '10:00']]; } },
    hmr: { api: async method => { if (method === 'POST') { posts++; if (failFirst) { failFirst = false; throw Error('invalid time'); } } return {}; } },
    refresh: async () => {}, alert() {}, errorText: e => e.message,
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), c);
  c.showPatient = async () => { shown++; return true; };
  c.openForm('book_phone', { id: 7 });
  await submit({ preventDefault() {}, target: { querySelector: () => button } });
  assert.equal(error.textContent, 'invalid time');
  assert.equal(button.disabled, false);
  assert.equal(shown, 0);
  await submit({ preventDefault() {}, target: { querySelector: () => button } });
  assert.equal(posts, 2);
  assert.equal(error.textContent, '');
  assert.equal(shown, 1);
});
