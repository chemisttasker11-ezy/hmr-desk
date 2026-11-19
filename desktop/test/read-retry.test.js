const test = require('node:test');
const assert = require('node:assert/strict');
const { fetchWithReadRetry, isDroppedSocket } = require('../src/read-retry');

const dropped = () => Object.assign(new TypeError('fetch failed'), { cause: { code: 'UND_ERR_SOCKET' } });

test('a GET whose socket was closed with no reply is retried once and can succeed', async () => {
  let calls = 0;
  const fetchFn = async () => { calls += 1; if (calls === 1) throw dropped(); return { ok: true }; };
  const res = await fetchWithReadRetry(fetchFn, 'GET', 'http://x/api/a', {}, 1);
  assert.equal(calls, 2);
  assert.equal(res.ok, true);
});

test('a GET that fails twice surfaces the second error (one retry only)', async () => {
  let calls = 0;
  const fetchFn = async () => { calls += 1; throw dropped(); };
  await assert.rejects(fetchWithReadRetry(fetchFn, 'GET', 'http://x/api/a', {}, 1), /fetch failed/);
  assert.equal(calls, 2);
});

test('a POST is never retried, so an action of unknown outcome is not sent twice', async () => {
  let calls = 0;
  const fetchFn = async () => { calls += 1; throw dropped(); };
  await assert.rejects(fetchWithReadRetry(fetchFn, 'POST', 'http://x/api/a', {}, 1), /fetch failed/);
  assert.equal(calls, 1);
});

test('other errors are not retried', async () => {
  let calls = 0;
  const fetchFn = async () => { calls += 1; throw Object.assign(new TypeError('fetch failed'), { cause: { code: 'ECONNREFUSED' } }); };
  await assert.rejects(fetchWithReadRetry(fetchFn, 'GET', 'http://x/api/a', {}, 1));
  assert.equal(calls, 1);
  assert.equal(isDroppedSocket(dropped()), true);
  assert.equal(isDroppedSocket(null), false);
});
