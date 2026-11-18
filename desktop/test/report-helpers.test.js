const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers');
const fs = require('node:fs');
const vm = require('node:vm');
test('findings reorder and deletion undo preserve order', () => {
  const items = [{ title: 'a' }, { title: 'b' }, { title: 'c' }];
  assert.deepEqual(H.moveFinding(items, 1, -1), [items[1], items[0], items[2]]);
  assert.deepEqual(H.moveFinding(items, 0, -1), items);
  assert.deepEqual(H.undoFinding(H.removeRow(items, 1), { index: 1, item: items[1] }), items);
});
test('review flags and library insertion retain only intended fields', () => {
  assert.deepEqual(H.reviewed(['intro', 'dear'], 'intro'), ['dear']);
  assert.deepEqual(
    H.findingFromResult({ source: 'past', title: 'Title', rec: 'Action', rationale: 'Reason', context: 'extra' }),
    { title: 'Title', rec: 'Action', rationale: 'Reason' },
  );
});

test('interview header formats optional details without raw keys', () => {
  assert.deepEqual(
    H.interviewHeader({
      name: 'Example',
      age: 42,
      dob: '1984-02-03',
      visit: '2026-11-12 09:30:00',
      gp: 'Dr Example',
      address: 'Example St',
      phone: '123',
    }),
    ['Example, age 42 · DOB 03/02/1984 · Visit 12/11/2026 09:30 · GP Dr Example', 'Example St · 123'],
  );
  assert.deepEqual(H.interviewHeader({}), ['', '']);
});
test('helper cards label sources and show the first three lines', () => {
  assert.equal(H.sourceLabel('past case'), 'Past cases');
  assert.equal(H.sourceLabel('brainstorm'), 'Brainstorm');
  assert.equal(H.sourceLabel('library'), 'Library');
  assert.equal(H.firstLines('one\ntwo\nthree\nfour'), 'one\ntwo\nthree');
});

test('interview refresh appears only for stale unsent reports', () => {
  assert.equal(H.showInterviewRefresh({ interview_newer: true }, { state: 'visited' }), true);
  assert.equal(H.showInterviewRefresh({ interview_newer: false }, { state: 'visited' }), false);
  assert.equal(H.showInterviewRefresh({}, { state: 'visited' }), false);
  assert.equal(H.showInterviewRefresh({ interview_newer: true }, { state: 'sent' }), false);
  assert.equal(H.showInterviewRefresh({ interview_newer: true }, { visits: [{ report_sent: '2026-11-01' }] }), false);
});

test('report refresh does not post when saving pending edits fails', async () => {
  let posts = 0, saves = 0;
  const screen = { inert: false };
  const context = vm.createContext({ H: { autosaver: () => ({ save: async () => { saves++; return false; } }) },
    page: 'report_editor', confirm: () => true, $: () => screen,
    hmr: { api: async () => { posts++; } }, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  vm.runInContext("reportId = 'one'; reportRecord = {}", context);
  assert.equal(await context.reportEditorClick({ dataset: { reportRefresh: '' } }), true);
  assert.equal(saves, 1); assert.equal(posts, 0); assert.equal(screen.inert, false);
});

test('report refresh offers each edited-block conflict and replaces only the ones accepted', async () => {
  const calls = [], prompts = [];
  const screen = { inert: false };
  const conflicts = [{ key: 'doctor', label: 'GP details block', report: 'Typed GP', record: 'Dr Record' },
    { key: 'patient', label: 'patient details block', report: 'Typed patient', record: 'DOB: 01-Feb-1950' }];
  const context = vm.createContext({ H: { autosaver: () => ({ save: async () => true, reset() {} }), esc: (x) => x },
    page: 'report_editor', $: () => screen, errorText: String, alert() {},
    confirm: (text) => { prompts.push(text); return !/The patient details block/.test(text); },
    hmr: { api: async (method, url, body) => { calls.push([method, url, body]); return method === 'POST' && !body ? { demographic_conflicts: conflicts } : {}; } },
    document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  vm.runInContext("reportId = 'one'; reportRecord = {}; renderReport = () => {}; loadSuggestions = () => {}", context);
  await context.reportEditorClick({ dataset: { reportRefresh: '' } });
  assert.equal(prompts.length, 3);                               // initial confirm, then one per conflict
  assert.match(prompts[1], /GP details block[\s\S]*Typed GP[\s\S]*Dr Record/);
  const replace = calls.find((c) => c[2] && c[2].replace_demographics);
  assert.deepEqual(replace[2].replace_demographics, ['doctor']); // the declined block is not replaced
});

test('report editor shows each differing block with both texts and sends only the chosen action', async () => {
  const calls = [];
  const screen = { inert: false, innerHTML: '' };
  const mismatch = [{ key: 'doctor', label: 'GP details block', report: 'Typed <GP>', record: 'Dr Record', acknowledged: false },
    { key: 'patient', label: 'patient details block', report: 'Old patient', record: 'New patient', acknowledged: true }];
  const questions = [];
  const context = vm.createContext({ H: { autosaver: () => ({ save: async () => true, reset() {} }), esc: (x) => String(x).replace(/</g, '&lt;') },
    esc: (x) => String(x).replace(/</g, '&lt;'), page: 'report_editor', $: () => screen, errorText: String, alert() {},
    confirm: (q) => { questions.push(q); return true; },
    hmr: { api: async (method, url, body) => { calls.push([method, url, body]); return { issues: [], demographic_mismatches: [] }; } },
    document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), context);
  vm.runInContext("reportId = 'one'; renderReport = () => {}; reportRecord = { demographic_mismatches: " + JSON.stringify(mismatch) + " }", context);
  const html = context.demographicsHtml();
  assert.match(html, /GP details block differs from the patient record[\s\S]*Typed &lt;GP>[\s\S]*Dr Record/);
  assert.match(html, /data-demo-action="keep" data-demo-key="doctor"/);
  assert.match(html, /patient details block differs from the patient record \(kept as written\)/);
  assert.doesNotMatch(html, /data-demo-action="keep" data-demo-key="patient"/);   // already kept; only Use patient record remains
  await context.reportEditorClick({ dataset: { demoAction: 'keep', demoKey: 'doctor' } });
  assert.match(questions[0], /Keep the report's GP details block as written[\s\S]*differs from the patient record[\s\S]*asks again/);
  assert.equal(JSON.stringify(calls[0]), JSON.stringify(['POST', '/api/patients/one/report/demographics', { action: 'keep', keys: ['doctor'] }]));
  vm.runInContext("reportRecord = { demographic_mismatches: " + JSON.stringify(mismatch) + " }", context);
  await context.reportEditorClick({ dataset: { demoAction: 'replace', demoKey: 'doctor' } });
  assert.match(questions[1], /Replace the report's GP details block with the patient record's text/);
  assert.equal(calls[1][2].action, 'replace');
});
