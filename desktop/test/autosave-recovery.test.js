const test = require('node:test');
const assert = require('node:assert/strict');
const { autosaver, interviewDrafts } = require('../renderer/helpers');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(shared = new Map(), post = async () => {}, equivalent) {
  global.localStorage = {
    get length() { return shared.size; },
    key: index => [...shared.keys()][index] ?? null,
    getItem: key => shared.get(key) ?? null,
    setItem: (key, value) => shared.set(key, value),
    removeItem: key => shared.delete(key),
  };
  let record = { notes: '' }, id = 'one', lastStatus = '';
  const saver = autosaver({ getRecord: () => record, getId: () => id,
    draftKey: () => `interview:${id}`, endpoint: post, equivalent,
    status: text => { lastStatus = text; }, errorText: () => 'failed' });
  return { saver, shared, get record() { return record; }, set record(v) { record = v; },
    set id(v) { id = v; }, get status() { return lastStatus; } };
}

test('pre-change draft recovery fills new interview defaults before saving', async () => {
  const context = vm.createContext({ H: { ...require('../renderer/helpers'), autosaver: () => ({}) }, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  const normalize = record => context.normalizeInterviewDetails(record);
  const shared = new Map(), old = setup(shared);
  old.record = context.normalizeInterviewDetails({ notes: '', details: { meds: [{}], other_meds: [{}], extra: 'keep' }, meds: [[]], other_meds: [[]] }, false);
  old.saver.reset(old.record); old.record.notes = 'draft'; old.saver.changed();
  let saved; const reopened = setup(shared, async (_, record) => { saved = record; }, context.interviewEquivalent);
  reopened.record = normalize({ notes: '', details: { meds: [{}], other_meds: [{}], extra: 'keep' }, meds: [[]], other_meds: [[]] });
  assert.equal(reopened.saver.reset(reopened.record).recovered, true); normalize(reopened.record);
  assert.equal(reopened.record.notes, 'draft');
  assert.equal(await reopened.saver.save(), true);
  assert.equal(saved.details.sx_falls, '');
  assert.equal(saved.details.meds[0].prn_use, '');
  assert.equal(saved.details.other_meds[0].kind, '');
  assert.equal(saved.details.extra, 'keep');
  assert.equal(shared.has('hmr-draft:interview:one'), false);
  const again = setup(shared, undefined, context.interviewEquivalent);
  again.record = saved;
  assert.equal(again.saver.reset(again.record).conflict, false);
  old.saver.reset(old.record);
});

test('old-format offline recovery clears the draft after saving', async () => {
  const context = vm.createContext({ H: { ...require('../renderer/helpers'), autosaver: () => ({}) }, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  const base = context.normalizeInterviewDetails({ notes: '', details: { meds: [{}] }, meds: [[]] }, false);
  const draft = structuredClone(base); draft.notes = 'draft';
  const shared = new Map([['hmr-draft:interview:one', JSON.stringify({ base: JSON.stringify(base), snapshot: JSON.stringify(draft), conflicts: [] })]]);
  setup(shared);
  let record = context.normalizeInterviewDetails(structuredClone(draft)), saved;
  const saver = autosaver({ getRecord: () => record, getId: () => 'one', draftKey: () => 'interview:one',
    equivalent: context.interviewEquivalent, loadCurrent: async () => context.normalizeInterviewDetails(structuredClone(base)),
    endpoint: async (_, value) => { saved = value; }, status: () => {}, errorText: () => 'error' });
  assert.equal(saver.resetOffline(record), true);
  assert.equal(await saver.save(), true);
  assert.equal(shared.has('hmr-draft:interview:one'), false);
  const again = setup(shared, undefined, context.interviewEquivalent); again.record = saved;
  assert.equal(again.saver.reset(again.record).conflict, false);
});

test('changes are durable immediately, recover after restart and clear on confirmation', async () => {
  const shared = new Map(), first = setup(shared);
  first.saver.reset(first.record);
  first.record.notes = 'draft'; first.saver.changed();
  assert.equal(JSON.parse(shared.get('hmr-draft:interview:one')).snapshot, JSON.stringify(first.record));
  const reopened = setup(shared);
  assert.equal(reopened.saver.reset(reopened.record).recovered, true);
  assert.equal(reopened.record.notes, 'draft');
  assert.equal(await reopened.saver.save(), true);
  assert.equal(shared.size, 0);
  first.saver.reset(first.record);
});

test('failed save retains draft and retry confirms latest edit', async () => {
  let fail = true;
  const x = setup(new Map(), async () => { if (fail) throw Error('offline'); });
  x.saver.reset(x.record); x.record.notes = 'offline'; x.saver.changed();
  assert.equal(await x.saver.save(), false);
  assert.equal(x.saver.dirty(), true);
  assert.match(x.status, /Not saved/);
  fail = false;
  assert.equal(await x.saver.save(), true);
  assert.equal(x.shared.size, 0);
});

test('edits during an in-flight save are serialized and never reported saved early', async () => {
  const calls = []; let release;
  const x = setup(new Map(), async (_id, record) => {
    calls.push(record.notes);
    if (calls.length === 1) await new Promise(resolve => { release = resolve; });
  });
  x.saver.reset(x.record); x.record.notes = 'first'; x.saver.changed();
  const pending = x.saver.save();
  x.record.notes = 'second'; x.saver.changed();
  assert.doesNotMatch(x.status, /^Saved/);
  release(); assert.equal(await pending, true);
  assert.deepEqual(calls, ['first', 'second']);
  assert.equal(x.shared.size, 0);
});

test('different patients are isolated and conflicting drafts require explicit choice', async () => {
  const shared = new Map(), x = setup(shared);
  x.saver.reset(x.record); x.record.notes = 'old draft'; x.saver.changed();
  x.id = 'two'; x.record = { notes: 'two' }; x.saver.reset(x.record);
  assert.equal(x.record.notes, 'two');
  x.id = 'one'; x.record = { notes: 'newer disk' };
  assert.equal(x.saver.reset(x.record).conflict, true);
  assert.equal(x.record.notes, 'newer disk');
  assert.equal(await x.saver.save(), false);
  assert.equal(x.saver.resolveConflict('restore'), true);
  assert.equal(x.record.notes, 'old draft');
  assert.equal(await x.saver.save(), true);
});

test('storage failure is visible and decline to leave keeps edits', async () => {
  const x = setup(new Map(), async () => { throw Error('offline'); });
  x.saver.reset(x.record);
  global.localStorage.setItem = () => { throw Error('full'); };
  x.record.notes = 'unsaved'; x.saver.changed();
  assert.match(x.status, /Local draft unavailable/);
  global.confirm = () => false;
  assert.equal(await x.saver.leave(), false);
  assert.equal(x.record.notes, 'unsaved');
  x.saver.reset(x.record);
});

test('unreadable drafts are preserved and legacy callers still save', async () => {
  const shared = new Map([['hmr-draft:interview:one', '{bad']]), x = setup(shared);
  assert.equal(x.saver.reset(x.record).storageError, true);
  x.record.notes = 'new'; x.saver.changed();
  assert.equal(shared.get('hmr-draft:interview:one'), '{bad');
  await x.saver.save();
  let record = { value: 1 }, posted;
  const legacy = autosaver({ getRecord: () => record, getId: () => 'x', endpoint: async (_, value) => { posted = value; }, status: () => {}, errorText: () => 'error' });
  legacy.reset(record); record.value = 2; legacy.changed();
  assert.equal(await legacy.save(), true);
  assert.equal(posted.value, 2);
});

test('an old patient response cannot mark a newly opened patient saved', async () => {
  let release;
  const shared = new Map(), x = setup(shared, async () => new Promise(resolve => { release = resolve; }));
  x.saver.reset(x.record); x.record.notes = 'first patient'; x.saver.changed();
  const pending = x.saver.save();
  x.id = 'two'; x.record = { notes: 'second baseline' }; x.saver.reset(x.record);
  x.record.notes = 'second edit'; x.saver.changed();
  release(); assert.equal(await pending, false);
  assert.equal(x.saver.dirty(), true);
  assert.equal(JSON.parse(shared.get('hmr-draft:interview:two')).snapshot, JSON.stringify(x.record));
  x.saver.reset(x.record);
});

test('offline reopen waits for a fresh baseline before posting and preserves conflicts', async () => {
  const shared = new Map(), x = setup(shared);
  x.saver.reset(x.record); x.record.notes = 'offline draft'; x.saver.changed();
  x.saver.reset(x.record);
  let record, online = false, posted = 0, current = { notes: '' };
  const saver = autosaver({ getRecord: () => record, getId: () => 'one', draftKey: () => 'interview:one',
    loadCurrent: async () => { if (!online) throw Error('offline'); return current; },
    endpoint: async () => { posted++; }, status: () => {}, errorText: () => 'error' });
  record = saver.offlineDraft();
  assert.equal(record.notes, 'offline draft');
  assert.equal(saver.resetOffline(record), true);
  assert.equal(await saver.save(), false);
  assert.equal(posted, 0);
  online = true; current = { notes: 'newer disk' };
  assert.equal(await saver.save(), false);
  assert.equal(posted, 0);
  assert.equal(record.notes, 'newer disk');
  assert.equal(saver.resolveConflict('restore'), true);
  assert.equal(await saver.save(), true);
  assert.equal(posted, 1);
});


test('offline inventory finds only valid patient interview drafts and leaves corrupt entries untouched', () => {
  const shared = new Map(), x = setup(shared);
  x.id = '42'; x.record = { header: { name: 'Person' }, notes: '' }; x.saver.reset(x.record);
  x.record.notes = 'draft'; x.saver.changed();
  shared.set('hmr-draft:interview:43', '{bad');
  shared.set('hmr-draft:interview:../bad', shared.get('hmr-draft:interview:42'));
  shared.set('hmr-draft:report:44', shared.get('hmr-draft:interview:42'));
  assert.deepEqual(interviewDrafts(), [{ id: '42', name: 'Person' }]);
  assert.equal(shared.get('hmr-draft:interview:43'), '{bad');
  assert.equal(x.saver.offlineDraft().notes, 'draft');
  x.saver.reset(x.record);
});


test('online conflict retains both versions and never replaces newer consent', async () => {
  const shared = new Map(); setup(shared);
  let record = { notes: 'base', revision: 'old', consent: { signed: false } };
  let remote = { notes: 'remote', revision: 'new', consent: { signed: true }, consent_file: 'signed.pdf' };
  let posts = 0;
  const saver = autosaver({ getRecord: () => record, getId: () => 'one', draftKey: () => 'interview:one',
    loadCurrent: async () => structuredClone(remote), status: () => {}, errorText: e => e.message,
    endpoint: async (_id, value) => { posts++; if (value.revision !== remote.revision) throw Error('interview conflict');
      remote = { ...value, revision: 'next' }; return remote; } });
  saver.reset(record); record.notes = 'local'; saver.changed();
  assert.equal(await saver.save(), false);
  assert.equal(saver.hasConflict(), true); assert.equal(record.notes, 'remote');
  assert.equal(saver.resolveConflict('restore'), true);
  assert.equal(record.notes, 'local'); assert.equal(record.consent.signed, true);
  assert.equal(await saver.save(), true); assert.equal(posts, 2);
  const history = JSON.parse(shared.get('hmr-draft:interview:one:conflict-history'));
  assert.equal(JSON.parse(history[0].local).notes, 'local');
  assert.equal(JSON.parse(history[0].remote).notes, 'remote');
  assert.equal(remote.consent.signed, true);
});
