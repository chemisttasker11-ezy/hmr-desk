'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');
const lookup = read('renderer', 'medicine-lookup.js');

test('lookup script loads before the interview and the row template calls it', () => {
  const html = read('index.html');
  assert.ok(html.indexOf('renderer/medicine-lookup.js') > 0 && html.indexOf('renderer/medicine-lookup.js') < html.indexOf('renderer/interview.js'));
  assert.match(read('renderer', 'interview.js'), /interviewLookupControls\(key, meta, i\)/);
});

test('results are built with textContent, never inserted as HTML', () => {
  const body = lookup.slice(lookup.indexOf('async function medicineLookupClick'));
  assert.doesNotMatch(body, /innerHTML/);
  assert.match(body, /textContent/);
});

test('the pharmacist chooses; no automatic link and free text stays valid', () => {
  assert.match(lookup, /Use this/);
  assert.match(lookup, /Keep typing the name by hand/);
  assert.doesNotMatch(lookup, /results\[0\]\)\s*;?\s*interviewRecord/);
});

test('rendered link escapes values from the reference file', () => {
  const ctx = { H: { esc: (v) => String(v).replace(/</g, '&lt;') } };
  const fn = new Function('H', lookup.slice(0, lookup.indexOf('async function medicineLookupClick')) + '; return interviewLookupControls;')(ctx.H);
  const html = fn('meds', { reference: { source: 'amt', code: '1', display: '<img src=x>', release: '20260101' } }, 0);
  assert.ok(!html.includes('<img'));
  assert.match(html, /Linked: &lt;img src=x>/);
  assert.doesNotMatch(fn('meds', {}, 0), /Linked/);
});

test('editing a medicine name unlinks a stale identity without changing use status or directions', () => {
  const vm = require('node:vm'); const notes = []; let removed = false;
  const results = {replaceChildren() {}, append: n => notes.push(n.textContent)};
  const block = {querySelector: s => s === '.med-ref' ? {remove: () => {removed = true;}} : results};
  const context = vm.createContext({H: {}, document: {addEventListener() {}, createElement: () => ({})},
    interviewRecord: {meds: [['Typed medicine', 'Referral dose', 'Interview dose']], details: {meds: [{reference: {code: '1'}, use_status: 'not_using'}]}}});
  vm.runInContext(lookup, context);
  context.medicineNameEdited('meds', 0, {closest: () => ({querySelector: () => block})});
  assert.equal(context.interviewRecord.details.meds[0].reference, undefined);
  assert.equal(context.interviewRecord.details.meds[0].use_status, 'not_using');
  assert.equal(context.interviewRecord.meds[0][1], 'Referral dose');
  assert(removed); assert.match(notes[0], /Previous reference unlinked/);
});

test('a late lookup cannot attach results to another patient, row or changed medicine', async () => {
  const vm = require('node:vm');
  const record = {meds: [['Old name']], details: {meds: [{}]}};
  let resolve; const appended = []; const out = {isConnected: true, replaceChildren() {}, append: x => appended.push(x)};
  const context = vm.createContext({H: {}, interviewId: '1', interviewRecord: record, page: 'interview',
    hmr: {api: () => new Promise(r => {resolve = r;})},
    document: {addEventListener() {}, querySelector: s => s.startsWith('textarea') ? {value: 'Old name'} : out,
      createElement: () => ({append() {}, addEventListener() {}})}, errorText: String});
  vm.runInContext(lookup, context);
  const pending = context.medicineLookupClick({dataset: {medLookup: 'meds', row: '0'}});
  record.meds[0][0] = 'Changed name';
  resolve({installed: true, results: [{source: 'amt', code: '1', display: 'Old match', release: '20260101'}]});
  await pending; assert.equal(appended.length, 0); assert.equal(record.details.meds[0].reference, undefined);
});
