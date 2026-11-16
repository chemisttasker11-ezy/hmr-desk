const { test } = require('node:test');
const assert = require('node:assert/strict');
const prodaController = require('../src/proda-login');
const autorun = require('../src/autorun');
const { pageScript, sanitizeAuthResult, redactUrl, createHandler, isPrivateApiRoute } = require('../src/control');
const { loginFields, otpFields: productionOtpFields } = require('../view-preload');
const Module = require('node:module');
const preloadPath = require.resolve('../view-preload');
const syntheticPreloadSource = require('node:fs').readFileSync(preloadPath, 'utf8');
const syntheticPreload = new Module(preloadPath, module);
syntheticPreload._compile(syntheticPreloadSource, preloadPath);
const { otpFields, submitOtp } = syntheticPreload.exports;
const mcp = require('../mcp/hmr-desk-mcp');

function createFakeWebContents(initialUrl = 'https://proda.humanservices.gov.au/login') {
  let currentUrl = initialUrl;
  const sent = [];
  const eventListeners = {};
  const wc = {
    isDestroyed: () => false,
    isLoading: () => false,
    getURL: () => currentUrl,
    loadURL: (u, event = {}) => {
      (eventListeners['did-start-navigation'] || []).forEach((cb) => cb(event, u, false, true));
      currentUrl = u;
      (eventListeners['did-navigate'] || []).forEach((cb) => cb({}, u));
    },
    send: (channel, data) => sent.push({ channel, data }),
    on: (ev, cb) => {
      eventListeners[ev] = eventListeners[ev] || [];
      eventListeners[ev].push(cb);
    },
    executeJavaScript: async (src) => {
      if (typeof src === 'string') {
        if (src.includes('hasSignal')) return true;
        if (src.includes('anchors')) return { clicked: true };
      }
      return true;
    },
    getSent: () => sent,
    redirectTo: (u) => { currentUrl = u; },
    emit: (name, ...args) => (eventListeners[name] || []).forEach(cb => cb({}, ...args)),
    mainFrame: {},
  };
  wc.mainFrame = { framesInSubtree: [wc] };
  return wc;
}

test('1. Production settings toggle defaults to false and parses real engine settings envelope', async () => {
  let settingsResponse = { settings: [{ key: 'proda_auto_sms_login', value: false }] };
  const api = async (_m, p) => {
    if (p === '/api/settings') return settingsResponse;
    if (p === '/api/auth/proda/start') return { status: 'started', attempt_id: 'att-1', started_at: '2026-11-15T00:00:00Z' };
    return {};
  };

  const fakeWc = createFakeWebContents();
  const views = { mhr: { webContents: fakeWc } };
  const state = { active: 'mhr' };

  // Production default: setting is false in engine settings array
  const ctrlDisabled = prodaController({
    api,
    views,
    state,
    allowHarness: true,
  });

  assert.equal(await ctrlDisabled.canAutoSubmit(), false, 'Default false setting must prevent auto-submit');

  const beforeSubmitRes = await ctrlDisabled.beforeSubmit({
    sender: fakeWc,
    senderFrame: fakeWc.mainFrame,
  });
  assert.equal(beforeSubmitRes.status, 'disabled');
  assert.equal(ctrlDisabled.authStatus().status, 'disabled');
  assert.equal(ctrlDisabled.authStatus().reason, 'proda_auto_sms_login_disabled');

  // When setting is enabled in real settings envelope
  settingsResponse = { settings: [{ key: 'other_key', value: 'x' }, { key: 'proda_auto_sms_login', value: true }] };
  const ctrlEnabled = prodaController({
    api,
    views,
    state,
    allowHarness: true,
  });

  assert.equal(await ctrlEnabled.canAutoSubmit(), true, 'Enabled setting allows auto-submit when MHR is active');
  const startRes = await ctrlEnabled.beforeSubmit({
    sender: fakeWc,
    senderFrame: fakeWc.mainFrame,
  });
  assert.equal(startRes.status, 'started');
  assert.equal(ctrlEnabled.authStatus().status, 'pending');

  // Harness disabled behavior
  const ctrlHarness = prodaController({
    api,
    views,
    state,
    isHarness: () => true,
    allowHarness: false,
  });
  assert.equal(await ctrlHarness.canAutoSubmit(), false, 'Harness must disable auto-submit');
  const triggerRes = await ctrlHarness.triggerLogin();
  assert.equal(triggerRes.status, 'unavailable');
  assert.equal(triggerRes.reason, 'harness_disabled');
});

test('2. Exact sender, mainframe and origin validation rejects event/null/frame omissions', () => {
  const mhrWc = createFakeWebContents('https://proda.humanservices.gov.au/login');
  const otherWc = createFakeWebContents('https://proda.humanservices.gov.au/login');
  const views = { mhr: { webContents: mhrWc }, emims: { webContents: otherWc } };

  const ctrl = prodaController({
    api: async () => ({ settings: [{ key: 'proda_auto_sms_login', value: true }] }),
    views,
  });

  // Rejection of null/undefined/missing events
  assert.equal(ctrl.validateSender(null), false, 'null event must be rejected');
  assert.equal(ctrl.validateSender(undefined), false, 'undefined event must be rejected');
  assert.equal(ctrl.validateSender({}), false, 'event without sender must be rejected');
  assert.equal(ctrl.validateSender({ sender: mhrWc }), false, 'event without senderFrame must be rejected');

  // Subframe rejection
  assert.equal(
    ctrl.validateSender({ sender: mhrWc, senderFrame: {} }),
    false,
    'Subframe must be rejected',
  );

  // Other tab rejection
  assert.equal(
    ctrl.validateSender({ sender: otherWc, senderFrame: otherWc.mainFrame }),
    false,
    'Other tab must be rejected',
  );

  // Valid sender
  assert.equal(
    ctrl.validateSender({ sender: mhrWc, senderFrame: mhrWc.mainFrame }),
    true,
    'Owned mhr mainFrame on exact PRODA origin must be accepted',
  );

  // Origin boundaries: credentials and non-default ports
  assert.equal(ctrl.isExactProdaOrigin('https://proda.humanservices.gov.au'), true);
  assert.equal(ctrl.isExactProdaOrigin('https://proda.humanservices.gov.au/login'), true);
  assert.equal(ctrl.isExactProdaOrigin('https://proda.humanservices.gov.au:443/login'), true);
  assert.equal(ctrl.isExactProdaOrigin('https://proda.humanservices.gov.au:8443/login'), false);
  assert.equal(ctrl.isExactProdaOrigin('https://user:pass@proda.humanservices.gov.au/login'), false);
  assert.equal(ctrl.isExactProdaOrigin('http://proda.humanservices.gov.au/'), false);
  assert.equal(ctrl.isExactProdaOrigin('https://login.proda.humanservices.gov.au/'), false);
  assert.equal(ctrl.isExactProdaOrigin('https://proda.humanservices.gov.au.evil.com/'), false);
});

test('3. Bounded password to OTP generation transition and cancellation on reload/replaced challenge', async () => {
  const finishCalls = [];
  const api = async (_m, p, body) => {
    if (p === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (p === '/api/auth/proda/start') return { status: 'started', attempt_id: 'att-transition', started_at: '2026-11-15T09:00:00Z' };
    if (p === '/api/auth/proda/poll') return { status: 'waiting' };
    if (p === '/api/auth/proda/finish') {
      finishCalls.push(body);
      return { status: 'finished' };
    }
    return {};
  };

  const mhrWc = createFakeWebContents('https://proda.humanservices.gov.au/login');
  const views = { mhr: { webContents: mhrWc } };
  const ctrl = prodaController({
    api,
    views,
    state: { active: 'mhr' },
    sleep: async () => {},
    allowHarness: true,
  });

  // Password submitted at generation 0
  const event = { sender: mhrWc, senderFrame: mhrWc.mainFrame };
  await ctrl.beforeSubmit(event);
  assert.equal(ctrl.getActiveAttempt().stage, 'awaiting_otp');
  assert.equal(ctrl.getActiveAttempt().passwordGen, 0);
  assert.equal(ctrl.getActiveAttempt().expectedOtpGen, 1);

  // Legitimate navigation transition from password page to OTP challenge (generation transitions to 1)
  mhrWc.loadURL('https://proda.humanservices.gov.au/otp');
  assert.equal(ctrl.getGeneration(), 1);

  // OTP page detected for this legitimate transition
  const pollPromise = ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
  assert.equal(ctrl.getActiveAttempt().stage, 'polling_otp');
  assert.equal(ctrl.getActiveAttempt().otpGen, 1);

  // Stop polling via manual entry
  ctrl.onOtpManual(event);
  await pollPromise;
  assert.equal(finishCalls.some((c) => c.attempt_id === 'att-transition' && c.outcome === 'cancelled'), true);
  assert.equal(ctrl.getActiveAttempt(), null);

  // Intervening reload test: start new attempt at current generation
  await ctrl.beforeSubmit(event);
  const genBefore = ctrl.getGeneration();
  // Double reload occurs (skipping expected generation)
  ctrl.onNavigation('https://proda.humanservices.gov.au/intermediate');
  ctrl.onNavigation('https://proda.humanservices.gov.au/otp-reloaded');
  assert.ok(ctrl.getGeneration() > genBefore + 1);

  // Replaced / reloaded challenge must be rejected with challenge_mismatch
  await ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
  assert.equal(ctrl.authStatus().status, 'needs_user_action');
  assert.equal(ctrl.authStatus().reason, 'challenge_mismatch');
});

test('landing page permits exactly one page-initiated hop to the verification challenge', async () => {
  const origin = 'https://proda.humanservices.gov.au';
  const services = origin + '/pia/pages/private/myIdentity/myServices.jsf';
  for (const scenario of ['success', 'browser', 'reload', 'other path', 'third navigation', 'password generation', 'query root', 'other target', 'query target', 'hash target']) {
    const calls = [];
    let releasePoll;
    const api = async (method, path, body) => {
      calls.push({ method, path, body });
      if (path === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
      if (path === '/api/auth/proda/start') return { status: 'started', attempt_id: 'landing-attempt' };
      if (path === '/api/auth/proda/poll') return new Promise(resolve => { releasePoll = resolve; });
      return {};
    };
    const wc = createFakeWebContents(scenario === 'password generation' ? origin + '/' : origin + '/prodalogin/pages/public/login.jsf');
    const view = { webContents: wc };
    const ctrl = prodaController({ api, views: { mhr: view }, state: { active: 'mhr' }, sleep: async () => {}, allowHarness: true });
    ctrl.attachView(view);
    const event = { sender: wc, senderFrame: wc.mainFrame };
    await ctrl.beforeSubmit(event);
    if (scenario !== 'password generation') wc.loadURL(scenario === 'other path' ? origin + '/other' : origin + '/');
    const targets = { reload: origin + '/', 'query root': origin + '/?another=1', 'other target': origin + '/other', 'query target': services + '?another=1', 'hash target': services + '#another' };
    wc.loadURL(targets[scenario] || services, scenario === 'browser' ? {} : { initiator: {} });
    if (scenario === 'password generation') {
      assert.equal(ctrl.getGeneration(), 1);
      assert.equal(ctrl.getActiveAttempt().expectedOtpGen, 1);
      wc.loadURL(origin + '/another', { initiator: {} });
    }
    if (scenario === 'third navigation') wc.loadURL(origin + '/another', { initiator: {} });
    if (scenario === 'success') {
      wc.redirectTo(origin + '/mga/sps/authsvc/policy/proda');
      const polling = ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
      await Promise.resolve();
      assert.equal(ctrl.authStatus().status, 'waiting_sms');
      assert.equal(calls.filter(call => call.path === '/api/auth/proda/poll').length, 1);
      assert.equal(calls.filter(call => call.path === '/api/auth/proda/finish').length, 0);
      ctrl.onOtpManual(event);
      releasePoll({ status: 'waiting' });
      await polling;
    } else {
      assert.equal(ctrl.authStatus().status, 'needs_user_action', scenario);
      assert.equal(ctrl.authStatus().reason, 'navigation_cancelled', scenario);
      assert.equal(calls.filter(call => call.path === '/api/auth/proda/poll').length, 0, scenario);
      assert.deepEqual(calls.filter(call => call.path === '/api/auth/proda/finish').map(call => call.body), [{ attempt_id: 'landing-attempt', outcome: 'cancelled' }], scenario);
    }
  }
});

test('4. Deferred start and concurrent beforeSubmit races coalesce cleanly', async () => {
  let startCount = 0;
  const api = async (_m, p) => {
    if (p === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (p === '/api/auth/proda/start') {
      startCount++;
      return { status: 'started', attempt_id: 'att-race', started_at: '2026-11-15T09:00:00Z' };
    }
    return {};
  };

  const mhrWc = createFakeWebContents('https://proda.humanservices.gov.au/login');
  const views = { mhr: { webContents: mhrWc } };
  const ctrl = prodaController({
    api,
    views,
    state: { active: 'mhr' },
    allowHarness: true,
  });

  const event = { sender: mhrWc, senderFrame: mhrWc.mainFrame };
  // Multiple concurrent beforeSubmit calls
  const [res1, res2, res3] = await Promise.all([
    ctrl.beforeSubmit(event),
    ctrl.beforeSubmit(event),
    ctrl.beforeSubmit(event),
  ]);

  assert.equal(startCount, 1, 'Concurrent beforeSubmit calls must coalesce into exactly 1 backend start');
  assert.equal(res1.status, 'started');
  assert.equal(res2.status, 'started');
  assert.equal(res3.status, 'started');
});

test('5. Valid OTP poll executes exactly one code submission and clears code immediately', async () => {
  const pollReplies = [
    { status: 'waiting' },
    { status: 'code', code: '839201' },
  ];
  let pollIdx = 0;
  const finishCalls = [];

  const api = async (_m, p, body) => {
    if (p === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (p === '/api/auth/proda/start') return { status: 'started', attempt_id: 'att-one-sub', started_at: '2026-11-15T09:00:00Z' };
    if (p === '/api/auth/proda/poll') return pollReplies[pollIdx++] || { status: 'waiting' };
    if (p === '/api/auth/proda/finish') {
      finishCalls.push(body);
      return { status: 'finished' };
    }
    return {};
  };

  const mhrWc = createFakeWebContents('https://proda.humanservices.gov.au/login');
  const views = { mhr: { webContents: mhrWc } };
  const ctrl = prodaController({
    api,
    views,
    state: { active: 'mhr' },
    sleep: async () => {},
    allowHarness: true,
  });

  const event = { sender: mhrWc, senderFrame: mhrWc.mainFrame };
  await ctrl.beforeSubmit(event);
  mhrWc.loadURL('https://proda.humanservices.gov.au/otp');

  await ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');

  const fills = mhrWc.getSent().filter((m) => m.channel === 'proda-otp-fill');
  assert.equal(fills.length, 1, 'Must send exactly one proda-otp-fill message');
  assert.equal(fills[0].data.code, '839201');

  assert.equal(finishCalls.length, 0);
  ctrl.onOtpSubmitted(event, '0123456789abcdef0123456789abcdef');
  assert.equal(finishCalls.length, 1);
  assert.equal(finishCalls[0].outcome, 'submitted');
  assert.equal(ctrl.authStatus().status, 'submitted');

  // Triggering again cannot submit a second time
  await ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
  assert.equal(mhrWc.getSent().filter((m) => m.channel === 'proda-otp-fill').length, 1);
});

test('6. Clinical host validation and actual positive DOM readiness requirement', async () => {
  const retryCalls = [];
  const autorunMock = {
    retry: (site) => retryCalls.push(site),
  };

  // URL parser validation: non-default port and credentials rejection
  const ctrl = prodaController({
    api: async () => ({ settings: [{ key: 'proda_auto_sms_login', value: true }] }),
    views: {},
    autorun: () => autorunMock,
  });

  assert.equal(ctrl.isExactClinicalHost('https://provider.ehealth.gov.au/portal/health-record-search'), true);
  assert.equal(ctrl.isExactClinicalHost('https://provider.ehealth.gov.au:443/portal/health-record-search'), true);
  assert.equal(ctrl.isExactClinicalHost('https://provider.ehealth.gov.au:8443/portal/health-record-search'), false);
  assert.equal(ctrl.isExactClinicalHost('https://user:pass@provider.ehealth.gov.au/portal/health-record-search'), false);
  assert.equal(ctrl.isExactClinicalHost('http://provider.ehealth.gov.au/portal/health-record-search'), false);
  assert.equal(ctrl.isExactClinicalHost('https://provider.ehealth.gov.au.evil.com/portal/health-record-search'), false);

  // Navigation alone to clinical host home page does NOT mark completed
  const clinicalWc = createFakeWebContents('https://provider.ehealth.gov.au/home');
  const views = { mhr: { webContents: clinicalWc } };
  const ctrlWithView = prodaController({
    api: async () => ({ settings: [{ key: 'proda_auto_sms_login', value: true }] }),
    views,
    autorun: () => autorunMock,
  });

  await ctrlWithView.onNavigation('https://provider.ehealth.gov.au/home');
  assert.notEqual(ctrlWithView.authStatus().status, 'completed', 'Clinical host without /portal/health-record-search cannot complete');
  assert.equal(retryCalls.length, 0);

  // When reaching /portal/health-record-search with positive DOM signal
  clinicalWc.loadURL('https://provider.ehealth.gov.au/portal/health-record-search');
  await ctrlWithView.onNavigation('https://provider.ehealth.gov.au/portal/health-record-search');

  assert.equal(ctrlWithView.authStatus().status, 'completed');
  assert.deepEqual(retryCalls, ['mhr']);
});

test('7. Service selection script verifies exact URL-parsed HTTPS provider anchor and rejects lookalikes/buttons', async () => {
  const mhrWc = createFakeWebContents('https://proda.humanservices.gov.au/services');
  let injectedScript = null;
  mhrWc.executeJavaScript = async (src) => {
    injectedScript = src;
    return { clicked: true };
  };

  const views = { mhr: { webContents: mhrWc } };
  const ctrl = prodaController({
    api: async () => ({ settings: [{ key: 'proda_auto_sms_login', value: true }] }),
    views,
  });

  ctrl.setStatus('submitted');
  await ctrl.checkServiceSelection(views.mhr);
  assert.ok(injectedScript, 'Service selection script was executed');

  // Verify that the injected script parses URL and restricts to <a>
  assert.ok(injectedScript.includes("document.querySelectorAll('a')"), 'Script must query only anchors');
  assert.ok(injectedScript.includes("targetUrl.hostname !== 'provider.ehealth.gov.au'"), 'Script must strictly verify hostname');
  assert.ok(injectedScript.includes('extraChoice'), 'Terms or org chooser must trigger extraChoice');
});

test('8. Redaction of sensitive URL search/hash/tokens in app_state and error suppression', async () => {
  // Test redactUrl
  const sensitiveProdaUrl = 'https://proda.humanservices.gov.au/login?session=abc12345&code=987654#token=xyz';
  const redactedProda = redactUrl(sensitiveProdaUrl);
  assert.equal(redactedProda, 'https://proda.humanservices.gov.au/');
  assert.equal(redactedProda.includes('987654'), false);
  assert.equal(redactedProda.includes('token'), false);

  const otherSiteUrl = 'https://app.example.com/view?patient=1&token=secret123&code=456789';
  const redactedOther = redactUrl(otherSiteUrl);
  assert.equal(redactedOther.includes('secret123'), false);
  assert.equal(redactedOther.includes('456789'), false);
  assert.equal(redactedOther, 'https://app.example.com/view');

  // Test control server endpoint error suppression for auth
  const ctx = {
    getWindow: () => ({ isDestroyed: () => false }),
    authStatus: async () => {
      throw Error('Sensitive internal database error containing secret code 112233');
    },
    prodaLogin: null,
    views: {},
    oneOffs: {},
    state: {},
  };

  const handler = createHandler(ctx, 'test-token');

  let responseBody = null;
  let responseCode = null;
  const fakeReq = {
    headers: { 'x-hmr-control': 'test-token', 'content-type': 'application/json' },
    method: 'POST',
    url: '/auth/status',
    [Symbol.asyncIterator]: async function* () {
      yield Buffer.from('{}');
    },
  };
  const fakeRes = {
    writeHead: (code) => {
      responseCode = code;
    },
    end: (str) => {
      responseBody = JSON.parse(str);
    },
  };

  await handler(fakeReq, fakeRes);
  assert.equal(responseCode, 200);
  assert.equal(responseBody.status, 'unavailable');
  assert.equal(responseBody.reason, 'unavailable');
  assert.equal(JSON.stringify(responseBody).includes('112233'), false);

  // Test MCP client filtering
  const filtered = mcp.filterAuthStatus({ status: 'waiting_sms', reason: 'not_started', raw_code: '998877' });
  assert.deepEqual(filtered, { status: 'waiting_sms', reason: 'not_started' });
  assert.equal(Object.hasOwn(filtered, 'raw_code'), false);
});

test('9. Preload form submit vs requestSubmit compatibility without trapping manual login', () => {
  // Test loginFields and otpFields
  global.getComputedStyle = () => ({ visibility: 'visible' });
  const input = (type, attrs = {}) => ({
    type,
    ...attrs,
    getClientRects: () => [1],
    getAttribute: (a) => attrs[a] || null,
  });

  const otpInput = input('text', { autocomplete: 'one-time-code', value: '' });
  const button = input('submit', { value: 'Verify' });
  button.hasAttribute = () => false;
  const formWithSubmitInput = {
    action: 'https://proda.humanservices.gov.au/mga/sps/authsvc/policy/proda?StateId=synthetic&operation=verify', method: 'post', target: '_self',
    hasAttribute: () => false, getAttribute: key => key === 'method' ? 'post' : null,
    querySelectorAll: (selector) => selector.startsWith('button') ? [button] : [otpInput],
    querySelector: () => null,
    submit: 'this is an input named submit, not a function', // DOM shadowing bug scenario
  };
  otpInput.form = formWithSubmitInput;
  button.form = formWithSubmitInput;

  const doc = { location: new URL('https://proda.humanservices.gov.au/otp'), querySelectorAll: () => [otpInput] };
  const fields = otpFields(doc);
  assert.ok(fields);
  assert.equal(fields.input, otpInput);

  // Verify generic sign-in check refusal remains intact
  global.document = { querySelectorAll: () => [otpInput] };
  assert.throws(() => eval(pageScript('check')), /sign-in page/);
});

const vm = require('node:vm');
test('clinical readiness requires the actual search controls and rejects navigation races', async () => {
  const url = 'https://provider.ehealth.gov.au/portal/health-record-search';
  const wc = createFakeWebContents(url);
  const view = { webContents: wc }, views = { mhr: view };
  const ctrl = prodaController({ api: async () => ({}), views });
  const ids = new Set(['lname', 'dob', 'identifierval', 'radio-sex-female', 'radio-sex-male', 'radio-identifier-IHI', 'radio-identifier-Medicare', 'search']);
  const window = { location: new URL(url) }; window.top = window;
  const document = { querySelector: () => null, getElementById: id => ids.has(id) ? {} : null };
  wc.executeJavaScript = async script => vm.runInNewContext(script, { window, document });
  assert.equal(await ctrl.verifyClinicalReadiness(view), true);
  ids.delete('search');
  assert.equal(await ctrl.verifyClinicalReadiness(view), false);
  ids.add('search');
  wc.loadURL(url + '-fake');
  assert.equal(await ctrl.verifyClinicalReadiness(view), false);
  wc.loadURL(url);
  let resolve;
  wc.executeJavaScript = () => new Promise(r => { resolve = r; });
  const pending = ctrl.verifyClinicalReadiness(view);
  views.mhr = { webContents: createFakeWebContents(url) };
  resolve(true);
  assert.equal(await pending, false);
});

test('late poll result after manual cancellation never fills a code', async () => {
  let resolvePoll, pollStarted;
  const started = new Promise(r => { pollStarted = r; });
  const api = async (_method, route) => {
    if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (route.endsWith('/start')) return { status: 'started', attempt_id: 'race' };
    if (route.endsWith('/poll')) return new Promise(r => { resolvePoll = r; pollStarted(); });
    return {};
  };
  const wc = createFakeWebContents(), event = { sender: wc, senderFrame: wc.mainFrame };
  const ctrl = prodaController({ api, views: { mhr: { webContents: wc } }, sleep: async () => {}, allowHarness: true });
  await ctrl.beforeSubmit(event);
  wc.loadURL('https://proda.humanservices.gov.au/otp');
  const poll = ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
  await started;
  ctrl.onOtpManual(event);
  resolvePoll({ status: 'code', code: '123456' });
  await poll;
  assert.equal(wc.getSent().length, 0);
  assert.equal(JSON.stringify(ctrl.authStatus()).includes('123456'), false);
});

test('service link script follows only a unique exact provider anchor', async () => {
  const wc = createFakeWebContents('https://proda.humanservices.gov.au/services');
  const view = { webContents: wc };
  const ctrl = prodaController({ api: async () => ({}), views: { mhr: view } });
  ctrl.setStatus('submitted');
  const window = { location: new URL(wc.getURL()) }; window.top = window;
  let clicked = 0;
  const anchor = href => ({ href, textContent: 'My Health Record', getClientRects: () => [1], click: () => clicked++ });
  let links = [anchor('https://provider.ehealth.gov.au.evil.example/')];
  const document = { querySelectorAll: selector => selector === 'a' ? links : [] };
  wc.executeJavaScript = async script => vm.runInNewContext(script, { window, document, URL, getComputedStyle: () => ({ visibility: 'visible', display: 'block' }) });
  await ctrl.checkServiceSelection(view);
  assert.equal(clicked, 0);
  links = [anchor('https://provider.ehealth.gov.au/portal/health-record-search'), anchor('https://provider.ehealth.gov.au/portal/health-record-search')];
  await ctrl.checkServiceSelection(view);
  assert.equal(clicked, 0);
  ctrl.setStatus('submitted');
  links = [anchor('https://provider.ehealth.gov.au/portal/health-record-search')];
  await ctrl.checkServiceSelection(view);
  assert.equal(clicked, 1);
});

test('JSF services link requires exact text, postback and no other choices', async () => {
  const services = 'https://proda.humanservices.gov.au/pia/pages/private/myIdentity/myServices.jsf';
  for (const scenario of ['valid', 'text', 'path', 'origin', 'method', 'duplicate', 'radio', 'checkbox', 'select', 'page', 'status']) {
    const url = scenario === 'page' ? 'https://proda.humanservices.gov.au/other' : services;
    const wc = createFakeWebContents(url), view = { webContents: wc };
    const ctrl = prodaController({ api: async () => ({}), views: { mhr: view } });
    if (scenario !== 'status') ctrl.setStatus('submitted');
    const window = { location: new URL(url) }; window.top = window;
    let clicked = 0, result, calls = 0;
    const form = { method: scenario === 'method' ? 'get' : 'post', action: scenario === 'path' ? '/other' : scenario === 'origin' ? 'https://example.com/other' : services };
    const anchor = () => ({ href: '#', textContent: scenario === 'text' ? 'My Health Record help' : 'My Health Record', closest: () => form, getClientRects: () => [1], click: () => clicked++ });
    const links = scenario === 'duplicate' ? [anchor(), anchor()] : [anchor()];
    const choice = { getClientRects: () => [1] };
    const document = { querySelectorAll: selector => selector === 'a' ? links : (scenario === 'radio' && selector === 'input[type=radio]' || scenario === 'checkbox' && selector === 'input[type=checkbox]' || scenario === 'select' && selector === 'select, [role=listbox]') ? [choice] : [] };
    wc.executeJavaScript = async script => { calls++; result = vm.runInNewContext(script, { window, document, URL, getComputedStyle: () => ({ visibility: 'visible', display: 'block' }) }); return result; };
    await ctrl.checkServiceSelection(view);
    assert.equal(clicked, scenario === 'valid' ? 1 : 0, scenario);
    if (scenario === 'status') assert.equal(calls, 0);
    else if (['duplicate', 'radio', 'checkbox', 'select'].includes(scenario)) assert.equal(result.extraChoice, true, scenario);
    else if (scenario !== 'valid') assert.equal(result.none, true, scenario);
  }
});

test('clinical landing selects only one safe option and retries an initially disabled Next', async () => {
  const landing = 'https://provider.ehealth.gov.au/portal/landing-page';
  for (const scenario of ['valid', 'checked', 'two', 'checkbox', 'text', 'cancel', 'path', 'origin', 'status', 'retry']) {
    const url = scenario === 'path' ? landing + '/other' : scenario === 'origin' ? 'https://example.com/portal/landing-page' : landing;
    const wc = createFakeWebContents(url), view = { webContents: wc }, notifications = [];
    let radioClicks = 0, nextClicks = 0, calls = 0, sleeps = 0;
    const form = {};
    const radio = { form, checked: scenario === 'checked', getClientRects: () => [1], click() { radioClicks++; this.checked = true; } };
    const submit = { form, tagName: 'BUTTON', textContent: scenario === 'cancel' ? 'Cancel' : 'Next', disabled: scenario === 'retry', getClientRects: () => [1], click: () => nextClicks++ };
    form.querySelectorAll = () => [submit];
    const ctrl = prodaController({ api: async () => ({}), views: { mhr: view }, notify: (...args) => notifications.push(args), sleep: async ms => { assert.equal(ms, 1500); sleeps++; submit.disabled = false; } });
    if (scenario !== 'status') ctrl.setStatus('submitted');
    const window = { location: new URL(url) }; window.top = window;
    const document = { querySelectorAll: selector => selector === 'input[type=radio]' ? (scenario === 'two' ? [radio, { ...radio }] : [radio]) : ['checkbox', 'text'].includes(scenario) ? [{ getClientRects: () => [1] }] : [] };
    wc.executeJavaScript = async script => { calls++; return vm.runInNewContext(script, { window, document, getComputedStyle: () => ({ visibility: 'visible', display: 'block' }) }); };
    await ctrl.checkClinicalLanding(view);
    await ctrl.checkClinicalLanding(view);
    const success = ['valid', 'checked', 'retry'].includes(scenario);
    assert.equal(nextClicks, success ? 1 : 0, scenario);
    assert.equal(radioClicks, success && scenario !== 'checked' ? 1 : 0, scenario);
    if (['two', 'checkbox', 'text', 'cancel'].includes(scenario)) {
      assert.equal(ctrl.authStatus().reason, 'service_selection_needed', scenario);
      assert.equal(notifications.length, 1, scenario);
    }
    if (['path', 'origin', 'status'].includes(scenario)) assert.equal(calls, 0, scenario);
    if (scenario === 'retry') { assert.equal(calls, 2); assert.equal(sleeps, 1); }
  }
});

test('follow-on clicks happen once per login attempt and stop when the attempt expires', async () => {
  const origin = 'https://proda.humanservices.gov.au', services = origin + '/pia/pages/private/myIdentity/myServices.jsf';
  const landing = 'https://provider.ehealth.gov.au/portal/landing-page', nonce = '0123456789abcdef0123456789abcdef';
  for (const scenario of ['same page twice', 'pages return', 'expired']) {
    let time = 0, linkClicks = 0, nextClicks = 0, window, document;
    const api = async (method, path) => path === '/api/settings' ? { settings: [{ key: 'proda_auto_sms_login', value: true }] }
      : path === '/api/auth/proda/start' ? { status: 'started', attempt_id: 'follow-on' } : path === '/api/auth/proda/poll' ? { status: 'code', code: '123456' } : {};
    const wc = createFakeWebContents(origin + '/prodalogin/pages/public/login.jsf'), view = { webContents: wc };
    const ctrl = prodaController({ api, views: { mhr: view }, state: { active: 'mhr' }, sleep: async () => {}, now: () => time, allowHarness: true });
    ctrl.attachView(view);
    const event = { sender: wc, senderFrame: wc.mainFrame };
    await ctrl.beforeSubmit(event);
    wc.loadURL(origin + '/');
    wc.loadURL(services, { initiator: {} });
    wc.redirectTo(origin + '/mga/sps/authsvc/policy/proda');
    await ctrl.onOtpPage(true, event, nonce);
    ctrl.onOtpSubmitted(event, nonce);
    assert.equal(ctrl.authStatus().status, 'submitted', scenario);
    const open = url => { window = { location: new URL(url) }; window.top = window; };
    const form = { method: 'post', action: services }, landingForm = {};
    const radio = { form: landingForm, checked: false, getClientRects: () => [1], click() { this.checked = true; } };
    landingForm.querySelectorAll = () => [{ form: landingForm, tagName: 'BUTTON', textContent: 'Next', disabled: false, getClientRects: () => [1], click: () => nextClicks++ }];
    const servicesPage = { querySelectorAll: selector => selector === 'a' ? [{ href: '#', textContent: 'My Health Record', closest: () => form, getClientRects: () => [1], click: () => linkClicks++ }] : [] };
    const landingPage = { querySelectorAll: selector => selector === 'input[type=radio]' ? [radio] : [] };
    wc.executeJavaScript = async script => vm.runInNewContext(script, { window, document, URL, getComputedStyle: () => ({ visibility: 'visible', display: 'block' }) });
    if (scenario === 'expired') time = 300000;
    wc.redirectTo(services); open(services); document = servicesPage;
    await Promise.all([ctrl.checkServiceSelection(view), ctrl.checkServiceSelection(view)]);
    if (scenario === 'pages return') { open(services); await ctrl.checkServiceSelection(view); }
    wc.loadURL(landing); open(landing); document = landingPage;
    await ctrl.checkClinicalLanding(view);
    if (scenario === 'pages return') { wc.loadURL(landing); open(landing); await ctrl.checkClinicalLanding(view); }
    assert.equal(linkClicks, scenario === 'expired' ? 0 : 1, scenario);
    assert.equal(nextClicks, scenario === 'expired' ? 0 : 1, scenario);
    assert.equal(ctrl.authStatus().status, 'submitted', scenario);
  }
});

test('deferred start is cancelled when the owned view or main frame changes', async () => {
  for (const replace of ['view', 'frame']) {
    let release, started;
    const waiting = new Promise(r => { started = r; });
    const finishes = [];
    const api = async (_method, route, body) => {
      if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
      if (route.endsWith('/start')) return new Promise(r => { release = r; started(); });
      if (route.endsWith('/finish')) finishes.push(body);
      return {};
    };
    const wc = createFakeWebContents(), views = { mhr: { webContents: wc } };
    const ctrl = prodaController({ api, views, allowHarness: true });
    const pending = ctrl.beforeSubmit({ sender: wc, senderFrame: wc.mainFrame });
    await waiting;
    if (replace === 'view') views.mhr = { webContents: createFakeWebContents() };
    else wc.mainFrame = {};
    release({ status: 'started', attempt_id: 'deferred' });
    assert.equal((await pending).ok, false);
    assert.equal(ctrl.getActiveAttempt(), null);
    assert.deepEqual(finishes, [{ attempt_id: 'deferred', outcome: 'cancelled' }]);
  }
});

test('new navigation and an OTP field replacement cancel a pending poll', async () => {
  for (const change of ['navigation', 'challenge']) {
    let release, started;
    const waiting = new Promise(r => { started = r; });
    const finishes = [];
    const api = async (_method, route, body) => {
      if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
      if (route.endsWith('/start')) return { status: 'started', attempt_id: 'race' };
      if (route.endsWith('/poll')) return new Promise(r => { release = r; started(); });
      if (route.endsWith('/finish')) finishes.push(body);
      return {};
    };
    const wc = createFakeWebContents(), views = { mhr: { webContents: wc } };
    const ctrl = prodaController({ api, views, sleep: async () => {}, allowHarness: true });
    const event = { sender: wc, senderFrame: wc.mainFrame };
    await ctrl.beforeSubmit(event);
    wc.loadURL('https://proda.humanservices.gov.au/otp');
    const poll = ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
    await waiting;
    if (change === 'navigation') wc.emit('did-start-navigation', 'https://proda.humanservices.gov.au/otp', false, true);
    else await ctrl.onOtpPage(true, event, 'abcdef0123456789abcdef0123456789');
    release({ status: 'code', code: '123456' });
    await poll;
    assert.equal(wc.getSent().length, 0);
    assert.equal(ctrl.getActiveAttempt(), null);
    assert.ok(finishes.some(item => item.outcome === 'cancelled'));
  }
});

test('a delayed code past the deadline is not delivered', async () => {
  let time = 0, release, started;
  const waiting = new Promise(r => { started = r; });
  const finishes = [];
  const api = async (_method, route, body) => {
    if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (route.endsWith('/start')) return { status: 'started', attempt_id: 'ttl' };
    if (route.endsWith('/poll')) return new Promise(r => { release = r; started(); });
    if (route.endsWith('/finish')) finishes.push(body);
    return {};
  };
  const wc = createFakeWebContents(), event = { sender: wc, senderFrame: wc.mainFrame };
  const ctrl = prodaController({ api, views: { mhr: { webContents: wc } }, now: () => time, sleep: async () => {}, allowHarness: true });
  await ctrl.beforeSubmit(event);
  wc.loadURL('https://proda.humanservices.gov.au/otp');
  const poll = ctrl.onOtpPage(true, event, '0123456789abcdef0123456789abcdef');
  await waiting;
  time = 300001;
  release({ status: 'code', code: '123456' });
  await poll;
  assert.equal(wc.getSent().length, 0);
  assert.equal(ctrl.authStatus().reason, 'expired');
  assert.ok(finishes.some(item => item.outcome === 'failed'));
});


test('renderer API bridge rejects private auth endpoints including encoded paths', () => {
  assert.equal(isPrivateApiRoute('/api/auth/proda/poll'), true);
  assert.equal(isPrivateApiRoute('/api/%61uth/proda/start?code=123456'), true);
  assert.equal(isPrivateApiRoute('/api/auth/proda/finish'), true);
  assert.equal(isPrivateApiRoute('/api/settings'), false);
  assert.equal(isPrivateApiRoute(null), true);
});

test('verified readiness retries immediately when an earlier autorun attempt is still in flight', async () => {
  let rejectFirst, startedFirst, onStarted;
  const firstStarted = new Promise(resolve => { startedFirst = resolve; });
  const resumed = new Promise(resolve => { onStarted = resolve; });
  let checks = 0;
  const wc = {
    isLoading: () => false,
    executeJavaScript: () => {
      checks++;
      if (checks === 1) return new Promise((_resolve, reject) => { rejectFirst = reject; startedFirst(); });
      return Promise.resolve(true);
    },
  };
  const run = autorun({
    api: async () => ({ tasks: [{ state: 'waiting', waiting_for: 'mhr' }] }),
    armed: {}, waitingTasks: { mhr: [{}] }, ensureView: () => ({ webContents: wc }),
    arm: async () => 'Ready', pageScript: () => 'check', now: () => 1000,
    notify: (_type, value) => { if (value.status === 'Started in the background') onStarted(); },
  });
  const first = run.tick();
  await firstStarted;
  await run.retry('mhr');
  rejectFirst(Error('sign-in page'));
  await first;
  let timer;
  try {
    await Promise.race([resumed, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(Error('retry did not resume')), 1000); })]);
  } finally { clearTimeout(timer); }
  assert.ok(checks >= 3);
});

test('a new password form in the same document cancels an old challenge', async () => {
  const handlers = {}, finishes = [];
  const ipcMain = { handle: (name, fn) => { handlers[name] = fn; }, on: (name, fn) => { handlers[name] = fn; } };
  const api = async (_method, route, body) => {
    if (route === '/api/settings') return { settings: [{ key: 'proda_auto_sms_login', value: true }] };
    if (route.endsWith('/start')) return { status: 'started', attempt_id: 'old' };
    if (route.endsWith('/finish')) finishes.push(body);
    return {};
  };
  const wc = createFakeWebContents(), event = { sender: wc, senderFrame: wc.mainFrame };
  const ctrl = prodaController({ api, ipcMain, views: { mhr: { webContents: wc } }, allowHarness: true });
  await ctrl.beforeSubmit(event);
  handlers['proda-password-page'](event);
  assert.equal(ctrl.getActiveAttempt(), null);
  assert.ok(finishes.some(item => item.outcome === 'cancelled'));
});

test('control auth responses discard unexpected fields even from callbacks', async () => {
  const ctx = { getWindow: () => ({ isDestroyed: () => false }), authStatus: () => ({ status: 'waiting_sms', reason: 'not_started', code: '123456', detail: 'secret' }) };
  const req = { headers: { 'x-hmr-control': 'token', 'content-type': 'application/json' }, method: 'POST', url: '/auth/status', [Symbol.asyncIterator]: async function* () { yield Buffer.from('{}'); } };
  let result;
  await createHandler(ctx, 'token')(req, { writeHead: () => {}, end: body => { result = JSON.parse(body); } });
  assert.deepEqual(result, { status: 'waiting_sms', reason: 'not_started' });
});

function verificationFixture({ label = 'Verify', action = '/mga/sps/authsvc/policy/proda?StateId=synthetic&operation=verify', method = 'post', mode = 'accepted', initial = '' } = {}) {
  class Input {
    get value() { return this._value || ''; }
    set value(v) { this._value = v; }
    getClientRects() { return [1]; }
    getAttribute(name) { return this.attrs?.[name] ?? null; }
    dispatchEvent() { return true; }
    addEventListener() {}
  }
  const input = new Input();
  Object.assign(input, { type: 'text', autocomplete: 'one-time-code', value: initial, attrs: {} });
  const button = { type: 'submit', textContent: label, value: '', attrs: {}, getClientRects: () => [1], hasAttribute(name) { return Object.hasOwn(this.attrs, name); }, getAttribute(name) { return this.attrs[name] ?? null; } };
  const listeners = new Set();
  let calls = 0;
  const form = {
    action: new URL(action, 'https://proda.humanservices.gov.au/otp').href, method, target: '_self', hasAttribute: key => key === 'action' || key === 'method',
    getAttribute: key => ({ action, method })[key] ?? null,
    querySelectorAll: selector => selector.startsWith('button') ? [button] : [],
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    requestSubmit(submitter) {
      calls++;
      if (mode === 'invalid') return; // native validation emitted no submit
      const event = { target: form, submitter, defaultPrevented: false };
      for (const listener of listeners) listener(event);
      if (mode === 'cancelled') event.defaultPrevented = true;
    },
  };
  input.form = button.form = form;
  const doc = { location: new URL('https://proda.humanservices.gov.au/otp'), querySelectorAll: () => [input], querySelector: () => null };
  return { doc, input, button, form, Input, calls: () => calls };
}

test('verification detector rejects resend, unsafe actions and ambiguous controls', () => {
  global.getComputedStyle = () => ({ visibility: 'visible' });
  for (const options of [{ label: 'Resend code' }, { label: 'Refresh code' }, { label: 'Continue', action: '/otp' }, { label: 'Next', action: '/otp' }, { label: 'Verify', action: '/send-code' }, { label: 'Verify', action: '/issue-new-code' }, { label: 'Continue', action: '/otp/resend' }, { action: 'https://evil.example/otp' }, { method: 'get' }]) {
    const fixture = verificationFixture(options);
    assert.equal(otpFields(fixture.doc), null);
    assert.equal(fixture.calls(), 0);
  }
  const fixture = verificationFixture();
  assert.ok(otpFields(fixture.doc));
  assert.ok(productionOtpFields(fixture.doc));
});

test('labelled password verification field is never a login and accepts a disabled Next', () => {
  const previous = global.getComputedStyle;
  global.getComputedStyle = () => ({ visibility: 'visible' });
  try {
    const fixture = verificationFixture({ label: 'Next' });
    Object.assign(fixture.input, { type: 'password', autocomplete: '', name: '', id: '', labels: [{ textContent: 'Verification code' }] });
    fixture.button.disabled = true;
    const show = { type: 'button', textContent: 'Show password' };
    fixture.form.querySelectorAll = selector => selector.startsWith('button') ? [fixture.button] : selector === 'input' ? [fixture.input] : [];
    fixture.doc.querySelectorAll = selector => selector === 'input' ? [fixture.input] : [show, fixture.button];
    assert.equal(loginFields(fixture.doc), null);
    const otp = otpFields(fixture.doc);
    assert.equal(otp.input, fixture.input);
    assert.equal(otp.submitBtn, fixture.button);
  } finally { global.getComputedStyle = previous; }
});

test('login detector rejects strict verification hints but accepts ordinary placeholders', () => {
  const previous = global.getComputedStyle;
  global.getComputedStyle = () => ({ visibility: 'visible' });
  try {
    const username = { type: 'text', placeholder: 'Username', getClientRects: () => [1], getAttribute: () => null };
    const password = { type: 'password', placeholder: 'Password', getClientRects: () => [1], getAttribute: () => null };
    const form = { querySelectorAll: () => [username, password] };
    password.form = form;
    const doc = { querySelectorAll: () => [username, password] };
    assert.deepEqual(loginFields(doc), { username, password, form });
    password.placeholder = 'Verification code';
    assert.equal(loginFields(doc), null);
    password.placeholder = '';
    password.getAttribute = key => key === 'aria-label' ? 'Verification code' : null;
    assert.equal(loginFields(doc), null);
  } finally { global.getComputedStyle = previous; }
});

test('OTP submission stops if the user types while Next is disabled', async () => {
  const priorStyle = global.getComputedStyle, priorInput = global.HTMLInputElement;
  global.getComputedStyle = () => ({ visibility: 'visible' });
  const fixture = verificationFixture({ label: 'Next' });
  global.HTMLInputElement = fixture.Input;
  fixture.button.disabled = true;
  try {
    const otp = otpFields(fixture.doc);
    const submission = submitOtp(fixture.doc, otp, '123456', () => true);
    assert.equal(fixture.input.value, '123456');
    fixture.input.value = '654321';
    assert.equal(await submission, false);
    assert.equal(fixture.calls(), 0);
  } finally { global.getComputedStyle = priorStyle; global.HTMLInputElement = priorInput; }
});

test('OTP submission never overwrites populated fields and acknowledges only accepted submit events', async () => {
  global.getComputedStyle = () => ({ visibility: 'visible' });
  const previous = global.HTMLInputElement;
  try {
    for (const [mode, accepted] of [['accepted', true], ['invalid', null], ['cancelled', null]]) {
      const fixture = verificationFixture({ mode });
      global.HTMLInputElement = fixture.Input;
      const otp = otpFields(fixture.doc);
      assert.equal(await submitOtp(fixture.doc, otp, '123456', () => true), accepted);
      assert.equal(fixture.calls(), 1);
    }
    const populated = verificationFixture({ initial: '654321' });
    global.HTMLInputElement = populated.Input;
    assert.equal(await submitOtp(populated.doc, otpFields(populated.doc), '123456', () => true), false);
    assert.equal(populated.input.value, '654321');
    assert.equal(populated.calls(), 0);
  } finally { global.HTMLInputElement = previous; }
});

test('preload reports populated OTP as manual and refuses browser autofill before code delivery', async () => {
  const fs = require('node:fs');
  const source = syntheticPreloadSource;
  for (const initial of ['654321', '']) {
    const fixture = verificationFixture({ initial });
    const messages = [], handlers = {}, window = {};
    window.top = window;
    window.addEventListener = (name, fn) => { if (name === 'DOMContentLoaded') handlers.ready = fn; };
    const ipcRenderer = { on: (name, fn) => { handlers[name] = fn; }, send: (...args) => messages.push(args), invoke: async () => ({}) };
    const context = { module: { exports: {} }, process: { type: 'renderer' }, require: name => { if (name === 'electron') return { ipcRenderer, contextBridge: { exposeInMainWorld() {} } }; throw Error('unexpected module'); },
      window, document: fixture.doc, location: fixture.doc.location, URL, HTMLInputElement: fixture.Input, Event,
      getComputedStyle: () => ({ visibility: 'visible' }), crypto: { randomUUID: () => '0123456789abcdef0123456789abcdef' },
      MutationObserver: class { observe() {} }, setTimeout, clearTimeout };
    vm.runInNewContext(source, context);
    handlers.ready();
    if (initial) {
      assert.ok(messages.some(x => x[0] === 'proda-otp-manual'));
      assert.ok(messages.some(x => x[0] === 'proda-otp-page' && x[1] === false));
    } else {
      fixture.input.value = '654321'; // browser autofill may not emit an input event
      await handlers['proda-otp-fill']({}, { code: '123456', nonce: '0123456789abcdef0123456789abcdef' });
      assert.equal(fixture.input.value, '654321');
      assert.ok(messages.some(x => x[0] === 'proda-otp-rejected'));
      assert.equal(fixture.calls(), 0);
    }
    assert.equal(JSON.stringify(messages).includes('654321'), false);
  }
});

test('preload only acknowledges an observed uncancelled verification submit', async () => {
  const fs = require('node:fs');
  const source = syntheticPreloadSource;
  for (const mode of ['accepted', 'invalid', 'cancelled']) {
    const fixture = verificationFixture({ mode }), messages = [], handlers = {}, window = {};
    window.top = window;
    window.addEventListener = (name, fn) => { if (name === 'DOMContentLoaded') handlers.ready = fn; };
    const ipcRenderer = { on: (name, fn) => { handlers[name] = fn; }, send: (...args) => messages.push(args), invoke: async () => ({}) };
    const context = { module: { exports: {} }, process: { type: 'renderer' }, require: name => { if (name === 'electron') return { ipcRenderer, contextBridge: { exposeInMainWorld() {} } }; throw Error('unexpected module'); },
      window, document: fixture.doc, location: fixture.doc.location, URL, HTMLInputElement: fixture.Input, Event,
      getComputedStyle: () => ({ visibility: 'visible' }), crypto: { randomUUID: () => '0123456789abcdef0123456789abcdef' },
      MutationObserver: class { observe() {} }, setTimeout, clearTimeout };
    vm.runInNewContext(source, context);
    handlers.ready();
    await handlers['proda-otp-fill']({}, { code: '936281', nonce: '0123456789abcdef0123456789abcdef' });
    assert.equal(messages.some(x => x[0] === 'proda-otp-submitted'), mode === 'accepted');
    assert.equal(messages.some(x => x[0] === 'proda-otp-rejected'), false);
    assert.equal(fixture.calls(), 1);
    assert.equal(JSON.stringify(messages).includes('936281'), false);
  }
});

test('production preload falls back when the verification action is unverified', () => {
  const fs = require('node:fs');
  const source = fs.readFileSync(require.resolve('../view-preload'), 'utf8');
  const fixture = verificationFixture({ label: 'Verify', action: '/otp' }), messages = [], handlers = {}, window = {};
  window.top = window;
  window.addEventListener = (name, fn) => { if (name === 'DOMContentLoaded') handlers.ready = fn; };
  const ipcRenderer = { on: (name, fn) => { handlers[name] = fn; }, send: (...args) => messages.push(args), invoke: async () => ({}) };
  const context = { module: { exports: {} }, process: { type: 'renderer' }, require: name => { if (name === 'electron') return { ipcRenderer, contextBridge: { exposeInMainWorld() {} } }; throw Error('unexpected module'); },
    window, document: fixture.doc, location: fixture.doc.location, URL, HTMLInputElement: fixture.Input, Event,
    getComputedStyle: () => ({ visibility: 'visible' }), crypto: { randomUUID: () => '0123456789abcdef0123456789abcdef' },
    MutationObserver: class { observe() {} }, setTimeout, clearTimeout };
  vm.runInNewContext(source, context);
  handlers.ready();
  assert.ok(messages.some(x => x[0] === 'proda-otp-manual'));
  handlers['proda-otp-fill']({}, { code: '123456', nonce: '0123456789abcdef0123456789abcdef' });
  assert.equal(fixture.calls(), 0);
  assert.equal(messages.some(x => x[0] === 'proda-otp-submitted'), false);
});

test('saved PRODA login uses only a uniquely safe named submitter', async () => {
  const vm = require('node:vm');
  const source = require('node:fs').readFileSync(preloadPath, 'utf8');
  async function run({ extra = false, action = '/login', method = 'post', target = '_self', label = 'Sign in', base = 'https://proda.humanservices.gov.au/', baseTarget = '', overrides = {} } = {}) {
    const listeners = {};
    class Input {
      constructor(type) { this.type = type; this.disabled = false; this.autocomplete = ''; this.name = ''; this.id = ''; }
      getClientRects() { return [1]; }
      dispatchEvent() {}
      set value(v) { this._value = v; }
      get value() { return this._value || ''; }
    }
    const username = new Input('text'), password = new Input('password');
    const button = { tagName: 'INPUT', type: 'submit', value: label, name: 'loginAction', disabled: false,
      getClientRects: () => [1], hasAttribute: key => Object.hasOwn(overrides, key), getAttribute: key => overrides[key] ?? null,
      get formAction() { return new URL(overrides.formaction || 'https://proda.humanservices.gov.au/login', base).href; },
      get formMethod() { return ['post', 'get'].includes((overrides.formmethod || '').toLowerCase()) ? overrides.formmethod.toLowerCase() : 'get'; },
      get formTarget() { return overrides.formtarget || ''; } };
    let submitted;
    const form = { action: new URL(action, base).href, method, target, hasAttribute: key => key === 'action', getAttribute: key => key === 'action' ? action : null, requestSubmit: b => { submitted = b; },
      querySelectorAll: selector => selector === 'input' ? [username, password] : (extra ? [button, { ...button }] : [button]) };
    button.form = form;
    username.form = password.form = form;
    const location = new URL('https://proda.humanservices.gov.au/login');
    const document = { location, querySelector: selector => selector === 'base[target]' && baseTarget ? { target: baseTarget } : null,
      querySelectorAll: selector => selector === 'input' ? [username, password] : [] };
    const window = { addEventListener() {} }; window.top = window;
    const ipc = { on: (name, fn) => { listeners[name] = fn; }, invoke: async () => ({}), send() {} };
    const context = { process: { type: 'renderer' }, require: name => name === 'electron' ? { ipcRenderer: ipc, contextBridge: { exposeInMainWorld() {} } } : require(name),
      module: { exports: {} }, window, document, location, URL, HTMLInputElement: Input,
      getComputedStyle: () => ({ visibility: 'visible' }), Event: class {}, setTimeout, clearTimeout };
    vm.runInNewContext(source, context);
    await listeners['sign-in-fill']({}, { origin: location.origin, username: 'synthetic-user', password: 'synthetic-password', submit: true });
    return { submitted, button, username, password };
  }
  const safe = await run();
  assert.equal(safe.submitted, safe.button);
  assert.equal(safe.submitted.name, 'loginAction');
  for (const scenario of [{ extra: true }, { action: 'https://evil.example/login' }, { base: 'https://evil.example/' },
    { overrides: { formaction: 'https://evil.example/login' } }, { overrides: { formaction: '' } }, { overrides: { formmethod: '' } },
    { overrides: { formtarget: '' } }, { method: 'get' }, { target: '_blank' }, { target: '', baseTarget: '_blank' }, { label: 'Back' }]) {
    const blocked = await run(scenario);
    assert.equal(blocked.submitted, undefined);
    assert.equal(blocked.username.value, 'synthetic-user');
    assert.equal(blocked.password.value, 'synthetic-password');
  }
  const selfBase = await run({ target: '', baseTarget: '_self' });
  assert.equal(selfBase.submitted, selfBase.button);
});

test('observed password OTP contract waits for enable and refuses changed or unsafe challenges', async () => {
  const { otpFields: detect, submitOtp: submit } = require('../view-preload');
  const priorStyle = global.getComputedStyle, priorInput = global.HTMLInputElement;
  global.getComputedStyle = () => ({ visibility: 'visible' });
  class Input {
    constructor() { this.type = 'password'; this.autocomplete = 'one-time-code'; this.name = ''; this.id = ''; this._value = ''; }
    get value() { return this._value; }
    set value(v) { this._value = v; }
    getClientRects() { return [1]; }
    getAttribute() { return null; }
    dispatchEvent() { return true; }
  }
  global.HTMLInputElement = Input;
  function fixture() {
    const input = new Input();
    const button = { tagName: 'BUTTON', type: 'submit', textContent: 'Next', value: '', name: '', id: '', disabled: true,
      getClientRects: () => [1], hasAttribute: () => false, getAttribute: () => null };
    const listeners = new Set(); let count = 0;
    const attrs = { action: '/mga/sps/authsvc/policy/proda?StateId=synthetic&operation=verify' };
    const form = { method: 'post', target: '_self', hasAttribute: key => key in attrs, getAttribute: key => attrs[key] ?? null,
      get action() { return new URL(attrs.action, 'https://proda.humanservices.gov.au').href; },
      querySelectorAll: selector => selector.startsWith('button') ? [button] : [],
      addEventListener: (_event, fn) => listeners.add(fn), removeEventListener: (_event, fn) => listeners.delete(fn),
      requestSubmit(submitter) { count++; const event = { target: form, submitter, defaultPrevented: false }; for (const fn of listeners) fn(event); if (form.cancel) event.defaultPrevented = true; } };
    input.form = button.form = form;
    const doc = { location: new URL('https://proda.humanservices.gov.au/otp'), querySelectorAll: () => [input], querySelector: () => null };
    return { input, button, form, doc, attrs, calls: () => count };
  }
  try {
    let f = fixture(); let otp = detect(f.doc); assert.ok(otp);
    setTimeout(() => { f.button.disabled = false; }, 10);
    assert.equal(await submit(f.doc, otp, '123456', () => true), true);
    assert.equal(f.calls(), 1);
    for (const action of ['/mga/sps/authsvc/policy/proda?StateId=x&StateId=y&operation=verify', '/mga/sps/authsvc/policy/proda?StateId=x&operation=resend', 'https://evil.example/mga/sps/authsvc/policy/proda?StateId=x&operation=verify']) {
      f = fixture(); f.attrs.action = action; assert.equal(detect(f.doc), null);
    }
    f = fixture(); f.doc.querySelector = () => ({ target: '_blank' }); f.form.target = ''; assert.equal(detect(f.doc), null);
    f = fixture(); const extraPassword = new Input(); extraPassword.autocomplete = ''; f.doc.querySelectorAll = () => [f.input, extraPassword]; assert.equal(detect(f.doc), null);
    f = fixture(); const username = new Input(); username.type = 'text'; username.autocomplete = 'username'; f.doc.querySelectorAll = () => [f.input, username]; assert.equal(detect(f.doc), null);
    f = fixture(); f.button.hasAttribute = key => key === 'formaction'; f.button.getAttribute = () => '/mga/sps/authsvc/policy/proda?StateId=x&operation=verify';
    f.button.formAction = 'https://evil.example/mga/sps/authsvc/policy/proda?StateId=x&operation=verify'; assert.equal(detect(f.doc), null);
    f = fixture(); otp = detect(f.doc); setTimeout(() => { f.attrs.action += '&extra=1'; f.button.disabled = false; }, 10);
    assert.equal(await submit(f.doc, otp, '123456', () => true), false); assert.equal(f.calls(), 0);
    f = fixture(); otp = detect(f.doc); let current = true; setTimeout(() => { current = false; f.button.disabled = false; }, 10);
    assert.equal(await submit(f.doc, otp, '123456', () => current), false); assert.equal(f.calls(), 0);
    f = fixture(); f.button.disabled = false; f.form.cancel = true; otp = detect(f.doc);
    assert.equal(await submit(f.doc, otp, '123456', () => true), null);
    f = fixture(); otp = detect(f.doc); assert.equal(await submit(f.doc, otp, '123456', () => true), false); assert.equal(f.calls(), 0);
  } finally { global.getComputedStyle = priorStyle; global.HTMLInputElement = priorInput; }
});
