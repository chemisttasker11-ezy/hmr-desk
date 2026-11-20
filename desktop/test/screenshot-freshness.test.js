const test = require('node:test');
const assert = require('node:assert/strict');
const { captureFresh } = require('../src/control');

// A fake webContents with a scripted capture and in-page fingerprint per call.
function fake({ shots, prints, painted = true, hangPaint = false }) {
  const state = { shot: 0, print: 0, invalidated: 0 };
  return {
    state,
    invalidate: () => { state.invalidated += 1; },
    executeJavaScript: (code) => {
      if (/requestAnimationFrame/.test(code)) return hangPaint ? new Promise(() => {}) : Promise.resolve(painted);
      return Promise.resolve(prints[Math.min(state.print++, prints.length - 1)]);
    },
    capturePage: async () => ({ toPNG: () => Buffer.from(shots[Math.min(state.shot++, shots.length - 1)]) }),
  };
}

test('a first capture is returned with window metadata, and never exposes the content fingerprint', async () => {
  const ctx = {};
  const win = { isVisible: () => true, isMinimized: () => false, isFocused: () => true };
  const r = await captureFresh(ctx, '', fake({ shots: ['a'], prints: ['p1'] }), win);
  assert.equal(r.ok, true); assert.equal(r.stale_detected, false); assert.equal(r.content_changed_since_previous, null); assert.ok(r.png);
  assert.deepEqual(r.window, { visible: true, minimized: false, focused: true });
  assert.ok(!JSON.stringify(r).includes('p1'), 'the fingerprint value must not leave the process');
  assert.ok(!('content_fingerprint' in r));
});

test('an identical frame is accepted when the page content did not change', async () => {
  const ctx = {};
  await captureFresh(ctx, '', fake({ shots: ['a'], prints: ['p1'] }), null);
  const r = await captureFresh(ctx, '', fake({ shots: ['a'], prints: ['p1'] }), null);
  assert.equal(r.ok, true); assert.equal(r.identical_to_previous, true); assert.equal(r.attempts, 1); assert.equal(r.content_changed_since_previous, false);
});

test('an identical frame while the content changed is retried and accepted only when the frame then differs', async () => {
  const ctx = {};
  await captureFresh(ctx, '', fake({ shots: ['old'], prints: ['p1'] }), null);
  const wc = fake({ shots: ['old', 'new'], prints: ['p2', 'p2'] });
  const r = await captureFresh(ctx, '', wc, null);
  assert.equal(r.ok, true); assert.equal(r.attempts, 2); assert.equal(Buffer.from(r.png, 'base64').toString(), 'new');
  assert.ok(wc.state.invalidated >= 2);
});

test('a frame that stays identical while the content changed is refused with the image withheld', async () => {
  const ctx = {};
  await captureFresh(ctx, '', fake({ shots: ['old'], prints: ['p1'] }), null);
  const r = await captureFresh(ctx, '', fake({ shots: ['old'], prints: ['p2'] }), null);
  assert.equal(r.ok, false); assert.equal(r.stale_detected, true); assert.equal(r.png, undefined); assert.equal(r.attempts, 3);
  assert.match(r.reason, /identical to the previous capture/);
});

test('this check is partial: a changed but outdated frame, and a first capture, are accepted (documented limit)', async () => {
  const ctx = {};
  const first = await captureFresh(ctx, '', fake({ shots: ['stale-but-different'], prints: ['p1'] }), null);
  assert.equal(first.ok, true);
  const second = await captureFresh(ctx, '', fake({ shots: ['other-stale'], prints: ['p2'] }), null);
  assert.equal(second.ok, true);
});

test('a renderer that reports no paint is refused without capturing', async () => {
  const wc = fake({ shots: ['x'], prints: ['p'], painted: false });
  const r = await captureFresh({}, '', wc, { isVisible: () => true, isMinimized: () => true, isFocused: () => false });
  assert.equal(r.ok, false); assert.equal(r.frame_painted, false); assert.equal(r.png, undefined); assert.equal(wc.state.shot, 0);
  assert.match(r.reason, /did not paint within 2000 ms/); assert.equal(r.window.minimized, true);
});

test('a renderer that never answers the paint check makes the capture fail within a bound instead of hanging', async () => {
  const started = Date.now();
  await assert.rejects(captureFresh({}, '', fake({ shots: ['x'], prints: ['p'], hangPaint: true }), null), /did not answer within/);
  assert.ok(Date.now() - started < 5000);
});

test('targets are tracked separately so another tab cannot make a capture look stale', async () => {
  const ctx = {};
  await captureFresh(ctx, 'ppa', fake({ shots: ['same'], prints: ['p1'] }), null);
  const r = await captureFresh(ctx, '', fake({ shots: ['same'], prints: ['p2'] }), null);
  assert.equal(r.ok, true); assert.equal(r.identical_to_previous, false);
});

test('the in-page fingerprint script skips password, hidden and secret-like fields', async () => {
  const { JSDOM } = (() => { try { return require('jsdom'); } catch { return {}; } })();
  const src = require('node:fs').readFileSync(require.resolve('../src/control.js'), 'utf8');
  assert.match(src, /e\.type === 'password' \|\| e\.type === 'hidden' \|\| secret\(e\)/);
  assert.match(src, /pass\|otp\|token\|secret\|key\|code\|pin\|ssn\|card/);
  void JSDOM;
});
