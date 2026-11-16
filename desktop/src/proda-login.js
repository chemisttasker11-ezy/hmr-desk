const PRODA_ORIGIN = 'https://proda.humanservices.gov.au';
const PRODA_LOGOUT_PATH = '/prodalogin/pages/public/logout.jsf';
const PRODA_SERVICES_PATH = '/pia/pages/private/myIdentity/myServices.jsf';
const CLINICAL_HOST = 'provider.ehealth.gov.au';
const CLINICAL_ORIGIN = 'https://provider.ehealth.gov.au';
const CLINICAL_LANDING_PATH = '/portal/landing-page';
const CLINICAL_SEARCH_PATH = '/portal/health-record-search';
const POLL_INTERVAL_MS = 2500;
const ATTEMPT_TTL_MS = 300000; // 5 minutes

function isExactProdaOrigin(urlString) {
  if (!urlString || typeof urlString !== 'string') return false;
  try {
    const u = new URL(urlString);
    return (
      u.protocol === 'https:' &&
      u.origin === PRODA_ORIGIN &&
      u.hostname === 'proda.humanservices.gov.au' &&
      !u.username &&
      !u.password &&
      (u.port === '' || u.port === '443')
    );
  } catch {
    return false;
  }
}

function isProdaLogout(url) {
  if (!isExactProdaOrigin(url)) return false;
  try { return new URL(url).pathname === PRODA_LOGOUT_PATH; } catch { return false; }
}

function isExactClinicalHost(urlString) {
  if (!urlString || typeof urlString !== 'string') return false;
  try {
    const u = new URL(urlString);
    return (
      u.protocol === 'https:' &&
      u.hostname === CLINICAL_HOST &&
      !u.username &&
      !u.password &&
      (u.port === '' || u.port === '443')
    );
  } catch {
    return false;
  }
}

const WHITELISTED_STATUSES = new Set([
  'disabled',
  'pending',
  'waiting_sms',
  'submitted',
  'completed',
  'needs_user_action',
  'unavailable',
]);

const WHITELISTED_REASONS = new Set([
  'not_started',
  'manual_fallback',
  'expired',
  'ambiguous',
  'invalid_code',
  'credentials_missing',
  'mhr_inactive',
  'proda_auto_sms_login_disabled',
  'harness_disabled',
  'navigation_cancelled',
  'service_selection_needed',
  'challenge_mismatch',
  'tab_not_open',
  'unavailable',
]);

function sanitizeStatus(status, reason) {
  const safeStatus = WHITELISTED_STATUSES.has(status) ? status : 'unavailable';
  const out = { status: safeStatus };
  if (reason && WHITELISTED_REASONS.has(reason)) {
    out.reason = reason;
  }
  return out;
}

module.exports = ({
  api,
  ipcMain,
  views,
  state,
  waitingTasks = {},
  openTab,
  notify = () => {},
  signIns = () => null,
  autorun = () => null,
  getWindow = () => null,
  now = Date.now,
  sleep = (ms) => new Promise((ok) => setTimeout(ok, ms)),
  isHarness = () => !!(process.env.HMR_SHOTS || process.env.HMR_SMOKE_URL || process.env.HMR_SMOKE_DATA),
  allowHarness = false,
}) => {
  let currentStatus = 'pending';
  let currentReason = 'not_started';
  let activeAttempt = null;
  let inFlightStart = null;
  let generation = 0;
  let loginRequested = false;
  let attachedView = null;
  let navigationPending = false;
  let landingGeneration = null;
  let logoutRecoveryUsed = false;

  function setStatus(status, reason = null) {
    if (WHITELISTED_STATUSES.has(status)) {
      currentStatus = status;
      currentReason = reason && WHITELISTED_REASONS.has(reason) ? reason : null;
    }
  }

  async function isSettingEnabled() {
    try {
      const res = await api('GET', '/api/settings');
      // Actual engine api/settings returns { settings: [{ key, value, ... }] }
      if (Array.isArray(res?.settings)) {
        const item = res.settings.find((s) => s?.key === 'proda_auto_sms_login');
        if (item) {
          return item.value === true || item.value === 'true' || item.value === 1;
        }
      }
      return false;
    } catch {
      return false;
    }
  }

  function isMhrActive() {
    if (state?.active === 'mhr') return true;
    if (Array.isArray(waitingTasks?.mhr) && waitingTasks.mhr.length > 0) return true;
    if (loginRequested) return true;
    return !!autorun?.()?.hasWaiting?.('mhr');
  }

  function validateSender(event) {
    // Strictly require event, sender, senderFrame
    if (!event || !event.sender || !event.senderFrame) return false;
    const v = views?.mhr;
    if (!v || v.webContents !== event.sender) return false;
    if (event.senderFrame !== event.sender.mainFrame) return false;
    const currentUrl = event.sender.getURL?.();
    if (!isExactProdaOrigin(currentUrl)) return false;
    return true;
  }

  async function canAutoSubmit() {
    if (isHarness() && !allowHarness) return false;
    if (!isMhrActive()) return false;
    const enabled = await isSettingEnabled();
    if (!enabled) return false;
    return isMhrActive();
  }

  async function beforeSubmit(event) {
    if (!validateSender(event)) {
      return { ok: false, error: 'invalid_sender' };
    }

    attachView(views.mhr);
    if (isHarness() && !allowHarness) {
      setStatus('unavailable', 'harness_disabled');
      return { ok: false, status: 'unavailable' };
    }

    // Coalesce concurrent calls for the same challenge/generation
    if (inFlightStart) return inFlightStart;

    if (activeAttempt) {
      const old = activeAttempt;
      old.polling = false;
      activeAttempt = null;
      api('POST', '/api/auth/proda/finish', { attempt_id: old.id, outcome: 'cancelled' }).catch(() => {});
    }

    const boundGen = generation;
    const boundSender = event.sender;
    const boundFrame = event.senderFrame;

    inFlightStart = (async () => {
      const enabled = await isSettingEnabled();

      // Re-validate sender, frame, origin, and generation after settings await
      if (
        views?.mhr?.webContents !== boundSender ||
        boundSender.isDestroyed?.() ||
        boundFrame !== boundSender.mainFrame ||
        !isExactProdaOrigin(boundSender.getURL?.()) ||
        generation !== boundGen
      ) {
        return { ok: false, error: 'state_changed' };
      }
      if (!enabled) {
        loginRequested = false;
        setStatus('disabled', 'proda_auto_sms_login_disabled');
        return { ok: true, status: 'disabled' };
      }

      let res;
      try {
        res = await api('POST', '/api/auth/proda/start', { origin: PRODA_ORIGIN });
      } catch {
        if (views?.mhr?.webContents !== boundSender || boundSender.isDestroyed?.() || boundFrame !== boundSender.mainFrame || !isExactProdaOrigin(boundSender.getURL?.()) || generation !== boundGen) return { ok: false, error: 'state_changed' };
        loginRequested = false;
        setStatus('unavailable', 'unavailable');
        return { ok: true, status: 'unavailable' };
      }

      // Re-validate sender, frame, origin, and generation after start API await
      if (
        views?.mhr?.webContents !== boundSender ||
        boundSender.isDestroyed?.() ||
        boundFrame !== boundSender.mainFrame ||
        !isExactProdaOrigin(boundSender.getURL?.()) ||
        generation !== boundGen
      ) {
        if (res?.attempt_id) {
          api('POST', '/api/auth/proda/finish', { attempt_id: res.attempt_id, outcome: 'cancelled' }).catch(() => {});
        }
        return { ok: false, error: 'state_changed' };
      }

      if (res?.status === 'started' && res.attempt_id) {
        activeAttempt = {
          id: res.attempt_id,
          started_at: res.started_at,
          startTime: now(),
          polling: false,
          submitted: false,
          passwordGen: boundGen,
          expectedOtpGen: boundGen + 1, // Bounded expected transition to OTP challenge
          otpGen: null,
          stage: 'awaiting_otp',
        };
        setStatus('pending');
        return { ok: true, status: 'started' };
      }

      activeAttempt = null;
      loginRequested = false;
      if (res?.status === 'disabled') {
        setStatus('disabled', 'proda_auto_sms_login_disabled');
        return { ok: true, status: 'disabled' };
      }
      setStatus('unavailable', 'unavailable');
      return { ok: true, status: 'unavailable' };
    })();

    try {
      return await inFlightStart;
    } finally {
      inFlightStart = null;
    }
  }

  function finishAttempt(attempt, status, reason, outcome, message) {
    if (activeAttempt !== attempt) return;
    attempt.polling = false;
    clearTimeout(attempt.deliveryTimer);
    activeAttempt = null;
    loginRequested = false;
    setStatus(status, reason);
    if (message) notify('result', { site: 'mhr', status: message });
    if (!attempt.finished) {
      attempt.finished = true;
      api('POST', '/api/auth/proda/finish', { attempt_id: attempt.id, outcome }).catch(() => {});
    }
  }

  async function startPolling(attempt, boundSender, boundFrame) {
    const valid = () => activeAttempt === attempt && attempt.polling &&
      views?.mhr?.webContents === boundSender && !boundSender.isDestroyed?.() &&
      boundFrame === boundSender.mainFrame && isExactProdaOrigin(boundSender.getURL?.()) &&
      generation === attempt.otpGen;
    const expired = () => now() - attempt.startTime >= ATTEMPT_TTL_MS;
    attempt.polling = true;
    setStatus('waiting_sms');
    notify('result', { site: 'mhr', status: 'Waiting for PRODA SMS verification code...' });
    while (valid()) {
      if (expired()) {
        finishAttempt(attempt, 'needs_user_action', 'expired', 'failed', 'PRODA SMS code expired - enter manually');
        return;
      }
      await sleep(POLL_INTERVAL_MS);
      if (activeAttempt !== attempt || !attempt.polling) return;
      if (!valid()) {
        finishAttempt(attempt, 'needs_user_action', 'navigation_cancelled', 'cancelled');
        return;
      }
      if (expired()) continue;
      let reply;
      try {
        reply = await api('POST', '/api/auth/proda/poll', { attempt_id: attempt.id });
      } catch {
        finishAttempt(attempt, 'unavailable', 'unavailable', 'failed', 'PRODA SMS login unavailable - enter manually');
        return;
      }
      if (activeAttempt !== attempt || !attempt.polling) return;
      if (!valid()) {
        finishAttempt(attempt, 'needs_user_action', 'navigation_cancelled', 'cancelled');
        return;
      }
      if (expired()) {
        finishAttempt(attempt, 'needs_user_action', 'expired', 'failed', 'PRODA SMS code expired - enter manually');
        return;
      }
      if (reply?.status === 'waiting') continue;
      if (reply?.status !== 'code' || typeof reply.code !== 'string' || !/^\d{6}$/.test(reply.code)) {
        const reason = reply?.status === 'expired' ? 'expired' : reply?.status === 'ambiguous' ? 'ambiguous' : 'unavailable';
        finishAttempt(attempt, reason === 'unavailable' ? 'unavailable' : 'needs_user_action', reason, 'failed', 'PRODA SMS login unavailable - enter manually');
        return;
      }
      attempt.submitted = true;
      attempt.polling = false;
      attempt.stage = 'submitted_otp';
      setStatus('pending');
      notify('result', { site: 'mhr', status: 'Submitting PRODA verification code...' });
      try {
        boundSender.send('proda-otp-fill', { code: reply.code, nonce: attempt.challengeNonce });
      } catch {
        reply.code = null;
        finishAttempt(attempt, 'unavailable', 'unavailable', 'failed', 'PRODA SMS login unavailable - enter manually');
        return;
      }
      reply.code = null;
      attempt.deliveryTimer = setTimeout(() => {
        if (activeAttempt === attempt && !attempt.acknowledged) finishAttempt(attempt, 'needs_user_action', 'manual_fallback', 'failed', 'Enter PRODA verification code manually');
      }, 5000);
      attempt.deliveryTimer.unref?.();
      return;
    }
    if (activeAttempt === attempt) finishAttempt(attempt, 'needs_user_action', 'navigation_cancelled', 'cancelled');
  }

  async function onOtpPage(hasOtp, event, challengeNonce) {
    if (!validateSender(event)) return;
    if (!hasOtp) {
      if (activeAttempt?.stage === 'polling_otp') onOtpManual(event);
      return;
    }
    if (typeof challengeNonce !== 'string' || !/^[a-f0-9-]{16,64}$/i.test(challengeNonce)) return;

    if (!activeAttempt) {
      setStatus('needs_user_action', 'manual_fallback');
      notify('result', { site: 'mhr', status: 'Enter PRODA verification code manually' });
      return;
    }

    if (now() - activeAttempt.startTime >= ATTEMPT_TTL_MS) {
      const old = activeAttempt; activeAttempt = null; loginRequested = false;
      setStatus('needs_user_action', 'expired');
      notify('result', { site: 'mhr', status: 'PRODA SMS code expired - enter manually' });
      try {
        await api('POST', '/api/auth/proda/finish', { attempt_id: old.id, outcome: 'failed' });
      } catch {}
      return;
    }

    if (activeAttempt.submitted) return;
    if (activeAttempt.polling && activeAttempt.challengeNonce === challengeNonce) return;
    if (activeAttempt.polling) { onOtpManual(event); setStatus('needs_user_action', 'challenge_mismatch'); return; }

    // Model explicit bounded expected transition from genuine password submit to its first OTP challenge
    if (activeAttempt.stage === 'awaiting_otp') {
      // Allow transition to OTP page on exact origin: either generation incremented by 1 (navigation), or stayed same (DOM swap)
      if (generation === activeAttempt.expectedOtpGen || generation === activeAttempt.passwordGen) {
        activeAttempt.stage = 'polling_otp';
        activeAttempt.otpGen = generation;
        activeAttempt.challengeNonce = challengeNonce;
      } else {
        // Intervening reload, replaced challenge, or multiple navigations: cancel!
        onOtpManual(event);
        setStatus('needs_user_action', 'challenge_mismatch');
        return;
      }
    } else if (activeAttempt.stage === 'polling_otp') {
      // Must match active challenge generation
      if (generation !== activeAttempt.otpGen || activeAttempt.challengeNonce !== challengeNonce) {
        onOtpManual(event);
        setStatus('needs_user_action', 'challenge_mismatch');
        return;
      }
    } else {
      return;
    }

    await startPolling(activeAttempt, event.sender, event.senderFrame);
  }

  function onOtpManual(event) {
    if (!validateSender(event)) return;
    if (activeAttempt) {
      finishAttempt(activeAttempt, 'needs_user_action', 'manual_fallback', 'cancelled');
    } else {
      loginRequested = false;
      setStatus('needs_user_action', 'manual_fallback');
    }
  }

  function onOtpSubmitted(event, nonce) {
    if (!validateSender(event) || !activeAttempt?.submitted || activeAttempt.challengeNonce !== nonce || generation !== activeAttempt.otpGen) return;
    activeAttempt.acknowledged = true;
    clearTimeout(activeAttempt.deliveryTimer);
    if (!activeAttempt.finished) {
      activeAttempt.finished = true;
      api('POST', '/api/auth/proda/finish', { attempt_id: activeAttempt.id, outcome: 'submitted' }).catch(() => {});
    }
    setStatus('submitted');
  }

  async function checkServiceSelection(view) {
    if (!view || views?.mhr !== view || view.webContents?.isDestroyed?.() || currentStatus !== 'submitted') return;
    // Follow-on clicks belong to the attempt whose code was accepted: once each, within its lifetime.
    const login = activeAttempt;
    if (login && (login.serviceClicked || now() - login.startTime >= ATTEMPT_TTL_MS)) return;
    const currentUrl = view.webContents.getURL?.() || '';
    const boundGen = generation, boundFrame = view.webContents.mainFrame;
    if (!boundFrame || !isExactProdaOrigin(currentUrl)) return;

    try {
      const script = `(() => {
        // Re-check top origin INSIDE injected script just before evaluation
        if (window.location.origin !== 'https://proda.humanservices.gov.au' || window !== window.top) {
          return { none: true };
        }
        const visible = e => !e.disabled && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';

        // Check for terms/agreements or organisation selection
        const terms = [...document.querySelectorAll('input[type=checkbox]')].filter(visible);
        if (terms.length > 0) return { extraChoice: true };

        const orgs = [...document.querySelectorAll('select, [role=listbox]')].filter(visible);
        if (orgs.length > 0) return { extraChoice: true };
        if (window.location.href === '${PRODA_ORIGIN}${PRODA_SERVICES_PATH}' && [...document.querySelectorAll('input[type=radio]')].some(visible)) return { extraChoice: true };

        // Restrict to ONE VISIBLE actual anchor with URL-parsed exact HTTPS provider origin and MHR text
        const anchors = [...document.querySelectorAll('a')].filter(visible).filter(a => {
          let targetUrl;
          try {
            targetUrl = new URL(a.href, window.location.href);
          } catch {
            return false;
          }
          if (
            targetUrl.protocol !== 'https:' ||
            targetUrl.hostname !== 'provider.ehealth.gov.au' ||
            targetUrl.username ||
            targetUrl.password ||
            (targetUrl.port && targetUrl.port !== '443')
          ) {
            return false;
          }
          const text = (a.innerText || a.textContent || '').trim();
          return /\\bmy\\s+health\\s+record\\b/i.test(text);
        });

        if (anchors.length === 1) {
          const a = anchors[0];
          // Re-check origin immediately before click
          if (window.location.origin === 'https://proda.humanservices.gov.au') {
            a.click();
            return { clicked: true };
          }
        }

        if (anchors.length > 1) return { extraChoice: true };
        if (window.location.href === '${PRODA_ORIGIN}${PRODA_SERVICES_PATH}') {
          const links = [...document.querySelectorAll('a')].filter(visible).filter(a => {
            const form = a.closest('form');
            try {
              return (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase() === 'my health record' &&
                form && form.method.toLowerCase() === 'post' && new URL(form.action, window.location.href).href === '${PRODA_ORIGIN}${PRODA_SERVICES_PATH}';
            } catch { return false; }
          });
          if (links.length > 1) return { extraChoice: true };
          // Two checks can reach the same document; a second click would re-post the form.
          if (links.length === 1 && window.location.origin === '${PRODA_ORIGIN}' && !window.__hmrServiceClicked) { window.__hmrServiceClicked = true; links[0].click(); return { clicked: true }; }
        }
        return { none: true };
      })()`;

      if (views?.mhr !== view || generation !== boundGen || view.webContents.mainFrame !== boundFrame || view.webContents.getURL?.() !== currentUrl) return;
      const res = await view.webContents.executeJavaScript(script);
      if (res?.clicked && login) login.serviceClicked = true;
      if (views?.mhr !== view || generation !== boundGen || view.webContents.mainFrame !== boundFrame || view.webContents.getURL?.() !== currentUrl) return;
      if (res?.extraChoice) {
        setStatus('needs_user_action', 'service_selection_needed');
      }
    } catch {}
  }

  async function checkClinicalLanding(view) {
    if (!view || views?.mhr !== view || view.webContents?.isDestroyed?.() || currentStatus !== 'submitted') return;
    const login = activeAttempt;
    if (login && (login.landingClicked || now() - login.startTime >= ATTEMPT_TTL_MS)) return;
    const wc = view.webContents, url = wc.getURL?.() || '', boundGen = generation, boundFrame = wc.mainFrame;
    if (!boundFrame || url !== CLINICAL_ORIGIN + CLINICAL_LANDING_PATH || landingGeneration === boundGen) return;
    landingGeneration = boundGen;
    const valid = () => views?.mhr === view && view.webContents === wc && !wc.isDestroyed?.() && currentStatus === 'submitted' && generation === boundGen && wc.mainFrame === boundFrame && wc.getURL?.() === url;
    const script = `(() => {
      if (window !== window.top || window.location.origin !== '${CLINICAL_ORIGIN}' || window.location.pathname !== '${CLINICAL_LANDING_PATH}') return { none: true };
      const visible = e => !e.disabled && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
      if ([...document.querySelectorAll('input[type=checkbox], select, input:not([type]), input[type=text], input[type=email], input[type=password], input[type=tel], input[type=number], textarea')].some(visible)) return { extraChoice: true };
      const radios = [...document.querySelectorAll('input[type=radio]')].filter(visible);
      if (!radios.length) return { none: true };
      if (radios.length !== 1) return { extraChoice: true };
      const radio = radios[0], form = radio.form;
      if (!form) return { extraChoice: true };
      const submits = [...form.querySelectorAll('button[type=submit], input[type=submit], button:not([type])')].filter(e => e.form === form && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none');
      if (submits.length !== 1 || !/^next$/i.test((submits[0].tagName.toLowerCase() === 'input' ? submits[0].value : submits[0].textContent).trim())) return { extraChoice: true };
      if (window !== window.top || window.location.origin !== '${CLINICAL_ORIGIN}' || window.location.pathname !== '${CLINICAL_LANDING_PATH}') return { none: true };
      if (!radio.checked) radio.click();
      if (submits[0].disabled) return { none: true };
      submits[0].click();
      return { clicked: true };
    })()`;
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        if (!valid()) return;
        const res = await wc.executeJavaScript(script);
        if (res?.clicked && login) login.landingClicked = true;
        if (!valid()) return;
        if (res?.extraChoice) {
          setStatus('needs_user_action', 'service_selection_needed');
          notify('result', { site: 'mhr', status: 'Choose your organisation in My Health Record' });
          return;
        }
        if (!res?.none || attempt) return;
        await sleep(1500);
      }
    } catch {}
  }

  async function verifyClinicalReadiness(view) {
    if (!view || view.webContents?.isDestroyed?.()) return false;
    try {
      const url = view.webContents.getURL?.() || '';
      if (!isExactClinicalHost(url)) return false;

      let parsed;
      try {
        parsed = new URL(url);
      } catch {
        return false;
      }
      if (parsed.pathname !== CLINICAL_SEARCH_PATH) {
        return false;
      }

      const boundGen = generation, boundWc = view.webContents, boundFrame = boundWc.mainFrame;
      if (views?.mhr !== view || !boundFrame) return false;
      const script = `(() => {
        if (window.location.pathname !== '${CLINICAL_SEARCH_PATH}') return false;
        if (window.location.origin !== '${CLINICAL_ORIGIN}' || window !== window.top) return false;
        if (document.querySelector('input[type=password]')) return false;
        // Verify positive search DOM signal at /portal/health-record-search
        return ['lname', 'dob', 'identifierval', 'radio-sex-female', 'radio-sex-male', 'radio-identifier-IHI', 'radio-identifier-Medicare', 'search'].every(id => !!document.getElementById(id));
      })()`;

      const ready = await view.webContents.executeJavaScript(script);
      // Re-check exact origin after async script resolves
      const postUrl = view.webContents.getURL?.() || '';
      if (!ready || views?.mhr !== view || view.webContents !== boundWc || boundWc.isDestroyed?.() || boundWc.mainFrame !== boundFrame || generation !== boundGen || postUrl !== url || !isExactClinicalHost(postUrl)) return false;

      return true;
    } catch {
      return false;
    }
  }

  function complete() {
    if (currentStatus === 'completed') return;
    setStatus('completed');
    logoutRecoveryUsed = false;
    notify('result', { site: 'mhr', status: 'My Health Record login completed' });
    loginRequested = false;
    if (activeAttempt) {
      const old = activeAttempt; old.polling = false; clearTimeout(old.deliveryTimer); activeAttempt = null;
      if (!old.finished) api('POST', '/api/auth/proda/finish', { attempt_id: old.id, outcome: 'submitted' }).catch(() => {});
    }
    try { autorun?.()?.retry?.('mhr'); } catch {}
  }

  async function onNavigation(url) {
    if (!navigationPending) generation++;
    navigationPending = false;
    if (isProdaLogout(url)) {
      if (activeAttempt) finishAttempt(activeAttempt, 'needs_user_action', 'manual_fallback', 'cancelled');
      else { loginRequested = false; setStatus('needs_user_action', 'manual_fallback'); }
      return;
    }
    if (activeAttempt && activeAttempt.stage === 'polling_otp') {
      const old = activeAttempt; old.polling = false; activeAttempt = null; loginRequested = false;
      setStatus('needs_user_action', 'navigation_cancelled');
      api('POST', '/api/auth/proda/finish', { attempt_id: old.id, outcome: 'cancelled' }).catch(() => {});
    }

    if (isExactClinicalHost(url)) {
      const v = views?.mhr;
      // Do NOT mark complete from onNavigation host alone: require known actual clinical readiness
      const ready = await verifyClinicalReadiness(v);
      if (ready) {
        complete();
        return;
      }
      // If reached clinical host but not ready yet (e.g. initial redirect loading), wait for dom settlement
      return;
    }

    if (isExactProdaOrigin(url)) {
      const v = views?.mhr;
      if (v) setTimeout(() => checkServiceSelection(v), 500);
      return;
    }

    // Navigated to outside origin or cancelled
    loginRequested = false;
    if (activeAttempt) {
      const cancelledId = activeAttempt.id;
      activeAttempt = null;
      setStatus('needs_user_action', 'navigation_cancelled');
      loginRequested = false;
      api('POST', '/api/auth/proda/finish', { attempt_id: cancelledId, outcome: 'cancelled' }).catch(() => {});
    }
  }

  function attachView(view) {
    if (!view || view === attachedView) return;
    attachedView = view;
    view.webContents?.on('did-start-navigation', (event, url, inPlace, isMainFrame) => {
      if (isMainFrame !== true || views?.mhr !== view) return;
      // PRODA's / landing page navigates itself to the code page; reloads still cancel.
      if (activeAttempt?.stage === 'awaiting_otp' && !activeAttempt.landingHopUsed &&
          generation === activeAttempt.expectedOtpGen && event?.initiator != null && inPlace === false &&
          view.webContents.getURL() === PRODA_ORIGIN + '/' && url === PRODA_ORIGIN + PRODA_SERVICES_PATH) {
        activeAttempt.landingHopUsed = true;
        activeAttempt.expectedOtpGen++;
      }
      generation++; navigationPending = true;
      if (currentStatus === 'completed') setStatus('pending', 'not_started');
      if (activeAttempt && (activeAttempt.stage === 'polling_otp' || !isExactProdaOrigin(url) && !isExactClinicalHost(url) || activeAttempt.stage === 'awaiting_otp' && generation > activeAttempt.expectedOtpGen)) {
        const old = activeAttempt; old.polling = false; activeAttempt = null; loginRequested = false;
        setStatus('needs_user_action', 'navigation_cancelled');
        api('POST', '/api/auth/proda/finish', { attempt_id: old.id, outcome: 'cancelled' }).catch(() => {});
      }
    });
    view.webContents?.on('did-navigate', (_event, url) => { if (views?.mhr === view) onNavigation(url); });
    view.webContents?.on('did-navigate-in-page', (_event, url, isMainFrame) => { if (isMainFrame === true) onNavigation(url); });
    view.webContents?.on('dom-ready', async () => {
      if (views?.mhr !== view) return;
      if (isExactProdaOrigin(view.webContents.getURL?.())) { checkServiceSelection(view); return; }
      if (view.webContents.getURL?.() === CLINICAL_ORIGIN + CLINICAL_LANDING_PATH) void checkClinicalLanding(view);
      if (await verifyClinicalReadiness(view)) complete();
    });
  }

  function authStatus() {
    return sanitizeStatus(currentStatus, currentReason);
  }

  async function triggerLogin() {
    if (isHarness() && !allowHarness) {
      return sanitizeStatus('unavailable', 'harness_disabled');
    }
    const enabled = await isSettingEnabled();
    if (!enabled) {
      setStatus('disabled', 'proda_auto_sms_login_disabled');
      return sanitizeStatus('disabled', 'proda_auto_sms_login_disabled');
    }

    if (openTab) {
      try {
        await openTab('mhr');
      } catch {}
    }

    const v = views?.mhr;
    if (v) {
      attachView(v);
      const url = v.webContents?.getURL?.() || '';
      if (isExactClinicalHost(url)) {
        const ready = await verifyClinicalReadiness(v);
        if (ready) {
          complete();
          return sanitizeStatus('completed');
        }
      }
    }

    if (!v) {
      setStatus('unavailable', 'tab_not_open');
      return authStatus();
    }
    const wc = v.webContents;
    const url = wc?.getURL?.() || '';
    if (isProdaLogout(url)) {
      if (logoutRecoveryUsed || !wc || wc.isDestroyed?.() || !wc.mainFrame) {
        setStatus('needs_user_action', 'manual_fallback');
        return authStatus();
      }
      if (activeAttempt) finishAttempt(activeAttempt, 'needs_user_action', 'manual_fallback', 'cancelled');
      const frame = wc.mainFrame, boundGen = generation;
      logoutRecoveryUsed = true;
      loginRequested = true;
      setStatus('pending');
      try {
        if (views?.mhr !== v || v.webContents !== wc || wc.isDestroyed?.() || wc.mainFrame !== frame || generation !== boundGen || wc.getURL?.() !== url) throw Error();
        await wc.loadURL(PRODA_ORIGIN + '/');
      } catch (error) {
        const expectedAbort = error?.errno === -3 && generation !== boundGen;
        if (!expectedAbort && views?.mhr === v && v.webContents === wc && !wc.isDestroyed?.() && wc.mainFrame === frame && loginRequested) {
          loginRequested = false;
          setStatus('needs_user_action', 'manual_fallback');
        }
      }
      return authStatus();
    }
    loginRequested = true;
    try {
      signIns?.()?.requestFill?.('mhr');
    } catch {}

    return sanitizeStatus(currentStatus, currentReason);
  }

  if (ipcMain) {
    ipcMain.handle('proda-before-submit', (event) => beforeSubmit(event));
    ipcMain.on('proda-start-cancel', (event) => { if (validateSender(event)) { generation++; onOtpManual(event); } });
    ipcMain.on('proda-password-page', (event) => {
      if (validateSender(event) && activeAttempt && !activeAttempt.submitted) onOtpManual(event);
    });
    ipcMain.on('proda-otp-page', (event, hasOtp, nonce) => onOtpPage(hasOtp, event, nonce));
    ipcMain.on('proda-otp-manual', (event) => onOtpManual(event));
    ipcMain.on('proda-otp-rejected', (event) => onOtpManual(event));
    ipcMain.on('proda-otp-submitted', (event, nonce) => onOtpSubmitted(event, nonce));
  }

  return {
    authStatus,
    triggerLogin,
    canAutoSubmit,
    beforeSubmit,
    onOtpPage,
    onOtpManual,
    onOtpSubmitted,
    onNavigation,
    attachView,
    setStatus,
    checkServiceSelection,
    checkClinicalLanding,
    verifyClinicalReadiness,
    isExactProdaOrigin,
    isExactClinicalHost,
    validateSender,
    sanitizeStatus,
    getGeneration: () => generation,
    getActiveAttempt: () => (activeAttempt ? { ...activeAttempt } : null),
  };
};
