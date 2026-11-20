const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const pages = [
  'today', 'book', 'visit', 'report', 'claim', 'followup', 'activity',
  'calendar',
  'My calendar',
  'my calendar',
  'my-calendar',
  'messages',
  'run',
  'patients',
  'interview',
  'intake',
  'reports',
  'mhr',
  'emims',
  'ppa',
  'amh',
  'sheet',
  'settings',
];
const pageScript = (operation, arg) => `(() => {
  const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
  if ([...document.querySelectorAll('input')].some(e => visible(e) && (e.type === 'password' || /one-time-code/i.test(e.autocomplete || '') || /otp|code|token|2fa|verification/i.test([e.name,e.id,e.placeholder,e.getAttribute('aria-label'), ...(e.labels ? [...e.labels].map(l => l.textContent) : [])].join(' '))))) throw Error('sign-in page');
  const helper = e => /^(hmr-|mims-|ppa-)/.test(e.id) || e.hasAttribute('data-hmr-helper');
  const op = ${JSON.stringify(operation)}, arg = ${JSON.stringify(arg)};
  if (op === 'check') return true;
  if (op === 'text') return (document.body?.innerText || '').slice(0, arg);
  if (op === 'buttons') return [...document.querySelectorAll('[id]')].filter(e => helper(e) && visible(e) && e.matches('button,a,[role="button"],input[type="button"],input[type="submit"]')).map(e => ({id:e.id,text:(e.innerText || e.value || '').trim(),disabled:!!e.disabled || e.getAttribute('aria-disabled') === 'true'}));
  const e = document.getElementById(arg);
  if (!e || !helper(e) || !visible(e) || !e.matches('button,a,[role="button"],input[type="button"],input[type="submit"]') || e.disabled || e.getAttribute('aria-disabled') === 'true') throw Error('Invalid helper element');
  e.click(); return {ok:true};
})()`;

// Main-window (renderer) controls: a structured snapshot plus click and fill by reference, so automation does not
// depend on screen coordinates. Refs are tied to one snapshot and one screen: after the screen changes, the page
// re-renders or a newer snapshot is taken, old refs are rejected. Sensitive fields (passwords, codes, tokens, keys) are
// never read or filled, link/token-shaped text is redacted, and controls that send, authorise, sign, acknowledge, call an
// outside service or open a native dialog are refused. Refusal is by label, a best-effort guard, not a security boundary.
const UI_BLOCKED = '\\b(send|resend|approve|sms|text message|queue|dispatch|offer|sign[ -]?off|signed off|mark[^a-z]{0,3}(report )?sent|report sent|claim|proda|sign[ -]?in|log[ -]?in|login|delete|discard|check phone|check messages|acknowledge|authori[sz]e|signature|signing|sign consent|draft with ai|suggest points|load ai draft|\\(ai\\)|open (original )?pdf|open folder|open patient folder|choose|browse|upload|import)\\b';
const uiScript = (operation, arg) => `(() => {
  const op = ${JSON.stringify(operation)}, arg = ${JSON.stringify(arg)};
  const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
  const sensitiveRe = /password|passcode|one-time|otp|token|2fa|verification|api[ _-]?key|secret/i;
  const redact = s => String(s ?? '')
    .replace(/https?:\\/\\/[^\\s"'<>]*(?:login|auth|signin|sign-in|oauth|otp|token|proda)[^\\s"'<>]*/gi, '[auth link removed]')
    .replace(/([?&](?:token|code|key|secret|sig|password|access_token)=)[^&\\s"']+/gi, '$1[removed]')
    .replace(/\\bBearer\\s+[A-Za-z0-9._~+\\/-]{16,}/g, 'Bearer [removed]')
    .replace(/\\b(?:sk|pk|xox[baprs]|ghp|github_pat)[-_][A-Za-z0-9_-]{16,}/g, '[key removed]')
    .replace(/\\b[0-9a-fA-F]{32,}\\b/g, '[hex removed]');
  const labelText = l => { const c = l.cloneNode(true); for (const x of c.querySelectorAll('select,textarea,input,option')) x.remove(); return c.textContent; };
  const labelOf = e => {
    const fromLabel = e.labels && e.labels.length ? [...e.labels].map(labelText).join(' ') : '';
    const own = e.getAttribute('aria-label') || fromLabel || e.placeholder || e.title || '';
    const field = e.matches('input,select,textarea') ? [e.name, e.dataset && e.dataset.field, e.dataset && e.dataset.prop, e.id].filter(Boolean).join(' ') : '';
    return redact(String(own || e.innerText || e.value || field).replace(/\\s+/g, ' ').trim().slice(0, 120));
  };
  const sensitive = e => e.type === 'password' || /one-time-code/i.test(e.autocomplete || '') || sensitiveRe.test([e.name, e.id, e.placeholder, e.getAttribute('aria-label'), e.labels && e.labels.length ? [...e.labels].map(l => l.innerText).join(' ') : ''].join(' '));
  const blocked = new RegExp(${JSON.stringify(UI_BLOCKED)}, 'i');
  const screen = () => (typeof page === 'undefined' ? null : String(page));
  const state = window.__hmrUi = window.__hmrUi || { epoch: 0, fp: {}, screen: null };
  const dataOf = e => { const d = {}; for (const a of e.attributes) if (/^data-/.test(a.name) && a.name !== 'data-hmr-ui' && Object.keys(d).length < 8) d[a.name.slice(5)] = redact(a.value).slice(0, 80); return d; };
  const print = e => [e.tagName, e.type || e.getAttribute('role') || '', labelOf(e), JSON.stringify(dataOf(e)), e.name || '', e.id || ''].join('|');
  const all = () => [...document.querySelectorAll('button,a[href],input,select,textarea,[role="button"],[role="tab"],summary')].filter(visible);
  if (op === 'guard') {
    const bad = [...document.querySelectorAll('input,textarea')].filter(e => visible(e) && sensitive(e) && String(e.value || '') !== '').length;
    const text = document.body?.innerText || '';
    if (bad || redact(text) !== text) throw Error('Refused: the screen shows a secret, token or sign-in link');
    return true;
  }
  if (op === 'snapshot') {
    for (const old of document.querySelectorAll('[data-hmr-ui]')) old.removeAttribute('data-hmr-ui');
    state.epoch += 1; state.fp = {}; state.els = {}; state.screen = screen();
    let n = 0;
    const controls = all().map(e => {
      if (e.type === 'hidden') return null;
      const r = 's' + state.epoch + '.' + (++n);
      e.setAttribute('data-hmr-ui', r); state.fp[r] = print(e); state.els[r] = e;
      const secret = e.matches('input,textarea,select') && sensitive(e);
      const item = { ref: r, tag: e.tagName.toLowerCase(), type: e.type || e.getAttribute('role') || null, id: e.id || null, label: labelOf(e), data: dataOf(e), disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true' };
      if (e.matches('input,textarea,select')) {
        item.readonly = !!e.readOnly;
        if (secret) item.sensitive = true;
        else if (e.type === 'checkbox' || e.type === 'radio') item.checked = !!e.checked;
        else if (e.type !== 'file') item.value = redact(e.value ?? '').slice(0, 300);
        if (e.tagName === 'SELECT' && !secret) item.options = [...e.options].slice(0, 60).map(o => ({ value: redact(o.value), text: redact(o.text.trim()), selected: o.selected }));
      }
      if (e.matches('button,a,[role="button"],[role="tab"],summary')) { item.text = redact((e.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120)); if (blocked.test(item.text + ' ' + item.label)) item.blocked = true; }
      return item;
    }).filter(Boolean);
    return { snapshot: state.epoch, screen: state.screen, title: document.title, text: redact((document.body?.innerText || '').slice(0, arg.max)), controls };
  }
  const m = /^s(\\d{1,6})\\.(\\d{1,6})$/.exec(String(arg.ref));
  if (!m || Number(m[1]) !== state.epoch) throw Error('Stale reference: take a fresh snapshot');
  if (state.screen !== screen()) throw Error('Stale reference: the screen changed; take a fresh snapshot');
  const e = document.querySelector('[data-hmr-ui="' + m[0] + '"]');
  if (!e || e !== (state.els || {})[m[0]] || !e.isConnected || !visible(e)) throw Error('Stale reference: the control is gone; take a fresh snapshot');
  if (state.fp[m[0]] !== print(e)) throw Error('Stale reference: the control changed; take a fresh snapshot');
  if (e.disabled || e.getAttribute('aria-disabled') === 'true') throw Error('Control is disabled');
  if (e.matches('input,textarea,select') && sensitive(e)) throw Error('Sensitive field refused');
  if (op === 'click') {
    if (e.matches('input,select,textarea') && !['button','submit','checkbox','radio'].includes(e.type)) throw Error('Use fill for this field');
    if (e.matches('input[type=file]')) throw Error('Blocked: file picker');
    if (blocked.test(labelOf(e) + ' ' + (e.innerText || '') + ' ' + Object.values(dataOf(e)).join(' '))) throw Error('Blocked: this control sends, authorises, signs, acknowledges, calls an outside service or opens a dialog; not available through this tool');
    e.click();
    return { ok: true, clicked: labelOf(e) };
  }
  if (op === 'fill') {
    if (!e.matches('input,textarea,select') || e.readOnly || ['file','hidden','button','submit','password'].includes(e.type)) throw Error('Not a fillable field');
    if (e.type === 'checkbox' || e.type === 'radio') {
      if (typeof arg.checked !== 'boolean') throw Error('checked (true or false) is required for this control');
      if (e.type === 'radio' && !arg.checked && e.checked) throw Error('A radio button cannot be unticked; choose another option');
      if (e.checked !== arg.checked) e.click();
      return { ok: true, checked: !!e.checked };
    }
    if (typeof arg.value !== 'string') throw Error('value is required for this control');
    if (e.tagName === 'SELECT') {
      const o = [...e.options].find(x => x.value === arg.value) || [...e.options].find(x => x.text.trim() === arg.value);
      if (!o) throw Error('No such option');
      e.value = o.value;
    } else {
      const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, arg.value);
    }
    e.dispatchEvent(new Event('input', { bubbles: true }));
    e.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, value: redact(e.value).slice(0, 200) };
  }
  throw Error('Unknown operation');
})()`;

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
function sanitizeAuthResult(raw) {
  if (!raw || typeof raw !== 'object') return { status: 'unavailable', reason: 'unavailable' };
  const status = WHITELISTED_STATUSES.has(raw.status) ? raw.status : 'unavailable';
  const out = { status };
  if (raw.reason && WHITELISTED_REASONS.has(raw.reason)) {
    out.reason = raw.reason;
  }
  return out;
}

function isPrivateApiRoute(value) {
  if (typeof value !== 'string') return true;
  try {
    const route = decodeURIComponent(new URL(value, 'http://127.0.0.1').pathname);
    return /^\/api\/auth(?:\/|$)/i.test(route);
  } catch {
    return true;
  }
}

function redactUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return '';
  try {
    const u = new URL(rawUrl);
    u.username = '';
    u.password = '';
    if (/proda|auth|login|signin|oauth/i.test(u.hostname) || /login|auth|signin|otp|token/i.test(u.pathname)) u.pathname = '/';
    u.search = '';
    u.hash = '';
    return u.href;
  } catch {
    return '';
  }
}


// A capture can be a stale frame: Chromium may hand back the last composited frame when a window is occluded or has not
// painted (observed once: a capture byte-identical to an earlier screen while the page had changed). This adds two checks
// and does NOT prove a capture is the current frame: (1) wait, bounded, for two painted frames; if the renderer does not
// paint within the cap the capture is refused, never hung on; (2) if the PNG is byte-identical to the previous capture of
// the same target while the page content fingerprint changed, retry, then refuse. A first capture, a stale DOM, or a changed
// but still outdated PNG are not detected. The fingerprint is a hash of visible text and ordinary field values (password,
// hidden and secret-like fields skipped). It is derived from clinical text, so it stays in this process: it is never
// returned, logged or written, and only a changed/unchanged boolean leaves this function.
const PAINT_CAP_MS = 2000;
const FRAME_SCRIPT = `new Promise(resolve => { const t = setTimeout(() => resolve(false), ${PAINT_CAP_MS});
  requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(t); resolve(true); })); })`;
const FINGERPRINT_SCRIPT = `(() => { let h = 5381; const add = s => { for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; };
  const secret = e => /pass|otp|token|secret|key|code|pin|ssn|card/i.test([e.name, e.id, e.autocomplete, e.type].join(' '));
  add(document.body?.innerText || '');
  for (const e of document.querySelectorAll('input,textarea,select')) {
    if (e.type === 'password' || e.type === 'hidden' || secret(e) || !e.getClientRects().length) continue;
    add(String(e.type === 'checkbox' || e.type === 'radio' ? e.checked : e.value)); }
  return h.toString(16); })()`;
const withCap = (promise, ms, what) => {
  let timer;
  const cap = new Promise((_, reject) => { timer = setTimeout(() => reject(Error(what + ' did not answer within ' + ms + ' ms')), ms); });
  return Promise.race([promise, cap]).finally(() => clearTimeout(timer));
};
async function captureFresh(ctx, key, wc, win) {
  const last = (ctx.lastShot ||= {})[key];
  let png, hash, fp, painted = false, attempts = 0;
  for (; attempts < 3;) {
    attempts += 1;
    painted = (await withCap(Promise.resolve(wc.executeJavaScript(FRAME_SCRIPT)), PAINT_CAP_MS + 1000, 'renderer paint check')) === true;
    if (!painted) break;
    wc.invalidate?.();
    fp = String(await withCap(Promise.resolve(wc.executeJavaScript(FINGERPRINT_SCRIPT)), 3000, 'fingerprint'));
    png = (await withCap(Promise.resolve(wc.capturePage()), 5000, 'capturePage')).toPNG();
    hash = crypto.createHash('sha256').update(png).digest('hex');
    if (!(last && last.hash === hash && last.fp !== fp)) break;
  }
  const flag = (name) => { try { return win?.[name]?.() === true; } catch { return false; } };
  const windowState = win ? { visible: flag('isVisible'), minimized: flag('isMinimized'), focused: flag('isFocused') } : undefined;
  if (!painted) return { png: undefined, ok: false, frame_painted: false, stale_detected: false, attempts, window: windowState,
    reason: 'the renderer did not paint within ' + PAINT_CAP_MS + ' ms (window may be occluded, minimized or hidden)' };
  const identical = !!(last && last.hash === hash), stale = identical && last.fp !== fp;
  ctx.lastShot[key] = { hash, fp };
  return { png: stale ? undefined : png.toString('base64'), ok: !stale, frame_painted: true, stale_detected: stale, attempts,
    identical_to_previous: identical, content_changed_since_previous: last ? last.fp !== fp : null, png_sha256: hash, window: windowState,
    reason: stale ? 'frame identical to the previous capture although the page content changed' : undefined };
}

function createHandler(ctx, token) {
  async function page(site, op, arg) {
    const view = Object.hasOwn(ctx.views, site) ? ctx.views[site] : null;
    if (!view || view.webContents.isDestroyed?.()) throw Error('Tab not open');
    const frames = view.webContents.mainFrame?.framesInSubtree || [];
    for (const frame of frames) await frame.executeJavaScript(pageScript('check'));
    return view.webContents.executeJavaScript(pageScript(op, arg));
  }
  return async (req, res) => {
    const send = (status, value) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(value));
    };
    const supplied = Buffer.from(String(req.headers['x-hmr-control'] || ''));
    const expected = Buffer.from(token);
    if (supplied.length !== expected.length || !crypto.timingSafeEqual(supplied, expected))
      return send(401, { error: 'Unauthorized' });
    if (req.method !== 'POST') return send(405, { error: 'POST required' });
    if (!/^application\/json(?:\s*;|\s*$)/i.test(req.headers['content-type'] || ''))
      return send(415, { error: 'JSON required' });
    let size = 0,
      chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 65536) return send(413, { error: 'Body too large' });
      chunks.push(chunk);
    }
    let body;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (!body || typeof body !== 'object' || Array.isArray(body)) throw Error();
    } catch {
      return send(400, { error: 'Invalid JSON' });
    }
    try {
      let result;
      const win = ctx.getWindow();
      if (!win || win.isDestroyed()) throw Error('App window is not open');
      switch (req.url) {
        case '/state':
          result = {
            screen: await win.webContents.executeJavaScript('page'),
            active: ctx.state.active,
            tabs: Object.fromEntries(
              Object.entries(ctx.views).map(([site, view]) => [
                site,
                { url: redactUrl(view.webContents.getURL()), armed: !!ctx.armed[site] },
              ]),
            ),
            one_off_count: Object.values(ctx.oneOffs).reduce((n, list) => n + list.length, 0),
          };
          break;
        case '/navigate':
          if (!pages.includes(body.page)) throw Error('Unknown page');
          result = await win.webContents.executeJavaScript(
            `navigate(${JSON.stringify(body.page)}).then(() => ({page}))`,
          );
          break;
        case '/patient/focus': {
          if (!Number.isSafeInteger(body.id) || body.id < 1 || !['patient','interview','report','followup'].includes(body.view) || Object.keys(body).some(k => !['id','view','number','tab','layout'].includes(k))) throw Error('Invalid patient focus');
          if (body.view === 'followup' ? ![1,2].includes(body.number) : body.number !== undefined) throw Error('Invalid patient focus');
          if (body.view !== 'patient' && (body.tab !== undefined || body.layout !== undefined)) throw Error('Invalid patient focus');
          if ((body.tab !== undefined && !['Overview','Conversation','Activity','Files'].includes(body.tab)) || (body.layout !== undefined && !['split','list','patient'].includes(body.layout))) throw Error('Invalid patient focus');
          const id = JSON.stringify(body.id);
          const script = body.view === 'patient' ? `openPatientWorkspace(${id},${JSON.stringify(body.tab || 'Overview')},${JSON.stringify(body.layout || 'patient')})`
            : body.view === 'interview' ? `openInterview(${id})`
            : body.view === 'report' ? `openReport(${id})`
            : `openFollowup(${id},${JSON.stringify(body.number)})`;
          result = await win.webContents.executeJavaScript(script);
          break;
        }
        case '/tab':
          if (!['mhr', 'emims', 'ppa', 'amh', 'sheet'].includes(body.site)) throw Error('Unknown tab');
          if (!['open', 'back', 'reload', 'toggle', 'load'].includes(body.action)) throw Error('Invalid action');
          result = (await ctx.tabAction(body.action, body.site, body.url)) ?? { ok: true };
          break;
        case '/page/buttons':
          result = await page(body.site, 'buttons');
          break;
        case '/page/click':
          if (typeof body.id !== 'string' || !body.id) throw Error('Invalid helper element');
          result = await page(body.site, 'click', body.id);
          break;
        case '/page/text':
          if (body.max !== undefined && (!Number.isSafeInteger(body.max) || body.max < 1 || body.max > 200000))
            throw Error('Invalid max');
          result = await page(body.site, 'text', body.max ?? 20000);
          break;
        case '/page/screenshot': {
          if (!body.site) { await win.webContents.executeJavaScript(pageScript('check')); await win.webContents.executeJavaScript(uiScript('guard')); }
          const site = body.site || ctx.state.active;
          if (site) await page(site, 'check');
          const target = body.site ? ctx.views[body.site].webContents : win.webContents;
          result = await captureFresh(ctx, body.site || '', target, body.site ? null : win);
          break;
        }
        case '/results':
          result = { results: ctx.results, saved: ctx.saved || {} };
          break;
        case '/auth/status':
          if (typeof ctx.authStatus !== 'function') return send(503, { error: 'unavailable' });
          result = sanitizeAuthResult(await ctx.authStatus(body));
          break;
        case '/auth/proda/login':
          if (typeof ctx.prodaLogin !== 'function') return send(503, { error: 'unavailable' });
          result = sanitizeAuthResult(await ctx.prodaLogin(body));
          break;
        case '/identity':
          result = { app_pid: process.pid, data_dir: ctx.dataDir || null, user_profile: process.env.USERPROFILE || null, smoke: !!process.env.HMR_SMOKE_DATA, control_port: ctx.controlPort || null };
          break;
        case '/ui/snapshot':
          if (body.max !== undefined && (!Number.isSafeInteger(body.max) || body.max < 1 || body.max > 200000)) throw Error('Invalid max');
          result = await win.webContents.executeJavaScript(uiScript('snapshot', { max: body.max ?? 20000 }));
          break;
        case '/ui/click':
          if (typeof body.ref !== 'string' || !/^s\d{1,6}\.\d{1,6}$/.test(body.ref)) throw Error('Invalid ref');
          result = await win.webContents.executeJavaScript(uiScript('click', { ref: body.ref }));
          break;
        case '/ui/fill':
          if (typeof body.ref !== 'string' || !/^s\d{1,6}\.\d{1,6}$/.test(body.ref)) throw Error('Invalid ref');
          if ((body.value === undefined) === (body.checked === undefined) || (body.value !== undefined && (typeof body.value !== 'string' || body.value.length > 20000)) || (body.checked !== undefined && typeof body.checked !== 'boolean')) throw Error('Provide exactly one of value or checked');
          result = await win.webContents.executeJavaScript(uiScript('fill', { ref: body.ref, value: body.value, checked: body.checked }));
          break;
        case '/window':
          if (body.action === 'focus') {
            if (win.isMinimized()) win.restore();
            win.focus();
          } else if (body.action === 'minimize') win.minimize();
          else throw Error('Invalid action');
          result = { ok: true };
          break;
        default:
          return send(404, { error: 'Unknown route' });
      }
      send(200, result);
    } catch (error) {
      if (req.url === '/auth/status' || req.url === '/auth/proda/login') {
        return send(200, { status: 'unavailable', reason: 'unavailable' });
      }
      send(400, { error: /sign-in page/.test(error.message) ? 'sign-in page' : error.message });
    }
  };
}
function start(ctx) {
  const token = crypto.randomBytes(32).toString('hex');
  const server = http.createServer(createHandler(ctx, token));
  const preferred = process.env.HMR_SMOKE_DATA ? 18768 : 8768;
  let fallback = false;
  const endpointFile = ctx.dataDir ? path.join(ctx.dataDir, 'control_endpoint.json') : null;
  const clear = () => { try { if (endpointFile) fs.rmSync(endpointFile, { force: true }); } catch {} };
  const listening = () => {
    ctx.controlPort = server.address().port;
    try {
      fs.writeFileSync(path.join(ctx.dataDir, 'app_control_token'), token, { mode: 0o600 });
      // The fixed port can already belong to another running copy. Record where THIS copy listens (never the token).
      fs.writeFileSync(endpointFile, JSON.stringify({ url: 'http://127.0.0.1:' + ctx.controlPort, pid: process.pid, fallback, written_at: new Date().toISOString() }), { mode: 0o600 });
    } catch (error) {
      console.error(`Control token unavailable: ${error.message}`);
      server.close();
    }
  };
  server.on('error', (error) => {
    if (error.code === 'EADDRINUSE' && !fallback) {
      fallback = true;
      console.error(`Control port ${preferred} is in use by another copy; using a private port`);
      return server.listen({ host: '127.0.0.1', port: 0, exclusive: true }, listening);
    }
    clear();
    console.error(`Control endpoint unavailable: ${error.message}`);
  });
  server.on('close', clear);
  process.once('exit', clear);
  clear();
  server.listen({ host: '127.0.0.1', port: preferred, exclusive: true }, listening);
  return server;
}

module.exports = { captureFresh, createHandler, start, pageScript, uiScript, UI_BLOCKED, sanitizeAuthResult, redactUrl, isPrivateApiRoute, WHITELISTED_STATUSES, WHITELISTED_REASONS };
