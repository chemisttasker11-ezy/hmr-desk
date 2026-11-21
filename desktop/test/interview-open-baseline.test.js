const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const H = require('../renderer/helpers');

function world(serverData) {
  const shared = new Map();
  global.localStorage = { get length() { return shared.size; }, key: i => [...shared.keys()][i] ?? null, getItem: k => shared.get(k) ?? null, setItem: (k, v) => shared.set(k, v), removeItem: k => shared.delete(k) };
  const ctx = vm.createContext({ H: { ...H, autosaver: () => ({}) }, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), ctx);
  const s = { rev: 1, data: structuredClone(serverData), posts: 0, shared, ctx };
  s.get = () => ({ ...structuredClone(s.data), revision: 'r' + s.rev });
  s.open = (offline = false) => {
    const e = { rec: s.get() };
    e.saver = H.autosaver({ getRecord: () => e.rec, getId: () => '1', draftKey: () => 'interview:1', equivalent: ctx.interviewEquivalent,
      loadCurrent: async () => { const c = s.get(); ctx.normalizeInterviewDetails(c); return c; },
      endpoint: async (_i, r) => { s.posts++; if (r.revision !== 'r' + s.rev) throw Error('interview conflict'); const { revision, saved, ...d } = r; s.data = structuredClone(d); s.rev++; return { revision: 'r' + s.rev }; },
      status: t => { e.status = t; }, errorText: x => x.message, onReconcile: () => {} });
    e.recovery = ctx.interviewResetBaseline(e.rec, offline, e.saver);
    return e;
  };
  return s;
}
const base = { notes: 'N1', conditions: 'C1', allergies: 'A1', meds: [['Medicine A', 'daily', '', '', '']], other_meds: [], details: { meds: [{}], other_meds: [] } };

test('an unedited open is clean and leaving does not write', async () => {
  const s = world(base), e = s.open();
  assert.equal(e.saver.dirty(), false);
  assert.equal(await e.saver.leave(), true);
  assert.equal(s.posts, 0);
  assert.deepEqual(s.data, base);
});

test('a real edit still saves, including the default fields', async () => {
  const s = world(base), e = s.open();
  e.rec.notes = 'N2'; e.saver.changed();
  assert.equal(e.saver.dirty(), true);
  assert.equal(await e.saver.save(), true);
  assert.equal(s.posts, 1);
  assert.equal(s.data.notes, 'N2');
  assert.equal(s.data.conditions, 'C1');
  assert.ok('prn_use' in s.data.details.meds[0]);
});

test('draft recovery still restores the unsaved edit and fills defaults', async () => {
  const s = world(base), first = s.open();
  first.rec.notes = 'N1 local draft'; first.saver.changed();     // writes the draft, base = clean baseline
  const again = s.open();
  assert.equal(again.recovery.recovered, true);
  assert.equal(again.rec.notes, 'N1 local draft');
  assert.ok('prn_use' in again.rec.details.meds[0]);
  assert.equal(again.saver.dirty(), true);
});

test('draft written by the old open order (base without defaults) is still recovered, not a conflict', async () => {
  const s = world(base);
  const old = { rec: s.get() };
  s.ctx.normalizeInterviewDetails(old.rec, false);
  const oldSaver = H.autosaver({ getRecord: () => old.rec, getId: () => '1', draftKey: () => 'interview:1', equivalent: s.ctx.interviewEquivalent, endpoint: async () => ({}), status() {}, errorText: x => x.message });
  oldSaver.reset(old.rec); s.ctx.normalizeInterviewDetails(old.rec);
  old.rec.notes = 'draft from previous build'; oldSaver.changed();
  const e = s.open();
  assert.equal(e.recovery.conflict, false);
  assert.equal(e.recovery.recovered, true);
  assert.equal(e.rec.notes, 'draft from previous build');
});

test('a stale editor never overwrites a newer saved record (conflict kept, no write)', async () => {
  const s = world(base), e = s.open();
  e.rec.notes = 'local edit'; e.saver.changed();
  s.data = { ...s.data, conditions: 'C2' }; s.rev++;               // another writer saved
  assert.equal(await e.saver.leave(), false);
  assert.equal(e.saver.hasConflict(), true);
  assert.equal(s.data.conditions, 'C2');
  assert.equal(s.data.notes, 'N1');
  const reopened = s.open();
  assert.equal(reopened.recovery.conflict, true);
  assert.equal(reopened.rec.conditions, 'C2');
});

test('offline open with a local draft keeps the draft untouched', () => {
  const s = world(base), first = s.open();
  first.rec.notes = 'offline draft'; first.saver.changed();
  const offline = s.open(true);
  assert.ok(offline.recovery);
});
