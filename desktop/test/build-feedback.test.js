const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('vm');
const H = require('../renderer/helpers.js');

function editor(saveResult) {
  const el = { textContent: '' };
  const calls = { save: 0, api: 0 };
  const saver = { save: async () => { calls.save++; return saveResult; }, leave: async () => true };
  const ctx = vm.createContext({
    H: { ...H, autosaver: () => saver }, page: 'report_editor', document: { addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; } },
    $: (id) => (id === 'report-build-status' ? el : null), errorText: (e) => String(e), alert() {},
    hmr: { api: async () => { calls.api++; return { id: 'job' }; } },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8'), ctx);
  vm.runInContext("reportId='1'; reportRecord={issues:[{title:'f'}]}; reportSaveStatus='Unsaved changes'", ctx);
  return { ctx, el, calls };
}

test('a failed save does not build and says why next to the build button', async () => {
  const { ctx, el, calls } = editor(false);
  await ctx.buildReport(true);
  assert.equal(calls.save, 1);
  assert.equal(calls.api, 0, 'no job may start after a failed save');
  assert.match(el.textContent, /Build not started/);
  assert.match(el.textContent, /Unsaved changes/);
  assert.match(el.textContent, /Nothing was built/);
  assert.equal(vm.runInContext('reportBuildRunning', ctx), false, 'a failed save must not leave the build flag set');
});

test('a second click during a running build says so and starts nothing', async () => {
  const { ctx, el, calls } = editor(true);
  vm.runInContext('reportBuildRunning = true', ctx);
  await ctx.buildReport(false);
  assert.equal(calls.save, 0);
  assert.equal(calls.api, 0);
  assert.match(el.textContent, /already running/);
  assert.equal(vm.runInContext('reportBuildRunning', ctx), true, 'the running build keeps its flag');
});
