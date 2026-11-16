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
          if (!body.site) await win.webContents.executeJavaScript(pageScript('check'));
          const site = body.site || ctx.state.active;
          if (site) await page(site, 'check');
          const target = body.site ? ctx.views[body.site].webContents : win.webContents;
          result = { png: (await target.capturePage()).toPNG().toString('base64') };
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
  server.on('error', (error) => console.error(`Control endpoint unavailable: ${error.message}`));
  server.listen({ host: '127.0.0.1', port: process.env.HMR_SMOKE_DATA ? 18768 : 8768, exclusive: true }, () => {
    try {
      fs.writeFileSync(path.join(ctx.dataDir, 'app_control_token'), token, { mode: 0o600 });
    } catch (error) {
      console.error(`Control token unavailable: ${error.message}`);
      server.close();
    }
  });
  return server;
}
module.exports = { createHandler, start, pageScript, sanitizeAuthResult, redactUrl, isPrivateApiRoute, WHITELISTED_STATUSES, WHITELISTED_REASONS };
