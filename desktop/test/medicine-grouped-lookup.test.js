'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const lookup = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'medicine-lookup.js'), 'utf8');

function el(tag) {
  const n = {tag, children: [], listeners: {}, hidden: false, className: '', textContent: '', dataset: {},
    append(...c) { n.children.push(...c); }, replaceChildren() { n.children = []; },
    addEventListener(t, f) { n.listeners[t] = f; }, isConnected: true};
  return n;
}
const all = (n) => [n, ...n.children.flatMap(all)];
const text = (n) => all(n).map((x) => x.textContent).join(' ');
async function run(reply) {
  const record = {meds: [['Brandex']], details: {meds: [{}]}};
  const out = el('div'); const requested = [];
  const ctx = vm.createContext({H: {}, interviewId: '1', interviewRecord: record, page: 'interview', errorText: String,
    interviewChanged() {}, renderInterview() {},
    hmr: {api: async (m, u) => { requested.push(u); return reply; }},
    document: {addEventListener() {}, querySelector: (s) => s.startsWith('textarea') ? {value: 'Brandex'} : out, createElement: el}});
  vm.runInContext(lookup, ctx);
  await ctx.medicineLookupClick({dataset: {medLookup: 'meds', row: '0'}});
  return {record, out, requested};
}
const L = (code, program = 'GE') => ({source: 'pbs', code: `${program}:${code}:9`, display: `Brandex | 20 mg tablet, 30 | ${code}`, kind: 'pbs_listing', release: '20260101', program_code: program, pbs_code: code});
const ref = (record) => JSON.parse(JSON.stringify(record.details.meds[0].reference));

test('identical PBS entries show as one line with no PBS code, listing label or listing choice', async () => {
  const listings = [L('1001A'), L('1002B'), L('1003C', 'S100')];
  const {record, out, requested} = await run({installed: true, results: listings, groups: [{grouped: true, label: 'Brandex | 20 mg tablet, 30', listings, count: 3}]});
  assert.match(requested[0], /grouped=1/);
  const rows = out.children.filter((c) => c.className === 'med-lookup-result');
  assert.equal(rows.length, 1);
  const shown = text(out);
  assert.doesNotMatch(shown, /1001A|1002B|1003C|pbs_listing|PBS listing|Show listings|program/);
  assert.match(shown, /Brandex \| 20 mg tablet, 30 \(3 matching entries combined\)/);
  assert.equal(all(out).filter((n) => n.textContent === 'Use this').length, 1);
  all(out).find((n) => n.textContent === 'Use this').listeners.click();
  // The stored reference is one real catalogue listing (first by code) with the code-free label as display.
  assert.deepEqual(ref(record), {source: 'pbs', code: 'GE:1001A:9', display: 'Brandex | 20 mg tablet, 30', release: '20260101'});
  assert.equal(record.meds[0][0], 'Brandex | 20 mg tablet, 30');
});

test('a single PBS-keyed entry and a legacy single row are code-free and still one click', async () => {
  const a = L('2001D');
  const one = await run({installed: true, results: [a], groups: [{grouped: true, label: 'Brandex | 20 mg tablet, 30', listings: [a], count: 1}]});
  assert.doesNotMatch(text(one.out), /2001D|pbs_listing/);
  assert.doesNotMatch(text(one.out), /combined/);
  const amt = {source: 'amt', code: '77', display: 'Examplestatin 20 mg tablet', kind: 'MPUU', release: '20260101'};
  const legacy = await run({installed: true, results: [amt]});
  assert.doesNotMatch(text(legacy.out), /MPUU|\[/);
  all(legacy.out).find((n) => n.textContent === 'Use this').listeners.click();
  assert.deepEqual(ref(legacy.record), {source: 'amt', code: '77', display: 'Examplestatin 20 mg tablet', release: '20260101'});
});

test('uncertain entries stay as separate lines, not collapsed', async () => {
  const a = L('1'), b = L('2');
  const g = [{grouped: false, label: 'Brandex | 20 mg tablet, 30 (source details incomplete, entry kept separate)', listings: [a], count: 1},
             {grouped: false, label: 'Brandex | 20 mg tablet, 30 (source details incomplete, entry kept separate)', listings: [b], count: 1}];
  const {out} = await run({installed: true, results: [a, b], groups: g});
  assert.equal(all(out).filter((n) => n.textContent === 'Use this').length, 2);
  assert.match(text(out), /source details incomplete/);
});

test('a truncated search tells the pharmacist to narrow it, and nothing is linked automatically', async () => {
  const a = L('1'); const {record, out} = await run({installed: true, results: [a], groups: [{grouped: true, label: 'x', listings: [a], count: 1}], more_available: true});
  assert.ok(all(out).some((n) => /More matches exist/.test(n.textContent)));
  assert.equal(record.details.meds[0].reference, undefined);
});

test('suggestion panel shows one code-free line per medicine and stores the chosen representative', () => {
  const cand = (code) => ({source: 'pbs', code, display: `Brandex | 20 mg tablet, 30 | ${code.split(':')[1]}`, kind: 'pbs_listing', generic_name: 'Examplestatin', brand_name: 'Brandex', dose_form: null, release: '20260101'});
  const proposal = {state: 'ambiguous', input_text: 'Brandex', truncated: false, candidates: [cand('GE:1:9'), cand('GE:2:9'), cand('GE:3:9')],
    groups: [{label: 'Brandex | 20 mg tablet, 30', grouped: true, indexes: [0, 1, 2]}]};
  const record = {meds: [['Brandex']], details: {meds: [{}]}};
  const ctx = vm.createContext({H: {esc: (v) => String(v)}, interviewRecord: record, interviewChanged() {}, renderInterview() {}, document: {addEventListener() {}}});
  vm.runInContext(lookup, ctx);
  vm.runInContext('medicineSuggestions', ctx).set(record.details.meds[0], proposal);
  const html = ctx.interviewLookupControls('meds', record.details.meds[0], 0);
  assert.doesNotMatch(html, /pbs_listing|GE:1|\| 1<|\| 2<|\| 3</);
  assert.equal((html.match(/data-med-suggestion/g) || []).length, 1);
  assert.match(html, /3 matching entries combined/);
  ctx.medicineLookupClick({dataset: {medSuggestion: 'meds', row: '0', candidate: '0'}});
  // Deliberate change: the stored reference now also carries the catalogue's own generic/brand when every listing in the group agrees.
  assert.deepEqual(ref(record), {source: 'pbs', code: 'GE:1:9', display: 'Brandex | 20 mg tablet, 30', release: '20260101', generic_name: 'Examplestatin', brand_name: 'Brandex'});
});
