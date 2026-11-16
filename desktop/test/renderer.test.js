const test = require('node:test');
const assert = require('node:assert/strict');
const { group, sentence, date } = require('../renderer/helpers');
test('groups engine states for filters', () => {
  assert.equal(group('pathology_ready'), 'Scheduled');
  assert.equal(group('report_drafted'), 'Visited');
  assert.equal(group('offered'), 'Offered');
});
test('formats dates and event sentences', () => {
  assert.equal(date('2026-11-12T10:30:00'), '12/11/2026');
  assert.equal(sentence({ type: 'note', detail: '{"text":"Call first"}' }), 'Note added: Call first');
  assert.equal(sentence({ type: 'visited', detail: 'invalid' }), 'Visit completed');
});

test('maps engine steps and groups waiting tasks', () => {
  const { stepName, taskGroups, steps } = require('../renderer/helpers');
  assert.equal(stepName('collect pathology'), 'pathology');
  assert.equal(stepName('prepare interview sheet'), 'interview_sheet');
  assert.equal(stepName('visit'), undefined);
  assert.equal(steps.report_build, 'Build report');
  assert.deepEqual(taskGroups([{ state: 'waiting', waiting_for: 'mhr' }, { state: 'done' }]), {
    mhr: [{ state: 'waiting', waiting_for: 'mhr' }],
  });
});

test('selects common bulk steps and formats locations', () => {
  const { commonStep, suburb, displayAddress } = require('../renderer/helpers');
  assert.equal(
    commonStep([{ next_step: 'build report' }, { next_step: 'build report' }, { next_step: 'visit' }]),
    'report_build',
  );
  assert.equal(suburb('Sampleton 4000'), 'Sampleton');
  assert.equal(displayAddress('1 Street, Sampleton 4000', 'Sampleton 4000'), '1 Street, Sampleton 4000');
  assert.equal(suburb('4217 Main Beach'), 'Main Beach');
  assert.equal(
    displayAddress('8/14 Macarthur Parade Main Beach QLD 4217', '4217 Main Beach'),
    '8/14 Macarthur Parade Main Beach QLD 4217',
  );
  assert.equal(displayAddress('1 Example Street', '4217 Main Beach'), '1 Example Street, Main Beach');
});

test('report buttons use engine readiness and keep medicine confirmation editable', () => {
  const vm = require('node:vm');
  const fs = require('node:fs');
  const { esc } = require('../renderer/helpers');
  const context = vm.createContext({ esc, H: require('../renderer/helpers') });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/reports.js'), 'utf8'), context);
  const row = context.reportRow(
    { id: 2, name: '<Test>', state: 'visited' },
    {
      steps: [
        { name: 'report_extract', ready: false, done: true, reason: 'already done' },
        { name: 'interactions', ready: false, done: false, reason: 'confirm the medicine list first' },
        { name: 'report_start', ready: false, done: false, reason: '<missing>' },
        { name: 'report_build', ready: true, done: false, reason: '' },
      ],
    },
    'Agent',
  );
  assert.doesNotMatch(row, />Extract/);
  assert.match(row, /Start report/);
  assert.match(row, /confirm the medicine list first/);
  assert.match(row, /&lt;missing&gt;/);
  assert.match(row, /add at least one finding/);
  assert.match(row, /data-report-open="2" data-build="edit"[^>]*>Edit report/);
  assert.match(row, /data-medicines="2"[^>]*>Check medicines for interaction check/);
  assert.doesNotMatch(row, /Check medicines for interaction check &#10003; Done/);
  const confirmed = context.reportRow(
    { id: 2, name: 'Test', state: 'visited' },
    { steps: [{ name: 'interactions', ready: true, done: false, reason: '' }] },
    'Agent',
  );
  assert.match(confirmed, /data-medicines="2"[^>]*>Check medicines for interaction check &#10003; Done/);
});

test('interview snapshots and row edits detect unsaved changes without mutating originals', () => {
  const { recordChanged, addRow, removeRow } = require('../renderer/helpers');
  const rows = [['medicine', 'daily']];
  const saved = JSON.stringify({ meds: rows });
  assert.equal(recordChanged({ meds: rows }, saved), false);
  const added = addRow(rows, 2);
  assert.deepEqual(added, [
    ['medicine', 'daily'],
    ['', ''],
  ]);
  assert.equal(recordChanged({ meds: added }, saved), true);
  assert.deepEqual(removeRow(added, 0), [['', '']]);
  assert.deepEqual(rows, [['medicine', 'daily']]);
});

test('extracts generic medicine names, compares settings, and validates consent', () => {
  const { genericName, settingsDiff, consentValidation } = require('../renderer/helpers');
  assert.equal(genericName('amoxicillin clavulanate 875 mg/125 mg'), 'amoxicillin clavulanate');
  assert.equal(genericName('paracetamol 500mg'), 'paracetamol');
  assert.equal(genericName('123 mg'), '');
  assert.deepEqual(
    settingsDiff(
      [
        { key: 'a', value: false },
        { key: 'b', value: 2 },
      ],
      { a: true, b: 2 },
    ),
    { a: true },
  );
  assert.equal(consentValidation({ by: 'patient' }), '');
  assert.match(consentValidation({ by: 'authorised', relationship: 0 }), /relationship/);
  assert.match(consentValidation({ by: 'authorised', relationship: 1, authorised_name: ' ' }), /name/);
  assert.equal(consentValidation({ by: 'authorised', relationship: 5, authorised_name: 'Example' }), '');
});

test('patient quick actions follow stage and declined folder', () => {
  const H = require('../renderer/helpers');
  assert.deepEqual(H.stageActions({ stage: 'hold' }), ['resume']);
  assert.ok(!H.stageActions({ stage: 'declined', folder: 'Declined-Exp 2026' }).includes('move_declined'));
  assert.ok(H.stageActions({ stage: 'declined', folder: 'Other' }).includes('move_declined'));
});

test('consent signing hides for signed records and posts a drawn PNG', async () => {
  const vm = require('node:vm');
  const fs = require('node:fs');
  const H = require('../renderer/helpers');
  const calls = [];
  const handlers = {};
  const context2d = { scale() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, clearRect() {} };
  const canvas = {
    getContext: () => context2d,
    getBoundingClientRect: () => ({ width: 600, height: 200, left: 0, top: 0 }),
    addEventListener: (name, fn) => { handlers[name] = fn; },
    setPointerCapture() {}, hasPointerCapture: () => true,
    toDataURL: () => 'data:image/png;base64,c2lnbmF0dXJl',
  };
  const save = { disabled: true }, clear = {}, cancel = {}, error = {}, image = {}, title = {};
  const nodes = { canvas, '[data-save]': save, '[data-clear]': clear, '[data-cancel]': cancel,
    '[data-touchpad]': {}, '.consent-pen': { style: {} }, '.consent-hint': {},
    '.error': error, img: image, h2: title, '.consent-preview p': { remove() {} } };
  const dialog = { setAttribute() {}, addEventListener() {}, showModal() { this.open = true; },
    close() { this.open = false; }, querySelector: (s) => nodes[s] };
  const screen = { innerHTML: '' };
  const document = { addEventListener() {}, createElement: () => dialog, body: { appendChild() {} }, querySelectorAll: () => [] };
  const context = vm.createContext({ document, window: { devicePixelRatio: 2 }, H, esc: H.esc,
    $: (id) => id === 'screen' ? screen : null, page: 'interview', patients: [{ id: 1, name: 'Patient' }],
    errorText: (e) => e.message, hmr: { api: async (...args) => {
      calls.push(args);
      if (args[1].endsWith('/preview')) return { png: 'Zm9ybQ==', by: 'patient' };
      if (args[1].endsWith('/sign')) return { file: 'signed.pdf' };
      if (args[0] === 'GET') return { consent: { signed: true }, consent_file: 'signed.pdf' };
      return {};
    } } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/followup-context.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext("interviewId = '1'; interviewRecord = { consent: { by: 'patient' }, consent_file: '' }; renderInterview()", context);
  assert.match(screen.innerHTML, /Sign consent form/);
  await context.openConsentDialog();
  assert.equal(save.disabled, true);
  handlers.pointerdown({ pointerId: 1, clientX: 20, clientY: 20 });
  assert.equal(save.disabled, false);
  await save.onclick();
  assert.equal(calls.find((c) => c[1].endsWith('/sign'))[2].png, 'c2lnbmF0dXJl');
  assert.match(screen.innerHTML, /Signed: signed\.pdf/);
  assert.match(screen.innerHTML, /View signed consent/);
  assert.doesNotMatch(screen.innerHTML, /Sign consent form/);
  assert.match(screen.innerHTML, /data-prop="signed" checked/);
});

test('touchpad signing draws separate strokes after a pause and exits on Escape', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const events = {}, lines = [], timers = new Map();
  let timerId = 0;
  const ctx = { scale() {}, beginPath() { lines.push('begin'); }, moveTo(x, y) { lines.push(['move', x, y]); },
    lineTo(x, y) { lines.push(['line', x, y]); }, stroke() {}, clearRect() {} };
  const canvas = { getContext: () => ctx, getBoundingClientRect: () => ({ width: 600, height: 200 }), addEventListener() {},
    requestPointerLock() { document.pointerLockElement = canvas; events.pointerlockchange(); } };
  const save = {}, touchpad = {}, error = {}, marker = { style: {} };
  const nodes = { canvas, '[data-save]': save, '[data-clear]': {}, '[data-cancel]': {}, '[data-touchpad]': touchpad,
    '.consent-pen': marker, '.consent-hint': {}, '.error': error, h2: {}, img: {}, '.consent-preview p': { remove() {} } };
  const dialog = { setAttribute() {}, addEventListener() {}, showModal() { this.open = true; }, querySelector: (s) => nodes[s] };
  const document = { addEventListener(name, fn) { events[name] = fn; }, removeEventListener() {},
    exitPointerLock() { this.pointerLockElement = null; events.pointerlockchange(); },
    createElement: () => dialog, body: { appendChild() {} } };
  const context = vm.createContext({ document, window: {}, H, esc: H.esc, $: () => null, errorText: (e) => e.message,
    setTimeout(fn, ms) { assert.equal(ms, 700); timers.set(++timerId, fn); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    hmr: { api: async () => ({ png: 'image' }) } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/followup-context.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext("interviewId = '1'; interviewRecord = { consent: { by: 'patient' } }", context);
  await context.openConsentDialog();
  await touchpad.onclick({ stopPropagation() {} });
  events.mousemove({ movementX: 10, movementY: 2 });
  assert.equal(save.disabled, false);
  assert.deepEqual(lines, ['begin', ['move', 0, 100], ['line', 15, 103]]);
  [...timers.values()][0]();
  events.mousemove({ movementX: 4, movementY: 0 });
  assert.deepEqual(lines.slice(3), ['begin', ['move', 15, 103], ['line', 21, 103]]);
  events.keydown({ key: 'Escape', preventDefault() {} });
  assert.equal(document.pointerLockElement, null);
  assert.equal(marker.hidden, true);
  delete canvas.requestPointerLock;
  await touchpad.onclick({ stopPropagation() {} });
  assert.equal(error.textContent, 'Touchpad mode is not available here');
});

test('bulk step selection posts in flow order and shows skipped reasons', async () => {
  const vm = require('node:vm');
  const fs = require('node:fs');
  const H = require('../renderer/helpers');
  const nodes = { 'queue-message': { textContent: '' } };
  const calls = [];
  const context = vm.createContext({ H, esc: H.esc, patients: [{ id: 7, name: 'Jane' }], page: 'patients',
    $: (id) => nodes[id], document: { querySelector: () => null, querySelectorAll: () => [] },
    hmr: { api: async (...args) => { calls.push(args); return { enqueued: [1], skipped: [
      { patient_id: 7, step: 'report_build', reason: 'Not ready' },
    ] }; } }, errorText: (e) => e.message });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/run.js'), 'utf8'), context);
  vm.runInContext("runStepsCatalog = [{ name: 'pathology', label: 'Collect pathology' }, { name: 'report_build', label: 'Build report' }]", context);
  assert.match(context.stepCheckboxes(H.bulkSteps), /data-run-step="pathology"/);
  assert.equal(context.selectedSteps(H.bulkSteps).length, 0);
  vm.runInContext("checkedPatients.add(7); tickedSteps.add('report_build'); tickedSteps.add('pathology')", context);
  await context.runClick({ dataset: { bulkStep: '' } });
  assert.deepEqual(Array.from(calls[0][2].steps), ['pathology', 'report_build']);
  assert.match(nodes['queue-message'].textContent, /1 task\(s\) queued/);
  assert.match(nodes['queue-message'].textContent, /Jane.*Build report: Not ready/);
  const button = { disabled: false };
  context.document.querySelector = () => button;
  vm.runInContext('tickedSteps.clear()', context);
  context.updateStepButton();
  assert.equal(button.disabled, true);
});

test('message board displays sections, test mode and sends edited drafts', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const nodes = { screen: { innerHTML: '' }, 'board-body-8': { value: 'Edited text' }, 'board-error-8': { textContent: '' } };
  const calls = [];
  const context = vm.createContext({ esc: H.esc, date: H.date, page: 'messages', formOpen: false,
    $: (id) => nodes[id], document: { addEventListener() {} },
    hmr: { api: async (...args) => { calls.push(args); return args[0] === 'GET' ? {
      outbox_mode: 'test', needs_you: [{ id: 8, patient_id: 2, name: 'Jane', state: 'draft', body: 'Original' }],
      waiting: [], upcoming: [], recent: [] } : {}; } } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/messages.js'), 'utf8'), context);
  await context.messagesBoard();
  for (const text of ['Test mode - only the test phone receives messages', 'Needs you', 'Waiting for reply', 'Upcoming visits', 'Recent', 'Jane']) assert.ok(nodes.screen.innerHTML.includes(text));
  await context.messageClick({ dataset: { messageSend: '8' } });
  assert.equal(calls[1][1], '/api/messages/8/approve');
  assert.equal(calls[1][2].body, 'Edited text');
  calls.length = 0;
  await context.messageClick({ dataset: { checkMessages: '' }, textContent: '' });
  assert.deepEqual(calls.map((c) => c[0] + ' ' + c[1]), ['POST /api/messages/check', 'GET /api/messages/board']);
  assert.match(nodes.screen.innerHTML, /data-check-messages[\s\S]*No new replies &middot; checked/);
});

test('custom message requires text and displays engine errors', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const nodes = { 'message-kind': { value: 'custom' }, 'message-body': { value: ' ' }, 'message-error': { textContent: '' } };
  let calls = 0;
  const context = vm.createContext({ esc: H.esc, date: H.date, selected: '1', $: (id) => nodes[id],
    document: { addEventListener() {} }, hmr: { api: async () => { calls++; throw Error('Test number only'); } } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/messages.js'), 'utf8'), context);
  await context.messageClick({ dataset: { messagePrepare: '' } });
  assert.match(nodes['message-error'].textContent, /Enter a message/);
  assert.equal(calls, 0);
  nodes['message-body'].value = 'Hello';
  await context.messageClick({ dataset: { messagePrepare: '' } });
  assert.equal(nodes['message-error'].textContent, 'Test number only');
});

test('timeline shows empty and overdue milestones and gates follow-up claims', () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const context = vm.createContext({ H, esc: H.esc, date: H.date });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  const html = context.timelineStrip({ referral_date: '2026-01-01', followup1_due: '2026-02-01' }, '2026-03-01');
  assert.match(html, /milestone empty[^>]*><strong>First contact/);
  assert.match(html, /milestone overdue[^>]*><strong>Follow-up 1 due/);
  assert.ok(context.availableActions({stage: 'followup'}, {followup1_done: '2026-01-01'}).includes('followup1_claimed'));
  assert.ok(!context.availableActions({stage: 'followup'}, {followup1_done: '2026-01-01', followup1_claimed: '2026-01-02'}).includes('followup1_claimed'));
});

test('call action posts the selected outcome and note', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  let submit, posted;
  const nodes = { 'action-area': {}, 'action-form': { addEventListener: (_, fn) => { submit = fn; } } };
  const context = vm.createContext({ esc: H.esc, $: id => nodes[id], actionLabels: {call: 'Called'}, actionFields: {call: ['outcome', 'note']}, selected: '4', localDate: () => '', FormData: class { *[Symbol.iterator]() { yield ['outcome', 'left_message']; yield ['note', 'Try again']; } }, hmr: {api: async (...args) => { posted = args; }}, refresh: async () => {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  context.openForm('call', { id: 4 });
  assert.match(nodes['action-area'].innerHTML, /<select name="outcome"/);
  await submit({preventDefault() {}, target: {}});
  assert.equal(JSON.stringify(posted), JSON.stringify(['POST', '/api/patients/4/action', {action: 'call', outcome: 'left_message', note: 'Try again'}]));
});

test('follow-up form saves the edited record and recommendation shape', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const handlers = {}, calls = [], nodes = {screen: {}, 'followup-status': {}};
  const record = {date: '', method: 'phone', spoke_with: '', med_changes: '', recommendations: [['Take medicine', '', '']], issues: '', outcome: '', notes: ''};
  const context = vm.createContext({ H, esc: H.esc, $: id => nodes[id], document: {addEventListener: (name, fn) => { handlers[name] = fn; }}, page: 'followup_editor', hmr: {api: async (...args) => { calls.push(args); if (args[0] === 'GET') return record; }}, errorText: String, setTimeout, clearTimeout, confirm: () => false });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/followup-context.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext("followupId = '4'; followupNumber = '1'", context);
  await context.followupScreen();
  handlers.input({target: {dataset: {followupField: 'date'}, value: '2026-11-12'}});
  handlers.input({target: {dataset: {followupRow: '0', col: '1'}, value: 'partly'}});
  handlers.input({target: {dataset: {followupRow: '0', col: '2'}, value: 'Discussed'}});
  await context.followupClick({dataset: {followupSave: ''}});
  const saved = calls.find(c => c[0] === 'POST');
  assert.equal(saved[1], '/api/patients/4/followup/1');
  assert.equal(JSON.stringify(saved[2]), JSON.stringify({...record, date: '2026-11-12', recommendations: [['Take medicine', 'partly', 'Discussed']]}));
});

test('report editor displays and copies Brainstorm V2 passages safely', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const copied = [];
  const context = vm.createContext({ H, esc: H.esc, document: { addEventListener() {} }, page: 'report_editor',
    navigator: { clipboard: { writeText: async (text) => copied.push(text) } }, errorText: String });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  vm.runInContext(`reportRecord = { issues: [] }; reportSuggestions = [
    { title: 'Suggestion', brainstorm: { title: '<Title>', page: '3&4', snippet: '<prompt> & text' } },
    { title: 'Other', brainstorm: null }
  ]; reportQuery = 'test'; reportResults = [
    { source: 'Brainstorm V2 p.7', title: '<Library>', snippet: '<reference> & text' },
    { source: 'library', title: 'Finding', rec: 'Recommendation' }
  ];`, context);
  const suggestions = context.suggestionsHtml();
  assert.match(suggestions, /<details><summary>Brainstorm V2 - &lt;Title&gt; \(p\.3&amp;4\)<\/summary><p>&lt;prompt&gt; &amp; text<\/p><button data-suggestion-copy="0">Copy<\/button><\/details>/);
  assert.equal((suggestions.match(/<details>/g) || []).length, 1);
  const library = context.libraryResultsHtml();
  assert.match(library, /Brainstorm V2 p\.7<\/span><h3>&lt;Library&gt;<\/h3><p class="library-excerpt">&lt;reference&gt; &amp; text<\/p><button data-library-copy="0">Copy/);
  assert.doesNotMatch(library.split('</article>')[0], /data-library-insert|Add to findings/);
  assert.match(library, /Recommendation<\/p><button data-library-insert="1">Insert/);
  await context.reportEditorClick({ dataset: { suggestionCopy: '0' } });
  await context.reportEditorClick({ dataset: { libraryCopy: '0' } });
  assert.deepEqual(copied, ['<prompt> & text', '<reference> & text']);
});

test('booking filter shows intake and booking stages', () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const nodes = { search: { value: '' }, chips: {}, bulk: {}, detail: {}, 'patient-list': { parentElement: { classList: { toggle() {} } } } };
  const context = vm.createContext({ H, esc: H.esc, group: H.group, date: H.date, $: id => nodes[id],
    patients: [{ id: 1, name: 'Booking', stage: 'booking' }, { id: 2, name: 'Ready', stage: 'ready' }],
    page: 'patients', filter: 'Booking', selected: '', selectedSteps: () => [], stepCheckboxes: () => '', stopColour: () => '' });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  context.renderPatients();
  assert.match(nodes.chips.innerHTML, /Booking \(1\)/);
  assert.match(nodes['patient-list'].innerHTML, /Booking/);
  assert.doesNotMatch(nodes['patient-list'].innerHTML, /Ready/);
});

test('appointment SMS preview, send, discard and errors', async () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const calls = [], handlers = {}, nodes = { detail: { querySelector: () => ({ addEventListener() {} }) }, 'offer-date': { value: '2027-02-03' }, 'offer-time': { value: '14:30' }, 'offer-error': {} };
  for (const id of ['offer-form', 'offer-send', 'offer-discard']) nodes[id] = { addEventListener: (event, fn) => { handlers[id] = fn; } };
  let fail = false, refreshes = 0, changeKinds = ['change_request', 'change'];
  const context = vm.createContext({ H, esc: H.esc, group: H.group, date: H.date, $: id => nodes[id], selected: '',
    detailTab: 'Timeline', formOpen: false, renderPatients() {}, messageComposer: () => '', stopColour: () => '',
    actionLabels: {}, localDate: () => '2026-01-01', errorText: e => e.message,
    refresh: async () => { refreshes++; await context.showPatient('1'); },
    hmr: { api: async (...args) => { calls.push(args); if (fail && args[0] === 'POST') throw new Error('Outbox test mode');
      if (args[1].endsWith('/timeline')) return {};
      if (args[0] === 'GET') return { id: 1, name: 'Test', state: 'offered', suggested_kind: 'change', change_kinds: changeKinds };
      if (args[1].endsWith('/messages')) return { id: 42, body: '<Hello>\nNext line' };
      return {}; } } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/patients.js'), 'utf8'), context);
  context.renderPatients = () => {};
  await context.showPatient('1');
  assert.match(nodes.detail.innerHTML, /Change the time/);
  assert.match(nodes.detail.innerHTML, /value="change_request"[^>]*>Ask to change/);
  assert.match(nodes.detail.innerHTML, /value="change"[^>]*>Have to change/);
  await handlers['offer-form']({ preventDefault() {}, submitter: { value: 'change_request' } });
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c => c[1].endsWith('/messages'))[2])), { kind: 'change_request', date: '2027-02-03', time: '14:30' });
  assert.match(nodes.detail.innerHTML, /<strong>Ask to change<\/strong>/);
  assert.match(nodes.detail.innerHTML, /&lt;Hello&gt;\nNext line/);
  await handlers['offer-send']();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c => c[1] === '/api/messages/42/approve')[2])), {});
  assert.equal(refreshes, 1); assert.match(nodes.detail.innerHTML, /Sent/);
  await handlers['offer-form']({ preventDefault() {}, submitter: { value: 'change' } });
  assert.equal(calls.filter(c => c[1].endsWith('/messages')).at(-1)[2].kind, 'change');
  assert.match(nodes.detail.innerHTML, /<strong>Have to change<\/strong>/);
  await handlers['offer-discard']();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c => c[1] === '/api/messages/42/discard')[2])), {});
  changeKinds = [];
  await context.showPatient('1');
  const form = nodes.detail.innerHTML.match(/<form id="offer-form">[\s\S]*?<\/form>/)[0];
  assert.match(nodes.detail.innerHTML, /Offer a new time/);
  assert.equal((form.match(/<button/g) || []).length, 1);
  assert.match(form, /value="offer"[^>]*>Preview SMS/);
  await handlers['offer-form']({ preventDefault() {}, submitter: { value: 'offer' } });
  assert.equal(calls.filter(c => c[1].endsWith('/messages')).at(-1)[2].kind, 'offer');
  fail = true;
  await handlers['offer-form']({ preventDefault() {}, submitter: { value: 'offer' } });
  assert.equal(nodes['offer-error'].textContent, 'Outbox test mode');
});

test('patient name and GP cells do not break words', () => {
  const css = require('node:fs').readFileSync(require.resolve('../style.css'), 'utf8');
  assert.match(css, /#patient-list \.patient-name, #patient-list \.patient-gp \{[^}]*min-width:[^;]+;[^}]*overflow-wrap: normal;[^}]*word-break: normal;/);
});


test('report placeholder errors name fields and focus the first field', () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  let message, focused;
  const letter = { open: false };
  const context = vm.createContext({ H, esc: H.esc, $: () => letter, alert: text => { message = text; },
    document: { addEventListener() {}, querySelector: selector => ({ focus: () => { focused = selector; } }) } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  context.showBuildError('Review placeholder fields: reason, intro');
  assert.equal(message, 'Review placeholder fields: Reason for referral, Introduction');
  assert.equal(letter.open, true);
  assert.equal(focused, '[data-field="reason"]');
});

test('report medicine notes use textareas and suggestions show specific gaps', () => {
  const vm = require('node:vm'), fs = require('node:fs'), H = require('../renderer/helpers');
  const table = H.tableInput('meds', 'meds', ['Medicine', 'Directions', 'Comment', 'Action'], [['A', 'B', 'long note', '']], 'report');
  assert.match(table, /<textarea data-field="meds" data-row="0" data-col="2"[^>]*>long note<\/textarea>/);
  assert.match(table, /<textarea data-field="meds" data-row="0" data-col="3"/);
  const context = vm.createContext({ H, esc: H.esc, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  vm.runInContext("reportGaps = ['Interview notes missing', 'Medicines not confirmed']", context);
  assert.match(context.suggestionsHtml(), /<li>Interview notes missing<\/li><li>Medicines not confirmed<\/li>/);
});
