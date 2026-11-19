const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const helpers = require('../renderer/helpers');
const source = fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8');

function context(alerts, focused) {
  const c = vm.createContext({
    H: { ...helpers, autosaver: () => ({ changed() {}, adopt() {}, save: async () => true }) }, esc: helpers.esc, page: 'report_editor',
    hmr: { api: async () => ({}) }, $: () => ({ open: false }), errorText: (e) => e.message,
    alert: (m) => alerts.push(m), document: { addEventListener() {}, querySelector: (q) => ({ focus() { focused.push(q); } }) },
  });
  vm.runInContext(source, c);
  return c;
}

test('build refusal for unreviewed imported wording names the findings and focuses the first review box', () => {
  const alerts = [], focused = [], c = context(alerts, focused);
  c.showBuildError('Review imported template findings: 2, 3');
  assert.match(alerts[0], /finding 2, 3/);
  assert.deepEqual(focused, ['[data-template-reviewed="1"]']);
});

test('placeholder refusals keep their own message', () => {
  const alerts = [], c = context(alerts, []);
  c.showBuildError('Review placeholder fields: intro');
  assert.match(alerts[0], /Introduction/);
});

test('review is a separate deliberate tick, never an edit side effect, and the engine confirms it', () => {
  assert.match(source, /data-template-reviewed="\$\{i\}"/);
  assert.match(source, /not yet reviewed for this patient/);
  assert.match(source, /Editing the wording does not count as review/);
  // an edit clears the tick on the client; the engine also drops the review when wording changes
  assert.match(source, /issue\.template_reviewed = false;\s*showTemplateReviewState/);
  // the tick is cleared until the engine reports it recorded
  assert.match(source, /el\.checked = false; \/\/ becomes checked only when the engine confirms the review/);
  assert.match(source, /Review not recorded/);
});

test('an edit updates the explanatory line, the state marker and the checkbox together, without waiting for a re-render', () => {
  const nodes = {
    box: { checked: true },
    note: { textContent: 'Imported past-case wording reviewed for this patient.', closest: () => holder },
  };
  const holder = { dataset: { templateReviewState: 'reviewed' } };
  const alerts = [];
  const c = vm.createContext({
    H: { ...helpers, autosaver: () => ({ changed() {}, adopt() {}, save: async () => true }) }, esc: helpers.esc, page: 'report_editor',
    hmr: { api: async () => ({}) }, $: () => ({ open: false }), errorText: (e) => e.message, alert: (m) => alerts.push(m),
    document: { addEventListener() {}, querySelector: (q) => (q === '[data-template-reviewed="0"]' ? nodes.box : q === '[data-template-review-note="0"]' ? nodes.note : null) },
  });
  vm.runInContext(source, c);
  c.showTemplateReviewState(0, false);
  assert.equal(nodes.box.checked, false);
  assert.match(nodes.note.textContent, /not yet reviewed for this patient/);
  assert.equal(holder.dataset.templateReviewState, 'pending');
  c.showTemplateReviewState(0, true);
  assert.equal(nodes.box.checked, true);
  assert.equal(nodes.note.textContent, 'Imported past-case wording reviewed for this patient.');
  assert.equal(holder.dataset.templateReviewState, 'reviewed');
  assert.match(source, /data-template-review-note="\$\{i\}"/);
  assert.match(source, /showTemplateReviewState\(Number\(el\.dataset\.issue\), false\)/);
});
