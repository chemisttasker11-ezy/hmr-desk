const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
const patientSource = fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8');
const runSource = fs.readFileSync(require.resolve('../renderer/run.js'), 'utf8');

test('layout and tab changes preserve the active patient form and selection', async () => {
  const classes = new Set();
  const layout = { classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); } }, style: { setProperty(name, value) { this[name] = value; } } };
  const tabs = ['Overview', 'Conversation', 'Activity', 'Files'].map(name => ({ dataset: { tab: name }, classList: { toggle() {} }, setAttribute() {} }));
  const sections = Object.fromEntries(tabs.map(t => [`.${t.dataset.tab.toLowerCase()}-view`, { hidden: false }]));
  const detail = { hidden: false, value: 'unsaved', querySelectorAll: () => tabs, querySelector: selector => sections[selector] };
  const divider = { setAttribute(name, value) { this[name] = value; } };
  const nodes = { detail, 'patient-divider': divider };
  const context = vm.createContext({ H, $: id => nodes[id], selected: '12', page: 'patients', formOpen: true, detailTab: 'Overview',
    document: { querySelector: () => layout, querySelectorAll: () => [] }, confirm: () => false });
  vm.runInContext(patientSource, context);
  context.setPatientLayout('patient');
  assert.ok(classes.has('full-view'));
  context.setPatientLayout('list');
  assert.ok(classes.has('list-view'));
  context.resizePatientPane(64);
  context.setPatientLayout('split');
  assert.equal(layout.style['--patient-list-width'], '64%');
  assert.equal(divider['aria-valuenow'], '64');
  context.selectPatientTab('Conversation');
  assert.equal(sections['.conversation-view'].hidden, false);
  assert.equal(sections['.overview-view'].hidden, true);
  assert.equal(detail.value, 'unsaved');
  assert.deepEqual(JSON.parse(JSON.stringify(await context.openPatientWorkspace('13'))), { cancelled: true });
  assert.equal(context.selected, '12');
  context.page = 'messages'; context.navigate = async () => {};
  assert.deepEqual(JSON.parse(JSON.stringify(await context.openPatientWorkspace('13'))), { cancelled: true });
  assert.equal(context.selected, '12');
});

test('patient conversation shows chronological messages once and distinguishes draft and queued', async () => {
  const nodes = { detail: { querySelector: () => null }, 'offer-form': { addEventListener() {} } };
  const patient = { id: 5, name: 'Alex Example', stage: 'booking', state: 'offered', messages: [
    { id: 3, direction: 'out', state: 'queued', body: 'Queued note', created_at: '2026-01-03T10:00:00' },
    { id: 4, direction: 'out', state: 'sent', body: 'Repeated message', created_at: '2026-01-03T11:00:00' },
    { id: 5, direction: 'out', state: 'sent', body: 'Repeated message', created_at: '2026-01-03T11:00:00' },
    { id: 2, direction: 'out', state: 'draft', body: 'Draft note', created_at: '2026-01-02T10:00:00' },
    { id: 1, direction: 'in', state: 'received', body: 'Reply text', created_at: '2026-01-01T10:00:00' }
  ] };
  const context = vm.createContext({ H, esc: H.esc, date: H.date, $: id => nodes[id], selected: '', page: 'patients', detailTab: 'Conversation', formOpen: false,
    patients: [{ id: 5, next_step: 'wait for reply' }], renderPatients() {}, messageComposer: () => '', actionLabels: {}, localDate: () => '2026-01-01',
    hmr: { api: async (method, url) => url.endsWith('/timeline') ? { entries: [{ at: '2026-01-01T10:00:00', kind: 'message', label: 'SMS received', detail: 'Reply text' }, { at: '2026-01-01T10:01:00', kind: 'event', label: 'Confirmed by SMS', detail: 'Booking confirmed' }] } : url === '/api/messages/board' ? { outbox_mode: 'test', needs_you: [{ id: 1, direction: 'in' }] } : url === '/api/agents' ? {} : patient } });
  vm.runInContext(patientSource, context);
  await context.showPatient(5);
  const html = nodes.detail.innerHTML.split('<div class="conversation-thread"')[1].split('<div class="activity-view"')[0];
  assert.ok(html.indexOf('Reply text') < html.indexOf('Draft note'));
  assert.ok(html.indexOf('Draft note') < html.indexOf('Queued note'));
  assert.equal((html.match(/Reply text/g) || []).length, 1);
  assert.equal((html.match(/Repeated message/g) || []).length, 2);
  assert.match(html, /Confirmed by SMS/);
  assert.match(html, /Draft message/);
  assert.match(html, /Outbound[^]*?queued/);
  assert.match(html, /data-message-send="2" disabled/);
  assert.match(html, /data-resolve="yes" data-id="1" data-patient-id="5"/);
  assert.match(nodes.detail.innerHTML, /Waiting for reply - open conversation/);
});

test('run catalogue rejects stale steps and reports queued and skipped tasks', async () => {
  const calls = [], status = {}, button = { disabled: false };
  const document = { querySelectorAll: () => [button], querySelector: () => null };
  let reject = false;
  const context = vm.createContext({ H, esc: H.esc, date: H.date, page: 'patients', patients: [{ id: 7, name: 'Alex Example' }], document,
    $: id => id === 'queue-message' ? status : null, renderPatients() {}, errorText: e => e.message,
    hmr: { api: async (method, url, body) => { calls.push({ method, url, body }); if (method === 'GET') return { steps: [{ name: 'interview_sheet', label: 'Interview sheet' }], tasks: [] }; if (reject) throw new Error('invalid steps: bad'); return { enqueued: [{ id: 1 }], skipped: [{ patient_id: 7, step: 'interview_sheet', reason: 'already done' }] }; } } });
  vm.runInContext(runSource, context);
  await context.enqueue(['interview_spec'], [7]);
  assert.match(status.textContent, /Nothing started/);
  assert.equal(calls.filter(c => c.method === 'POST').length, 0);
  await context.enqueue(['interview_sheet'], [7]);
  assert.match(status.textContent, /1 task\(s\) queued/);
  assert.match(status.textContent, /Alex Example.*already done/);
  reject = true;
  await context.enqueue(['interview_sheet'], [7]);
  assert.match(status.textContent, /Nothing started: invalid steps: bad/);
});


test('bulk disclosure retains expansion, ticked steps and selected patients during refresh', () => {
  let disclosure;
  const bulk = { innerHTML: '', querySelector: () => disclosure };
  const nodes = { search: { value: '' }, chips: {}, bulk, detail: {}, 'patient-list': {} };
  const layout = { classList: { toggle() {} }, style: { setProperty() {} } };
  const context = vm.createContext({ H, esc: H.esc, date: H.date, page: 'patients', selected: '7', filter: 'All active',
    patients: [{ id: 7, name: 'Synthetic', stage: 'ready', next_step: 'make interview sheet' }], runPending: false,
    $: id => nodes[id], document: { querySelector: () => layout, querySelectorAll: () => [] } });
  vm.runInContext(patientSource, context); vm.runInContext(runSource, context);
  vm.runInContext("runStepsCatalog = [{name:'pathology',label:'Collect pathology'}]; checkedPatients.add(7); tickedSteps.add('pathology')", context);
  context.renderPatients();
  assert.match(bulk.innerHTML, /<details class="bulk-disclosure card" >/);
  assert.match(bulk.innerHTML, /Patients: 1 selected/); assert.match(bulk.innerHTML, /Steps: 1 ticked/);
  disclosure = { open: true, addEventListener() {} };
  context.renderPatients();
  assert.match(bulk.innerHTML, /<details class="bulk-disclosure card" open>/);
  assert.equal(vm.runInContext('checkedPatients.has(7) && tickedSteps.has("pathology")', context), true);
  disclosure.open = false; context.renderPatients();
  assert.match(bulk.innerHTML, /<details class="bulk-disclosure card" >/);
});

test('health groups only inactive portals and keeps unknown or failing states visible', async () => {
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  const fn = source.slice(source.indexOf('async function health()'), source.indexOf('async function refresh()'));
  const nodes = { health: { innerHTML: '', querySelector: () => ({ open: true }) }, 'next-visit': {} };
  let rejectTabs = false;
  const context = vm.createContext({ H, esc: H.esc, labels: { mhr: 'My Health Record', emims: 'eMIMS', ppa: 'PPA', amh: 'AMH' }, $: id => nodes[id],
    hmr: { api: async (_method, url) => url === '/api/status' ? { gateway_online: false, outbox_mode: 'test' } : { visits: [] },
      tab: async () => { if (rejectTabs) throw Error('unavailable'); return { mhr: 'not open', emims: 'not open', ppa: 'ready', amh: 'failed' }; } } });
  vm.runInContext(fn, context); await context.health();
  assert.match(nodes.health.innerHTML, /Engine connected/); assert.match(nodes.health.innerHTML, /Phone offline/);
  assert.match(nodes.health.innerHTML, /Outbox TEST/); assert.match(nodes.health.innerHTML, /Portals: 2 not open/);
  assert.match(nodes.health.innerHTML, /portal-inactive" open/); assert.match(nodes.health.innerHTML, /PPA: ready/); assert.match(nodes.health.innerHTML, /AMH: failed/);
  rejectTabs = true; await context.health();
  assert.doesNotMatch(nodes.health.innerHTML, /Portals: .* not open/); assert.match(nodes.health.innerHTML, /My Health Record: unknown/);
});


test('health refresh restores keyboard focus to the equivalent portal control', async () => {
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  const fn = source.slice(source.indexOf('async function health()'), source.indexOf('async function refresh()'));
  const body = {}, outside = {}, doc = { body, activeElement: body };
  const original = kind => ({ dataset: kind === 'summary' ? {} : { page: kind }, matches: () => kind === 'summary' });
  let focused, tabState = 'not open', oldFocus, groupOpen = true, allReady = false;
  const makeTarget = (selector, group = null) => ({ closest: () => group, focus(options) { focused = { selector, options }; doc.activeElement = this; } });
  const healthNode = {
    contains: node => node === oldFocus,
    set innerHTML(value) { this.html = value; if (doc.activeElement === oldFocus) doc.activeElement = body; },
    querySelector(selector) {
      if (selector === '.portal-inactive') return { open: groupOpen };
      if (selector === '.portal-inactive > summary' && allReady) return null;
      const group = selector === '[data-page="mhr"]' && tabState === 'not open'
        ? { open: groupOpen, querySelector: () => makeTarget('.portal-inactive > summary') } : null;
      return makeTarget(selector, group);
    },
  };
  const nodes = { health: healthNode, 'next-visit': {} };
  const context = vm.createContext({ document: doc, H, esc: H.esc, labels: { mhr: 'My Health Record', emims: 'eMIMS', ppa: 'PPA', amh: 'AMH' }, $: id => nodes[id],
    hmr: { api: async (_method, url) => url === '/api/status' ? { gateway_online: false, outbox_mode: 'test' } : { visits: [] },
      tab: async () => ({ mhr: tabState, emims: allReady ? 'ready' : 'not open', ppa: 'ready', amh: allReady ? 'ready' : 'not open' }) } });
  vm.runInContext(fn, context);
  oldFocus = original('summary'); doc.activeElement = oldFocus; await context.health();
  assert.equal(focused.selector, '.portal-inactive > summary'); assert.equal(focused.options.preventScroll, true);
  oldFocus = original('mhr'); doc.activeElement = oldFocus; tabState = 'ready'; await context.health();
  assert.equal(focused.selector, '[data-page="mhr"]');
  oldFocus = original('mhr'); doc.activeElement = oldFocus; tabState = 'not open'; groupOpen = false; await context.health();
  assert.equal(focused.selector, '.portal-inactive > summary');
  oldFocus = original('summary'); doc.activeElement = oldFocus; tabState = 'ready'; allReady = true; await context.health();
  assert.equal(focused.selector, '[data-page]');
  focused = null; oldFocus = original('mhr'); doc.activeElement = outside; await context.health();
  assert.equal(focused, null); assert.equal(doc.activeElement, outside);
});

test('in-flight background patient reads cannot replace newly expanded actions', async () => {
  let resolveBoard, expanded = false;
  const board = new Promise(resolve => { resolveBoard = resolve; });
  const detail = { innerHTML: 'expanded actions stay here', querySelector: () => expanded ? {} : null };
  const context = vm.createContext({ H, $: id => id === 'detail' ? detail : null, page: 'patients', selected: '5', formOpen: false,
    detailTab: 'Overview', renderPatients() {}, hmr: { api: async (method, path) => path.endsWith('/timeline') ? { milestones: {} } : path === '/api/messages/board' ? board : path === '/api/agents' ? {} : { id: 5 } } });
  vm.runInContext(patientSource, context);
  const reading = context.showPatient(5, undefined, true);
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  expanded = true;
  resolveBoard({});
  assert.equal(await reading, false);
  assert.equal(detail.innerHTML, 'expanded actions stay here');
});

test('failed reselection keeps the list usable and intake open still reaches the target patient', async () => {
  const calls = [];
  const node = () => ({ hidden: false, textContent: '', innerHTML: '', value: '', dataset: {}, style: { setProperty() {} },
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false }, setAttribute() {}, addEventListener() {},
    appendChild() {}, querySelector: () => null, querySelectorAll: () => [], contains: () => false });
  const nodes = {};
  const $ = (id) => nodes[id] || (nodes[id] = node());
  const hmr = { api: async (method, path) => {
    calls.push(method + ' ' + path);
    if (path === '/api/patients/stale-id') throw new Error('not found');
    if (path === '/api/patients/13') return { id: 13, name: 'Target Patient', change_kinds: [], files: {} };
    if (path === '/api/patients/13/timeline') return { milestones: {} };
    return {};
  } };
  const context = vm.createContext({ H, $, hmr, esc: H.esc, date: H.date, group: H.group, sentence: H.sentence, actionLabels: {}, actionFields: {}, actionButton: () => '', aiInfo: () => '', stageText: () => '', messageComposer: () => '', localDate: () => '2026-11-17', selected: 'stale-id', page: 'patients', formOpen: false, detailTab: 'Overview',
    patients: [], filter: 'All active', patientSort: 'urgency', appointmentRange: 'all', runMessage: '', patientWidth: 50, patientLayout: 'split', fullPatientView: false, searchTimer: 0, messagesTimer: 0, runTimer: 0,
    patientRequest: 0, navToken: 0, offerPatient: '', offerDraft: null, offerStatus: '', confirm: () => true, alert() {},
    document: { querySelector: () => node(), querySelectorAll: () => [], activeElement: null },
    errorText: (e) => String(e && e.message || e), setTimeout: () => 0, clearTimeout() {} });
  vm.runInContext(patientSource, context);
  const before = calls.length;
  const shown = await context.reselectActivePatient('stale-id', true);
  assert.equal(shown, false);
  assert.equal(context.selected, null, 'stale selection is cleared');
  assert.ok(calls.slice(before).includes('GET /api/patients/stale-id'), 'selection fetch attempted');
  assert.equal(nodes['patient-selection-error'].hidden, false, 'local recoverable error shown');
  assert.match(nodes['patient-selection-error'].textContent, /not found/, 'real error text preserved');
  nodes['detail'] = node();
  context.page = 'intake';
  context.navigate = async () => { context.page = 'patients'; };
  const openCalls = calls.length;
  await context.openPatientWorkspace(13);
  assert.ok(calls.slice(openCalls).includes('GET /api/patients/13'), 'intake target open attempted after prior selection failure');
});
