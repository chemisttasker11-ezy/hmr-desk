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
