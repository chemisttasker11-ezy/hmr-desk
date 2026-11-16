const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { hidden: false, textContent: '', innerHTML: '', dataset: {}, removeAttribute() {} });
    return elements.get(id);
  };
  const main = { scrollTop: 0 };
  const context = vm.createContext({
    H: { esc: String, date: String, group: String, sentence: String, sectionOf: id => id },
    document: { getElementById: element, querySelector: () => main },
    hmr: { tab: async () => {}, oneOff: async () => [] },
    clearInterval() {}, setInterval() {}, clearTimeout() {}, confirm: () => true,
    alert: message => { context.lastError = message; }, runTimer: null, pickerOpen: false,
    interviewId: '', reportId: '', followupId: '', followupNumber: '',
    leaveInterview: async () => { context.interviewId = ''; return true; },
    leaveReport: async () => true, leaveFollowup: async () => true,
  });
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  vm.runInContext(source.slice(0, source.indexOf('function errorText(error)')), context);
  vm.runInContext("refresh = async () => {}; showResults = () => {}; errorText = error => error.message;", context);
  return { context, main };
}

test('return from a first portal page restores the interview and scroll', async () => {
  const { context: c, main } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42'; main.scrollTop = 480;
  await vm.runInContext("navigate('amh')", c);
  assert.equal(c.interviewId, '');
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'interview');
  assert.equal(c.interviewId, '42');
  assert.equal(main.scrollTop, 480);
});

test('nested history returns in order and a cancelled leave keeps the target', async () => {
  const { context: c } = setup();
  await vm.runInContext("(async () => { await navigate('patients'); await navigate('interview'); })()", c);
  c.interviewId = '7';
  c.leaveInterview = async () => false;
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'interview');
  c.leaveInterview = async () => true;
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'patients');
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'today');
});

test('return reports errors and retains history for a retry', async () => {
  const { context: c } = setup();
  await vm.runInContext("navigate('amh')", c);
  c.hmr.tab = async () => { throw Error('Cannot hide portal'); };
  await vm.runInContext('goBack()', c);
  assert.equal(c.lastError, 'Cannot hide portal');
  assert.equal(vm.runInContext('navigationHistory.length', c), 1);
});

test('portal Page back uses web history and falls back to app history at the first page', async () => {
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  const handler = source.slice(source.indexOf("$('back').onclick ="), source.indexOf("$('reload').onclick ="));
  let webBack = true, returned = 0;
  const button = {}, results = {};
  const c = vm.createContext({ $: id => id === 'back' ? button : results, page: 'amh',
    hmr: { tab: async () => webBack }, goBack: async () => { returned++; }, errorText: error => error.message });
  vm.runInContext(handler, c);
  await button.onclick();
  assert.equal(returned, 0);
  webBack = false;
  await button.onclick();
  assert.equal(returned, 1);
});

test('a screen with no app history returns to Today', async () => {
  const { context: c } = setup();
  vm.runInContext("page = 'amh'", c);
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'today');
});

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('a newer navigation wins while Back waits for a native view change', async () => {
  const { context: c } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42';
  await vm.runInContext("navigate('amh')", c);
  const gate = deferred(), calls = [];
  let first = true;
  c.hmr.tab = async (action, site) => {
    calls.push([action, site]);
    if (first) { first = false; await gate.promise; }
  };
  const back = vm.runInContext('goBack()', c);
  await Promise.resolve(); await Promise.resolve();
  const newer = vm.runInContext("navigate('emims')", c);
  gate.resolve();
  await Promise.all([back, newer]);
  assert.equal(vm.runInContext('page', c), 'emims');
  assert.equal(vm.runInContext('navigationHistory.length', c), 3);
  assert.deepEqual(calls.at(-1), ['open', 'emims']);
});

test('a stale guarded navigation cannot restore its identity or open its tab', async () => {
  const { context: c } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42';
  const gate = deferred(), calls = [];
  c.leaveInterview = async () => { await gate.promise; return true; };
  c.hmr.tab = async (action, site) => { calls.push([action, site]); };
  const older = vm.runInContext("navigate('amh', {page:'amh', interviewId:'old', scroll:0})", c);
  const newer = vm.runInContext("navigate('emims')", c);
  gate.resolve();
  await Promise.all([older, newer]);
  assert.equal(vm.runInContext('page', c), 'emims');
  assert.equal(c.interviewId, '42');
  assert.deepEqual(calls, [['open', 'emims']]);
});

test('overlapping editor leaves share one guard and cannot clear the winning editor later', async () => {
  const { context: c } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42'; c.interviewRecord = { id: '42' };
  const gate = deferred();
  let calls = 0;
  c.leaveInterview = async () => { calls++; await gate.promise; c.interviewId = ''; c.interviewRecord = null; return true; };
  c.refresh = async () => { c.interviewRecord = { id: c.interviewId }; };
  const leaving = vm.runInContext("navigate('amh')", c);
  const staying = vm.runInContext("navigate('interview')", c);
  gate.resolve();
  await Promise.all([leaving, staying]);
  assert.equal(calls, 1);
  assert.equal(vm.runInContext('page', c), 'interview');
  assert.equal(c.interviewId, '42');
  assert.deepEqual(c.interviewRecord, { id: '42' });
});

test('a failed shared leave guard preserves the Back history entry', async () => {
  const { context: c } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42';
  const gate = deferred();
  let calls = 0;
  c.leaveInterview = async () => { calls++; await gate.promise; return false; };
  const back = vm.runInContext('goBack()', c);
  const newer = vm.runInContext("navigate('amh')", c);
  gate.resolve();
  await Promise.all([back, newer]);
  assert.equal(calls, 1);
  assert.equal(vm.runInContext('page', c), 'interview');
  assert.equal(vm.runInContext('navigationHistory.length', c), 1);
  assert.equal(c.interviewId, '42');
});

test('record visit patient navigation keeps the interview in Back history', async () => {
  const { context: c, main } = setup();
  await vm.runInContext("navigate('interview')", c);
  c.interviewId = '42'; main.scrollTop = 350;
  await vm.runInContext("navigate('patients', { selected: '42', detailTab: 'Overview', scroll: 0 })", c);
  assert.equal(vm.runInContext('selected', c), '42');
  await vm.runInContext('goBack()', c);
  assert.equal(vm.runInContext('page', c), 'interview');
  assert.equal(c.interviewId, '42');
  assert.equal(main.scrollTop, 350);
});
