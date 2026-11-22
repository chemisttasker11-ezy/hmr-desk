const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function load(rows) {
  const listeners = {};
  const context = vm.createContext({ esc: H.esc, page: 'interview', document: { addEventListener: (n, f) => { (listeners[n] ||= []).push(f); } },
    renderInterview() { context.rendered = (context.rendered || 0) + 1; }, interviewChanged(k) { (context.changed ||= []).push(k); } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview-duplicates.js'), 'utf8'), context);
  const metas = rows.map((r, n) => ({ use_status: r[1] || 'taking', item_id: String(n + 1).padStart(32, '0'), ...(r[2] ? { reference: r[2] } : {}) }));
  context.interviewRecord = { meds: rows.map(r => [r[0], '', '', '', '']), other_meds: [], details: { meds: metas, other_meds: [] } };
  return { context, listeners, metas, run: code => vm.runInContext(code, context) };
}
const cand = (t, i) => JSON.parse(t.run(`JSON.stringify(interviewDupCandidates(interviewRecord, interviewDupEntries(interviewRecord)[${i}]).map(e => e.i))`));

test('suggests only the same whole medicine text with a strength, or the same linked catalogue entry', () => {
  const t = load([['Metformin 500 mg tablet'], ['metformin  500 MG tablet'], ['Metformin 1000 mg tablet'], ['Metformin 500 mg capsule'], ['Metformin'], ['Metformin']]);
  assert.deepEqual(cand(t, 0), [1]);            // case and spacing only
  assert.deepEqual(cand(t, 2), []);             // 10 mg versus 20 mg style: a different strength never matches
  assert.deepEqual(cand(t, 3), []);             // a different form never matches
  assert.deepEqual(cand(t, 4), []);             // the name alone, with no strength, is not enough
  const ref = { source: 'amt', code: '42' };
  const r = load([['Brand A tablet', 'taking', ref], ['Generic B tablet', 'taking', { ...ref }], ['Other tablet', 'taking', { source: 'amt', code: '43' }]]);
  assert.deepEqual(cand(r, 0), []);   // same code but different entered text: the text wins, no suggestion
  const same = load([['Metformin 500 mg tablet', 'taking', ref], ['Metformin 500 mg tablet', 'taking', { ...ref }], ['Metformin 500 mg tablet', 'taking', { source: 'amt', code: '99' }]]);
  assert.deepEqual(cand(same, 0), [1]);   // identical text and the same code
  assert.deepEqual(cand(same, 2), []);    // identical text but linked to a different catalogue entry
  const stale = load([['Metformin 500 mg tablet', 'taking', ref], ['Metformin 850 mg tablet', 'taking', { ...ref }]]);
  assert.deepEqual(cand(stale, 0), []);   // stale code beside edited strength
});

test('confirming needs an explicit choice, records only the link, and never changes use or removes rows', () => {
  const t = load([['Metformin 500 mg tablet'], ['Metformin 500 mg tablet', 'not_using']]);
  t.run('interviewDupConfirm("meds", 1, true)');
  assert.equal(t.metas[1].duplicate_of, undefined);   // nothing chosen yet: nothing saved
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[1].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 1, true)`);
  const link = t.metas[1].duplicate_of;
  assert.equal(link.item_id, t.metas[0].item_id);
  assert.equal(link.own_sig, 'metformin 500 mg tablet|');
  assert.deepEqual([t.metas[0].use_status, t.metas[1].use_status], ['taking', 'not_using']);
  assert.equal(t.context.interviewRecord.meds.length, 2);
  t.run('interviewDupConfirm("meds", 1, false)');
  assert.equal(t.metas[1].duplicate_of, undefined);
});

test('self links, chains and marked targets are refused in the form too', () => {
  const t = load([['X 5 mg'], ['X 5 mg'], ['X 5 mg']]);
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[0].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 0, true)`);
  assert.equal(t.metas[0].duplicate_of, undefined);
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[1].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 1, true)`);
  assert.ok(t.metas[1].duplicate_of);
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[2].item_id, interviewRecord.details.meds[1].item_id); interviewDupConfirm("meds", 2, true)`);
  assert.equal(t.metas[2].duplicate_of, undefined);          // target is itself marked
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[0].item_id, interviewRecord.details.meds[2].item_id); interviewDupConfirm("meds", 0, true)`);
  assert.equal(t.metas[0].duplicate_of, undefined);          // would make a cycle through a marked row
});

test('an edit to either entry, or removing the target, makes the confirmation not current', () => {
  const t = load([['Metformin 500 mg tablet'], ['Metformin 500 mg tablet']]);
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[1].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 1, true)`);
  const state = () => t.run('interviewDupState(interviewRecord, interviewDupEntries(interviewRecord)[1]).current');
  assert.equal(state(), true);
  t.context.interviewRecord.meds[0][0] = 'Metformin 850 mg tablet';
  assert.equal(state(), false);
  t.run('interviewDupLapse(interviewRecord)');
  assert.equal(t.metas[1].duplicate_of.lapsed, true);
  assert.equal(t.metas[1].duplicate_of.note, '');                 // audit stays on the record
  t.context.interviewRecord.meds[0][0] = 'Metformin 500 mg tablet';
  assert.equal(state(), false);                                      // restoring the text does not revive it
  t.run('interviewDupConfirm("meds", 1, false)');
  t.run(`interviewDupDraft.set(interviewRecord.details.meds[1].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 1, true)`);
  assert.equal(state(), true);                                       // an explicit new confirmation is current again
  assert.equal(t.metas[1].duplicate_of.lapsed, undefined);
  t.context.interviewRecord.meds[1][0] = 'Metformin 500 mg capsule';
  assert.equal(state(), false);
  t.context.interviewRecord.meds[1][0] = 'Metformin 500 mg tablet';
  t.context.interviewRecord.meds.shift(); t.context.interviewRecord.details.meds.shift();
  assert.equal(t.run('interviewDupState(interviewRecord, interviewDupEntries(interviewRecord)[0]).current'), false);
});

const R5 = { source: 'amt', code: '5' };
const CASES = [ // same table as the engine test test_duplicate_confirmation.py
  ['Metformin 500 mg tablet', null, 'metformin  500 MG tablet', null, true],
  ['Metformin 500 mg tablet', null, 'Metformin 1000 mg tablet', null, false],
  ['Metformin 500 mg tablet', null, 'Metformin 500 mg capsule', null, false],
  ['Metformin', null, 'Metformin', null, false],
  ['Brand A 500 mg tablet', R5, 'BRAND A 500mg tablets', R5, true],
  ['Brand A 500 mg tablet', R5, 'Generic B 500 mg tablets', R5, false],
  ['Brand A 500 mg tablet', R5, 'Generic B 850 mg tablet', R5, false],
  ['Brand A 500 mg tablet', R5, 'Brand A 500 mg tablet', { source: 'amt', code: '6' }, false],
  ['Brand A 500 mg MR tablet', R5, 'Brand A 500 mg tablet', R5, false],
  ['Brand X 10 mg extended-release tablet', R5, 'Brand X 10 mg immediate-release tablet', R5, false],
  ['Brand X 10 mg/20 mg tablet', R5, 'Brand X 20 mg/10 mg tablet', R5, false],
  ['Brand X 10 mg gel', R5, 'Brand X 10 mg powder', R5, false],
  ['Brand X 10 mg widget', R5, 'Brand X 10 mg gadget', R5, false],
  ['Version 2 notes', R5, 'Version 2 notes', R5, false],
  ['Syrup 5 mg/5 mL', null, 'Syrup 5 mg/5 mL', null, true],
  ['Syrup 5 mg/5 mL', null, 'Syrup 5 mg/10 mL', null, false],
];
test('only entries that show the same strength and form can be confirmed, matching the engine rule', () => {
  for (const [a, ra, b, rb, expected] of CASES) {
    const t = load([[a, 'taking', ra], [b, 'taking', rb]]);
    assert.equal(t.run('interviewDupCompatible(interviewDupEntries(interviewRecord)[0], interviewDupEntries(interviewRecord)[1])'), expected, a + ' vs ' + b);
    t.run('interviewDupDraft.set(interviewRecord.details.meds[1].item_id, interviewRecord.details.meds[0].item_id); interviewDupConfirm("meds", 1, true)');
    assert.equal(!!t.metas[1].duplicate_of, expected, 'manual confirm: ' + a + ' vs ' + b);   // a deliberate pick of a different strength is refused too
  }
});

const ADVERSARIAL = [['Brand X .5 mg tablet', 'Brand X 5 mg tablet'], ['Brand X 0.5 mg tablet', 'Brand X .5 mg tablet'], ['Brand X 5 mg tablet', 'Brand X 5. mg tablet'], ['Brand X 5-10 mg tablet', 'Brand X 5+10 mg tablet'], ['Brand X 5-10 mg tablet', 'Brand X 5/10 mg tablet'], ['Brand X 5+10 mg tablet', 'Brand X 5/10 mg tablet'], ['Brand X 5,10 mg tablet', 'Brand X 5/10 mg tablet'], ['Brand X 5 mg/mL solution', 'Brand X 5 mg/5 mL solution'], ['Brand X 5 mg per mL solution', 'Brand X 5 mg/mL solution'], ['Brand X 5 mg/mL solution', 'Brand X 5 mg:mL solution'], ['Brand X 1,000 mg tablet', 'Brand X 1000 mg tablet'], ['Brand X 1.000 mg tablet', 'Brand X 1000 mg tablet'], ['Brand X 5 mg tablet', 'Brand X 50 mg tablet'], ['Brand X 1 0 mg tablet', 'Brand X 10 mg tablet'], ['Brand X 5 mg tablet', 'Brand X 5 mg (tablet)'], ['Brand X 5 mg tablet', 'Brand X 5 mg tablet x2'], ['Brand X 5 mg tablet', 'Brand X 5 mg tablet.'], ['Brand X 5 mg EC tablet', 'Brand X 5 mg-EC tablet'], ['Brand X 5 mg tablet', 'Brand X 5 mcg tablet'], ['Brand X 5 mg tablet', 'Brand X 5 g tablet'], ['Brand X 5 mg tablet', 'Brand X 5 % tablet'], ['Brand X 5 mg tablet', 'Brand-X 5 mg tablet'], ['Brand X µ5 tablet', 'Brand X 5 tablet'], ['Brand X 5 mg tablet', 'Brand X ５ mg tablet']];
test('punctuation, digits and units are never normalised into the same identity (same pairs as the engine test)', () => {
  for (const [a, b] of ADVERSARIAL) for (const ref of [null, R5]) {
    const t = load([[a, 'taking', ref], [b, 'taking', ref]]);
    assert.equal(t.run('interviewDupCompatible(interviewDupEntries(interviewRecord)[0], interviewDupEntries(interviewRecord)[1])'), false, a + ' vs ' + b);
    assert.equal(t.run('interviewDupCompatible(interviewDupEntries(interviewRecord)[1], interviewDupEntries(interviewRecord)[0])'), false, b + ' vs ' + a);
  }
});

test('suggestions use the confirmation predicate: version-number text, unequal punctuation and different catalogue entries are never suggested', () => {
  for (const [a, b, ra, rb, expected] of [['Version 2 notes', 'Version 2 notes', null, null, 0], ['Brand X .5 mg tablet', 'Brand X 5 mg tablet', null, null, 0], ['Brand A 500 mg tablet', 'Brand A 500 mg tablet', R5, { source: 'amt', code: '6' }, 0], ['Brand A 500 mg tablet', 'BRAND A 500mg tablets', null, null, 1]]) {
    const t = load([[a, 'taking', ra], [b, 'taking', rb]]);
    assert.equal(t.run('interviewDupCandidates(interviewRecord, interviewDupEntries(interviewRecord)[0]).length'), expected, a + ' vs ' + b);
  }
});
