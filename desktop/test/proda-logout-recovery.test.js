const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const controller = require('../src/proda-login');
const ROOT = 'https://proda.humanservices.gov.au/';
const LOGOUT = ROOT + 'prodalogin/pages/public/logout.jsf';

function fixture(initial = LOGOUT, enabled = true) {
  const wc = new EventEmitter();
  wc.url = initial; wc.mainFrame = {}; wc.isDestroyed = () => false;
  wc.getURL = () => wc.url; wc.sent = []; wc.loads = [];
  wc.loadURL = async url => { wc.loads.push(url); wc.emit('did-start-navigation', {}, url, false, true); wc.url = url; wc.emit('did-navigate', {}, url); };
  const view = { webContents: wc }, views = { mhr: view }, finishes = [];
  const api = async (_method, route, body) => {
    if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: enabled }] };
    if (route === '/api/auth/proda/start') return { status: 'started', attempt_id: 'synthetic-attempt' };
    if (route === '/api/auth/proda/finish') finishes.push(body);
    return {};
  };
  const ctrl = controller({ api, views, state: { active: 'mhr' }, allowHarness: true, isHarness: () => false });
  ctrl.attachView(view);
  return { wc, ctrl, finishes, views };
}

test('explicit request on exact logout navigates once to canonical PRODA root', async () => {
  const f = fixture();
  assert.equal((await f.ctrl.triggerLogin()).status, 'pending');
  assert.deepEqual(f.wc.loads, [ROOT]);
  f.wc.url = LOGOUT;
  await f.ctrl.onNavigation(LOGOUT);
  assert.deepEqual(f.ctrl.authStatus(), { status: 'needs_user_action', reason: 'manual_fallback' });
  await f.ctrl.triggerLogin();
  assert.deepEqual(f.wc.loads, [ROOT]);
});

test('logout navigation does not relogin without an explicit request', async () => {
  const f = fixture();
  f.ctrl.setStatus('completed');
  await f.ctrl.onNavigation(LOGOUT);
  assert.deepEqual(f.wc.loads, []);
  assert.deepEqual(f.ctrl.authStatus(), { status: 'needs_user_action', reason: 'manual_fallback' });
  const disabled = fixture(LOGOUT, false);
  await disabled.ctrl.triggerLogin();
  assert.deepEqual(disabled.wc.loads, []);
});

test('lookalike origins and unknown paths do not trigger logout recovery', async () => {
  for (const url of ['http://proda.humanservices.gov.au/prodalogin/pages/public/logout.jsf',
    'https://proda.humanservices.gov.au.evil.example/prodalogin/pages/public/logout.jsf',
    'https://user@proda.humanservices.gov.au/prodalogin/pages/public/logout.jsf',
    ROOT + 'prodalogin/pages/public/logout.jsf/other', ROOT + 'unknown']) {
    const f = fixture(url);
    await f.ctrl.triggerLogin();
    assert.deepEqual(f.wc.loads, []);
  }
});

test('existing attempt is cancelled exactly once before recovery', async () => {
  const f = fixture(ROOT + 'login');
  const result = await f.ctrl.beforeSubmit({ sender: f.wc, senderFrame: f.wc.mainFrame });
  assert.equal(result.status, 'started');
  f.wc.url = LOGOUT;
  await f.ctrl.triggerLogin();
  assert.equal(f.ctrl.getActiveAttempt(), null);
  assert.deepEqual(f.finishes, [{ attempt_id: 'synthetic-attempt', outcome: 'cancelled' }]);
  assert.deepEqual(f.wc.loads, [ROOT]);
});

test('a navigation-aborted root load preserves the new login attempt', async () => {
  const f = fixture();
  f.wc.loadURL = async url => {
    f.wc.emit('did-start-navigation', {}, url, false, true);
    f.wc.url = url;
    f.wc.emit('did-navigate', {}, url);
    throw Object.assign(new Error(), { errno: -3 });
  };
  assert.equal((await f.ctrl.triggerLogin()).status, 'pending');
  assert.equal(f.ctrl.authStatus().status, 'pending');
});

test('real load failure falls back and a replaced view is not overwritten', async () => {
  const f = fixture();
  f.wc.loadURL = async () => { throw Object.assign(new Error(), { errno: -105 }); };
  assert.deepEqual(await f.ctrl.triggerLogin(), { status: 'needs_user_action', reason: 'manual_fallback' });

  const replaced = fixture();
  replaced.wc.loadURL = async () => {
    replaced.views.mhr = { webContents: new EventEmitter() };
    replaced.ctrl.setStatus('completed');
    throw Object.assign(new Error(), { errno: -105 });
  };
  assert.equal((await replaced.ctrl.triggerLogin()).status, 'completed');

  const noNavigation = fixture();
  noNavigation.wc.loadURL = async () => { throw Object.assign(new Error(), { errno: -3 }); };
  assert.deepEqual(await noNavigation.ctrl.triggerLogin(), { status: 'needs_user_action', reason: 'manual_fallback' });
});
