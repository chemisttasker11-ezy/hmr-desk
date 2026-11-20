const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

function render(scope) {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/reports.js'), 'utf8');
  const context = { H, esc: H.esc, document: { addEventListener() {} }, medicineData: null, window: {}, hmr: {} };
  vm.createContext(context);
  vm.runInContext(source + '\nthis.renderMedicines = renderMedicines;', context);
  const html = [];
  context.$ = () => ({ set innerHTML(v) { html.push(v); }, get innerHTML() { return ''; }, querySelector() { return null; }, appendChild() {} });
  context.page = 'interview';
  context.fixture = { meds: [['aspirin', '']], allergies: [], interview_usage: [], medicine_snapshot: { items: [] }, interaction_scope: scope };
  vm.runInContext('medicinePatient = 1; medicineData = fixture;', context);
  try { context.renderMedicines(); } catch (e) { if (!html.length) throw e; }
  return html.join('');
}

test('the medicines panel shows the interaction scope statement, escaped', () => {
  const out = render({ statement: ['Interaction check: no interaction result is on file.', 'Not on the confirmed medicine list: <b>X</b>.'] });
  assert.match(out, /data-interaction-scope/);
  assert.match(out, /no interaction result is on file/);
  assert.match(out, /&lt;b&gt;X&lt;\/b&gt;/);
  assert.doesNotMatch(out, /<b>X<\/b>/);
});

test('no banner when there is nothing to disclose or the API gave no scope', () => {
  assert.doesNotMatch(render({ statement: [] }), /data-interaction-scope/);
  assert.doesNotMatch(render(undefined), /data-interaction-scope/);
});
