const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

const at = (y, m, d, hh = 12, mm = 0) => new Date(y, m - 1, d, hh, mm);
const NOW = at(2026, 11, 20, 18, 59);

test('old, today, future, missing and malformed report dates', () => {
  assert.equal(H.reportDateReview('18/11/2026', NOW).state, 'old');
  assert.match(H.reportDateReview('18/11/2026', NOW).text, /Report date is 18\/11\/2026\. Today is 20\/11\/2026\. Keep it, or set it to today\./);
  assert.equal(H.reportDateReview('20/11/2026', NOW).state, 'ok');
  assert.equal(H.reportDateReview('20/11/2026', NOW).text, '');
  assert.equal(H.reportDateReview('21/11/2026', NOW).state, 'future');
  assert.equal(H.reportDateReview('', NOW).state, 'missing');
  assert.equal(H.reportDateReview(undefined, NOW).state, 'missing');
  assert.equal(H.reportDateReview(null, NOW).state, 'missing');
  for (const bad of ['31/02/2026', '2026-13-01', 'yesterday', '20112026', '20/11/26', '0/0/2026']) {
    assert.equal(H.reportDateReview(bad, NOW).state, 'malformed', bad);
  }
});

test('ISO and unpadded forms are read as the same day; the saved text is never rewritten', () => {
  assert.equal(H.reportDateReview('2026-11-20', NOW).state, 'ok');
  assert.equal(H.reportDateReview('2026-11-20T00:00:00', NOW).state, 'ok');
  assert.equal(H.reportDateReview('2/3/2026', NOW).shown, '02/03/2026');
  assert.equal(H.reportDateReview('2/3/2026', NOW).state, 'old');
});

test('today means the pharmacist local calendar day, not the UTC day', () => {
  // Local 00:30 on the 21st and 23:30 on the 20th: each is judged against its own local day.
  assert.equal(H.reportDateReview('21/11/2026', at(2026, 11, 21, 0, 30)).state, 'ok');
  assert.equal(H.reportDateReview('20/11/2026', at(2026, 11, 21, 0, 30)).state, 'old');
  assert.equal(H.reportDateReview('20/11/2026', at(2026, 11, 20, 23, 30)).state, 'ok');
  assert.equal(H.reportDateReview('21/11/2026', at(2026, 11, 20, 23, 30)).state, 'future');
});

test('the review never mutates its input and adds no field to the record', () => {
  const record = Object.freeze({ report_date: '18/11/2026' });
  H.reportDateReview(record.report_date, NOW);
  assert.deepEqual(Object.keys(record), ['report_date']);
  const src = fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8');
  const note = src.slice(src.indexOf('function reportDateNoteHtml'), src.indexOf('function followupDecisionHtml'));
  assert.doesNotMatch(note, /reportRecord\.[a-z_]+\s*=[^=]/, 'the advisory note must not write into the saved record');
});

function editor(record) {
  const context = vm.createContext({
    H, esc: H.esc, page: 'report_editor', reportRecord: record, renderCalls: 0, saved: [], changed: 0,
    reportSaver: null, renderReport() { context.renderCalls += 1; },
    document: { addEventListener() {}, querySelector() { return null; } }, window: {}, hmr: {},
  });
  context.reportSaver = { changed() { context.changed += 1; }, async save(flag) { context.saved.push([flag, context.reportRecord.report_date]); return true; } };
  const src = fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8');
  const noteFn = src.slice(src.indexOf('function reportDateNoteHtml'), src.indexOf('function followupDecisionHtml'));
  const start = src.indexOf('if (d.reportDateToday !== undefined) {');
  const end = src.indexOf('if (d.reportSave !== undefined)');
  assert.ok(start > 0 && end > start);
  vm.runInContext(noteFn + '\nasync function clickToday(){ const d = {reportDateToday: ""};\n' + src.slice(start, end) + '\n}', context);
  return context;
}

test('the Set to today button is explicit: it changes only report_date, then saves once', async () => {
  const record = { report_date: '18/11/2026', assess_date: '17/11/2026', issues: [{ title: 'x' }] };
  const ctx = editor(record);
  assert.match(ctx.reportDateNoteHtml(), /data-report-date-today/);
  assert.match(ctx.reportDateNoteHtml(), /data-report-date-review="old"/);
  await ctx.clickToday();
  const today = H.reportDateReview('', new Date()).today;
  assert.equal(ctx.reportRecord.report_date, today);
  assert.equal(ctx.reportRecord.assess_date, '17/11/2026');
  assert.deepEqual(ctx.reportRecord.issues, [{ title: 'x' }]);
  assert.equal(ctx.changed, 1);
  assert.deepEqual(ctx.saved, [[true, today]]);
  assert.equal(ctx.renderCalls, 1);
  assert.equal(ctx.reportDateNoteHtml(), '');
});

test('a current date shows no note and no button', () => {
  const ctx = editor({ report_date: H.reportDateReview('', new Date()).today });
  assert.equal(ctx.reportDateNoteHtml(), '');
});
