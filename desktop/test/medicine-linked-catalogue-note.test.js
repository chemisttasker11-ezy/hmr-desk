const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const H = require('../renderer/helpers.js');

const linked = { values: ['Brandex | Tablet 20 mg | oral'], metadata: { reference: { source: 'pbs', code: 'X', display: 'Brandex | Tablet 20 mg | oral', release: 'SYN' } } };
const free = { values: ['aspirin'], metadata: {} };

test('a catalogue-linked medicine gets the caution, free text does not, and the value is never rewritten', () => {
  assert.match(H.linkedCatalogueNote('Brandex | Tablet 20 mg | oral', [linked, free]), /not a generic name/);
  assert.equal(H.linkedCatalogueNote('aspirin', [linked, free]), '');
  assert.equal(H.linkedCatalogueNote('', [linked]), '');
  assert.equal(H.linkedCatalogueNote('Brandex | Tablet 20 mg | oral', undefined), '');
});

test('medicines panel shows the caution beside the linked row only and keeps the typed value', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/reports.js'), 'utf8');
  const context = { H, esc: H.esc, document: { addEventListener() {} }, medicineData: null, window: {}, hmr: {} };
  vm.createContext(context);
  vm.runInContext(source + '\nthis.renderMedicines = renderMedicines;', context);
  const html = [];
  context.$ = () => ({ set innerHTML(v) { html.push(v); }, get innerHTML() { return ''; }, querySelector() { return null; }, appendChild() {} });
  context.page = 'interview'; context.fixture = { meds: [['Brandex | Tablet 20 mg | oral', ''], ['aspirin', '']], allergies: [], interview_usage: [], medicine_snapshot: { items: [linked, free] } };
  vm.runInContext('medicinePatient = 1; medicineData = fixture;', context);
  try { context.renderMedicines(); } catch (e) { if (!html.length) throw e; }
  const out = html.join('');
  assert.equal((out.match(/not a generic name/g) || []).length, 1);
  assert.match(out, /name="generic" value="Brandex \| Tablet 20 mg \| oral"/);
});
