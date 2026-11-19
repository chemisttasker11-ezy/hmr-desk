const test = require('node:test');
const assert = require('node:assert/strict');
const { autosaver } = require('../renderer/helpers');

function make(error) {
  const store = new Map();
  global.localStorage = { get length() { return store.size; }, key: i => [...store.keys()][i] ?? null,
    getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k) };
  let record = { name: 'x' }, status = '';
  const saver = autosaver({ getRecord: () => record, getId: () => 'one', draftKey: () => 'report:one',
    endpoint: async () => { throw error; }, status: t => { status = t; }, errorText: e => String(e.message) });
  saver.reset(record); record.name = 'y';
  return { saver, get status() { return status; } };
}

test('an engine refusal of the content shows its reason, not unreachable storage', async () => {
  const x = make(Error('invalid issues'));
  assert.equal(await x.saver.save(true), false);
  assert.equal(x.status, 'Not saved - invalid issues');
});

for (const text of ['fetch failed', 'SocketError: other side closed', 'connect ECONNRESET']) {
  test(`a dropped connection keeps the storage wording: ${text}`, async () => {
    const x = make(Error(text));
    assert.equal(await x.saver.save(true), false);
    assert.equal(x.status, 'Not saved - Unable to reach storage; retrying');
  });
}
