const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const { autosaver } = require('../renderer/helpers');

function setup({ remote, post } = {}) {
  global.localStorage = (m => ({ get length() { return m.size; }, key: i => [...m.keys()][i] ?? null, getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: k => m.delete(k) }))(new Map());
  const state = { record: { notes: '', revision: 'r1' }, id: 'one', remote: remote || { notes: '', revision: 'r1' }, posts: 0, status: '', gate: null };
  state.saver = autosaver({ getRecord: () => state.record, getId: () => state.id, draftKey: () => `interview:${state.id}`,
    endpoint: async (_, v) => { state.posts++; if (post) return post(v); return { revision: 'r2' }; },
    loadCurrent: async () => { if (state.gate) await state.gate; return JSON.parse(JSON.stringify(state.remote)); },
    status: t => { state.status = t; }, errorText: () => 'failed' });
  state.saver.reset(state.record);
  return state;
}

test('an unchanged saved record is current and nothing happens', async () => {
  const s = setup();
  assert.equal(await s.saver.checkRemote(), 'current');
  assert.equal(s.posts, 0);
});

test('saved data changed elsewhere and the form is clean: reported stale-clean, record untouched, nothing written', async () => {
  const s = setup({ remote: { notes: 'from mcp', revision: 'r9' } });
  assert.equal(await s.saver.checkRemote(), 'stale-clean');
  assert.equal(s.record.notes, ''); assert.equal(s.posts, 0); assert.equal(s.saver.hasConflict(), false);
});

test('saved data changed elsewhere and the form has unsaved edits: the draft is kept as a conflict, never saved over the remote save', async () => {
  const s = setup({ remote: { notes: 'from mcp', revision: 'r9' } });
  s.record.notes = 'my edit'; // dirty, autosave not run
  assert.equal(await s.saver.checkRemote(), 'conflict');
  assert.equal(s.saver.hasConflict(), true);
  assert.equal(s.posts, 0);
  assert.equal(s.record.notes, 'from mcp');          // the form now shows the saved data
  assert.equal(await s.saver.save(), false);           // saving stays blocked until an explicit choice
  assert.equal(s.posts, 0);
  assert.equal(s.saver.resolveConflict('restore'), true);   // explicit restore brings the draft back on the new revision
  assert.equal(s.record.notes, 'my edit'); assert.equal(s.record.revision, 'r9');
});

test('typing while the check is fetching is treated as unsaved edits, not discarded', async () => {
  const s = setup({ remote: { notes: 'from mcp', revision: 'r9' } });
  let release; s.gate = new Promise(r => { release = r; });
  const pending = s.saver.checkRemote();
  s.record.notes = 'typed during fetch'; release();
  assert.equal(await pending, 'conflict');
  assert.equal(s.posts, 0);
  s.saver.resolveConflict('restore');
  assert.equal(s.record.notes, 'typed during fetch');
});

test('a save in flight, an open conflict or a patient switch during the check skip it', async () => {
  const inflight = setup({ remote: { notes: 'x', revision: 'r9' }, post: () => new Promise(() => {}) });
  inflight.record.notes = 'edit'; void inflight.saver.save();
  await new Promise(r => setTimeout(r, 10));
  assert.equal(await inflight.saver.checkRemote(), 'skipped');
  const switched = setup({ remote: { notes: 'x', revision: 'r9' } });
  let release; switched.gate = new Promise(r => { release = r; });
  const pending = switched.saver.checkRemote();
  switched.id = 'two'; release();
  assert.equal(await pending, 'skipped');
});

function wrapper({ result, switchTo, dirty = false }) {
  const calls = { screen: 0 };
  const context = vm.createContext({ page: 'interview', interviewId: 'one', interviewRequest: 1, interviewRecord: { a: 1 }, interviewPathologyDirty: false, interviewSaveStatus: '',
    $: () => null, window: { addEventListener() {} }, document: { addEventListener() {} }, Date,
    interviewSaver: { checkRemote: async () => { if (switchTo) { context.interviewId = switchTo; } return result; }, dirty: () => dirty },
    interviewScreen: async () => { calls.screen++; context.interviewRecord = { a: 2 }; } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview-freshness.js'), 'utf8'), context);
  return { context, calls, check: () => context.interviewFreshnessCheck(true) };
}

test('the screen reloads only for a clean stale form on the same patient', async () => {
  const ok = wrapper({ result: 'stale-clean' });
  assert.equal(await ok.check(), 'reloaded'); assert.equal(ok.calls.screen, 1); assert.equal(ok.context.interviewSaveStatus, 'Updated from saved data');
  const other = wrapper({ result: 'stale-clean', switchTo: 'two' });
  assert.equal(await other.check(), 'skipped'); assert.equal(other.calls.screen, 0);
  const edited = wrapper({ result: 'stale-clean', dirty: true });
  assert.equal(await edited.check(), 'skipped'); assert.equal(edited.calls.screen, 0);
  const conflict = wrapper({ result: 'conflict' });
  assert.equal(await conflict.check(), 'conflict'); assert.equal(conflict.calls.screen, 0);
});

test('unsaved pathology edits and non-interview pages skip the check', async () => {
  const p = wrapper({ result: 'stale-clean' }); p.context.interviewPathologyDirty = true;
  assert.equal(await p.check(), 'skipped');
  const q = wrapper({ result: 'stale-clean' }); q.context.page = 'today';
  assert.equal(await q.check(), 'skipped'); assert.equal(q.calls.screen, 0);
});
