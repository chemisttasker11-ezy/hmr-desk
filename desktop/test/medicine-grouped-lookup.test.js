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

test('one line per product with PBS listings hidden until opened, and an explicit listing is the one linked', async () => {
  const listings = [L('1001A'), L('1002B'), L('1003C', 'S100')];
  const {record, out, requested} = await run({installed: true, results: listings, groups: [{grouped: true, label: 'Brandex | 20 mg tablet, 30', listings, count: 3}]});
  assert.match(requested[0], /grouped=1/);
  const rows = out.children.filter((c) => c.className === 'med-lookup-result');
  assert.equal(rows.length, 1);
  assert.match(rows[0].children[0].textContent, /3 PBS listings/);
  const list = out.children.find((c) => c.className === 'med-lookup-listings');
  assert.equal(list.hidden, true);
  assert.equal(all(rows[0]).filter((n) => n.textContent === 'Use this').length, 0);  // no one-click pick on the group line
  rows[0].children[1].listeners.click(); assert.equal(list.hidden, false);
  const picks = all(list).filter((n) => n.textContent === 'Use this listing');
  assert.equal(picks.length, 3);
  picks[2].listeners.click();
  assert.deepEqual(JSON.parse(JSON.stringify(record.details.meds[0].reference)), {source: 'pbs', code: 'S100:1003C:9', display: listings[2].display, release: '20260101'});
  assert.equal(record.meds[0][0], listings[2].display);
});

test('single listings and uncertain rows keep the one-click line; old flat replies still work', async () => {
  const a = L('1'); const {out} = await run({installed: true, results: [a], groups: [{grouped: false, label: a.display, listings: [a], count: 1}]});
  assert.equal(all(out).filter((n) => n.textContent === 'Use this').length, 1);
  const flat = await run({installed: true, results: [a]});
  assert.equal(all(flat.out).filter((n) => n.textContent === 'Use this').length, 1);
});

test('a truncated search tells the pharmacist to narrow it, and nothing is linked automatically', async () => {
  const a = L('1'); const {record, out} = await run({installed: true, results: [a], groups: [{grouped: false, label: a.display, listings: [a], count: 1}], more_available: true});
  assert.ok(all(out).some((n) => /More matches exist/.test(n.textContent)));
  assert.equal(record.details.meds[0].reference, undefined);
});
