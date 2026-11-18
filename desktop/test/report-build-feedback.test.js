const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

function editor(jobResult) {
  const els = { 'report-build-status': { textContent: '' }, 'report-output': { textContent: '' } };
  const buttons = [{ disabled: false }, { disabled: false }];
  const seenDisabled = [];
  const ctx = vm.createContext({
    H: { ...H, autosaver: () => ({ save: async () => true, leave: async () => true, dirty: () => false, changed() {} }) },
    page: 'report_editor', errorText: (e) => String(e), setTimeout: (fn) => fn(), alert: () => {},
    document: { addEventListener() {}, querySelector: () => null, querySelectorAll: () => buttons },
    $: (id) => els[id],
    hmr: { api: async (method, path) => { if (method === 'POST') { seenDisabled.push(buttons.map((b) => b.disabled)); return { id: 'abc' }; } return jobResult; } },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), ctx);
  vm.runInContext("reportId='1'; reportRecord={issues:[{}]}", ctx);
  return { ctx, els, buttons, seenDisabled };
}

test('a successful build shows what was built and re-enables the buttons', async () => {
  const { ctx, els, buttons, seenDisabled } = editor({ state: 'done', output: 'Built Synthetic-v2.docx' });
  await ctx.buildReport(true);
  assert.equal(els['report-build-status'].textContent, 'Word and PDF built: Built Synthetic-v2.docx. The files are in the patient folder.');
  assert.deepEqual(seenDisabled, [[true, true]]);
  assert.deepEqual(buttons.map((b) => b.disabled), [false, false]);
});

test('a failed build says it did not finish and keeps the reason on screen', async () => {
  const { ctx, els, buttons } = editor({ state: 'failed', output: 'Local PDF conversion failed; prior Word draft preserved. Reason: no PDF produced' });
  await ctx.buildReport(true);
  assert.equal(els['report-build-status'].textContent, 'Build did not finish: Local PDF conversion failed; prior Word draft preserved. Reason: no PDF produced');
  assert.deepEqual(buttons.map((b) => b.disabled), [false, false]);
});
