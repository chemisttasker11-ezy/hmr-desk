'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'medicine-lookup.js'), 'utf8');

function setup() {
  const listeners = {}, timers = [], clicked = [], focused = [];
  const lookupBtn = {dataset: {medLookup: 'meds', row: '0'}};
  const record = {meds: [['Metf']], details: {meds: [{}]}};
  const box = {value: 'Metf', tagName: 'TEXTAREA', dataset: {col: '0', row: '0', field: 'meds'}, isConnected: true};
  const ctx = vm.createContext({H: {}, interviewId: '1', interviewRecord: record, page: 'interview', errorText: String,
    interviewChanged() {}, renderInterview() {}, hmr: {api: async () => { clicked.push('api'); return {installed: true, results: [], groups: []}; }},
    setTimeout: (f, ms) => { timers.push({f, ms}); return timers.length; }, clearTimeout: (n) => { if (timers[n - 1]) timers[n - 1].dead = true; },
    document: {addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
      querySelector: (s) => s.startsWith('[data-med-lookup') ? lookupBtn : s.startsWith('textarea') ? box : {replaceChildren() {}, append() {}, isConnected: true}}});
  vm.runInContext(src, ctx);
  return {listeners, timers, box, clicked, ctx};
}

test('typing three or more letters schedules one lookup after a pause; fewer letters schedule none', async () => {
  const s = setup();
  s.box.value = 'Me'; s.listeners.input.forEach(f => f({target: s.box}));
  assert.equal(s.timers.length, 0);
  s.box.value = 'Met'; s.listeners.input.forEach(f => f({target: s.box}));
  s.box.value = 'Metf'; s.listeners.input.forEach(f => f({target: s.box}));
  const live = s.timers.filter(t => !t.dead);
  assert.equal(live.length, 1, 'earlier pending lookup is cancelled');
  assert.ok(live[0].ms >= 250);
});

test('typeahead ignores other fields and never edits the typed name', () => {
  const s = setup();
  s.listeners.input.forEach(f => f({target: {tagName: 'TEXTAREA', value: 'abcd', dataset: {col: '1', row: '0', field: 'meds'}}}));
  s.listeners.input.forEach(f => f({target: {tagName: 'TEXTAREA', value: 'abcd', dataset: {col: '0', row: '0', field: 'obs'}}}));
  assert.equal(s.timers.length, 0);
  assert.equal(s.ctx.interviewRecord.meds[0][0], 'Metf');
});

function el(tag) {
  const n = {tag, children: [], listeners: {}, className: '', textContent: '', dataset: {}, title: '',
    append(...c) { n.children.push(...c); }, replaceChildren() { n.children = []; },
    addEventListener(t, f) { n.listeners[t] = f; }, setAttribute(k, v) { n[k] = v; }, isConnected: true};
  return n;
}
const all = (n) => [n, ...n.children.flatMap(all)];
function lookupHarness(apis) {
  const record = {meds: [['Metf']], details: {meds: [{}]}};
  const out = el('div'); const box = {value: 'Metf'};
  let n = 0;
  const ctx = vm.createContext({H: {}, interviewId: '1', interviewRecord: record, page: 'interview', errorText: String,
    interviewChanged() {}, renderInterview() {}, hmr: {api: () => apis[n++]},
    document: {addEventListener() {}, querySelector: (s) => s.startsWith('textarea') ? box : out, createElement: el}});
  vm.runInContext(src, ctx);
  return {ctx, out, record};
}
const listing = (display, over = {}) => ({source: 'pbs', code: 'C' + display, display, kind: 'pbs_listing', release: '20260101', generic_name: 'metformin', brand_name: 'Synthex', dose_form: '500 mg tablet', ...over});
const reply = (ls) => ({installed: true, results: ls, groups: ls.map(l => ({grouped: false, label: l.display, listings: [l], count: 1}))});

test('an older lookup answering after a newer one for the same text cannot add duplicate rows', async () => {
  let slow; const first = new Promise(r => { slow = r; });
  const h = lookupHarness([first, Promise.resolve(reply([listing('Synthex 500')]))]);
  const btn = {dataset: {medLookup: 'meds', row: '0'}};
  const a = h.ctx.medicineLookupClick(btn);
  const b = h.ctx.medicineLookupClick(btn);
  await b; slow(reply([listing('Synthex 500')])); await a;
  assert.equal(h.out.children.filter(c => c.className === 'med-lookup-result').length, 1);
});

test('a reply for a row whose text changed is dropped', async () => {
  let go; const p = new Promise(r => { go = r; });
  const h = lookupHarness([p]);
  const a = h.ctx.medicineLookupClick({dataset: {medLookup: 'meds', row: '0'}});
  h.record.meds[0][0] = 'Metformin changed'; go(reply([listing('Synthex 500')])); await a;
  assert.equal(h.out.children.filter(c => c.className === 'med-lookup-result').length, 0);
});

test('catalogue fields give separate name, generic and strength/form parts; the full source label stays as the tooltip', async () => {
  const h = lookupHarness([Promise.resolve(reply([listing('Synthex | 500 mg tablet, 100')]))]);
  await h.ctx.medicineLookupClick({dataset: {medLookup: 'meds', row: '0'}});
  const parts = all(h.out).filter(n => /med-result-(name|generic|form)/.test(n.className));
  assert.deepEqual(parts.map(p => p.className + ':' + p.textContent), ['med-result-name:Synthex', 'med-result-generic:metformin', 'med-result-form:500 mg tablet']);
  assert.equal(all(h.out).find(n => n.className === 'med-result-text').title, 'Synthex | 500 mg tablet, 100');
});

test('when strength/form is missing the source label is shown whole', async () => {
  const h = lookupHarness([Promise.resolve(reply([listing('Synthex | 500 mg tablet, 100', {dose_form: ''})]))]);
  await h.ctx.medicineLookupClick({dataset: {medLookup: 'meds', row: '0'}});
  assert.equal(all(h.out).filter(n => /med-result-(name|form)/.test(n.className)).length, 0);
  assert.equal(all(h.out).find(n => n.className === 'med-result-text').textContent, 'Synthex | 500 mg tablet, 100');
});
