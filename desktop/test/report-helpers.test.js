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
