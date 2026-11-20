// Real-DOM check of the main-window controls (uiScript) through headless Chrome, plus a real stdio MCP process talking
// to the real control server. Skipped when no Chrome is available. Linux/headless Chrome only: not Electron, not Windows.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { spawn, spawnSync } = require('node:child_process');
const { createHandler, start } = require('../src/control');

const chrome = ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((p) => fs.existsSync(p));
// Markup below is copied in shape from the real renderer templates (intake form, interview medicine use and consent,
// report editor fields) so the controls are the app's own kinds: wrapped labels, name-only fields, number and date
// inputs, radios whose only label is wrapping text, data-* row identifiers and submit buttons.
const PAGE = `<!doctype html><title>t</title><body><script>var page='intake'</script>
<div id=root>
<form data-referral-commit="0" class="form" onsubmit="event.preventDefault();log.push('commit')">
 <label>Name<input name="name" value=""></label>
 <label>Sex<input name="sex" value=""></label>
 <label>Referral date<input name="referral_date" value=""></label>
 <label>Phone<input name="phone" value=""></label>
 <label>Reviewing pharmacist<input name="clinical_reviewer" value=""></label>
 <label>Medicines source page<input name="clinical_page_medicines" type="number" min="0" step="1" value="0"></label>
 <label>Prescribed medicines / directions (one medicine per line)<textarea name="clinical_medicines" rows="4"></textarea></label>
 <label>Allergy documentation state<select name="clinical_allergies_status"><option value="unknown" selected>Unknown / not specified</option><option value="explicit_none">Explicitly documented none</option><option value="listed">Allergies listed</option></select></label>
 <label><input type=checkbox name=distinct> Different person from an existing patient</label>
 <button>Confirm and add patient</button>
</form>
<fieldset><legend>Medicine use</legend>
 <label><input type="radio" name="use-found-0" data-use-field="use_status" data-use-table="found" data-row="0" value="taking"> Taking</label>
 <label><input type="radio" name="use-found-0" data-use-field="use_status" data-use-table="found" data-row="0" value="not_using"> Not using</label>
 <label><input type="radio" name="use-found-1" data-use-field="use_status" data-use-table="found" data-row="1" value="taking"> Taking</label>
</fieldset>
<select data-usage-preset="found" data-row="0" aria-label="Usage preset row 1"><option value="">--</option><option value="daily">Once daily</option></select>
<label class="consent-check"><input type="checkbox" data-field="consent" data-prop="signed"> Consent signed</label>
<input type="date" data-field="consent" data-prop="date">
<textarea data-field="gp_notes"></textarea>
<input id="interview-search" type="search"><select id="interview-patient"><option value="" selected disabled>Choose</option><option value="7">Synthetic Person</option></select>
<button id=ack>Acknowledge reviewed discrepancies</button><button id=pick>Choose PDFs</button><button id=opn>Open original PDF</button>
<button id=sig>Sign consent form</button><button id=snd>Send offer</button><button id=mk>Mark report sent</button><button id=ai>Draft with AI</button>
<button id=sv>Save</button><button id=today>Set to today (21/11/2026)</button><button id=off disabled>Disabled one</button>
<div style="display:none"><button id=hid>Hidden</button></div>
<label>API key<input id=tk value="abc"></label><label>Password<input type=password id=p value="hunter2"></label>
<p id=leak>Report sha 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef and https://example.invalid/oauth/authorize?code=ZZZ12345 here</p>
</div>
<script>window.log=[];
document.addEventListener('input',e=>log.push('input:'+(e.target.name||e.target.dataset.field||e.target.id)+'='+e.target.value));
document.addEventListener('change',e=>log.push('change:'+(e.target.name||e.target.dataset.prop||e.target.id)+'='+(e.target.type==='checkbox'||e.target.type==='radio'?e.target.checked:e.target.value)));
document.addEventListener('click',e=>{ if(e.target.closest('button')) log.push('click:'+(e.target.id||e.target.textContent.trim())); });</script></body>`;

async function launch(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'chr-'));
  const proc = spawn(chrome, ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0', '--user-data-dir=' + dir, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  t.after(async () => { proc.kill('SIGKILL'); await new Promise((r) => setTimeout(r, 300)); fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }); });
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = ''; const timer = setTimeout(() => reject(new Error('chrome start timeout')), 20000);
    proc.stderr.on('data', (d) => { buf += d; const m = buf.match(/ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/\S+/); if (m) { clearTimeout(timer); resolve(m[0]); } });
  });
  const port = new URL(wsUrl).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(targets.find((x) => x.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
  const send = (method, params) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send('Page.enable');
  await send('Page.navigate', { url: 'data:text/html;charset=utf-8,' + encodeURIComponent(PAGE) });
  await new Promise((r) => setTimeout(r, 500));
  const evaluate = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description?.split('\n')[0].replace(/^Error: /, '') || 'eval failed');
    return r.result.result.value;
  };
  t.after(() => ws.close());
  return { evaluate };
}


test('uiScript on the app markup: snapshot, fill every native control kind, readback, refusals', { skip: !chrome }, async (t) => {
  const { uiScript } = require('../src/control');
  const { evaluate } = await launch(t);
  const snap = await evaluate(uiScript('snapshot', { max: 3000 }));
  assert.equal(snap.screen, 'intake');
  assert.match(snap.controls[0].ref, /^s1\.\d+$/);
  const labelled = (label, extra = () => true) => snap.controls.find((c) => c.label === label && extra(c)) || assert.fail('no control labelled ' + label + '; have ' + JSON.stringify(snap.controls.map((c) => c.label)));
  const act = (op, c, more) => evaluate(uiScript(op, { ref: c.ref, ...more }));
  // wrapped-label inputs, number input, textarea, select by text and by value
  assert.equal((await act('fill', labelled('Name'), { value: 'Synthetic Person' })).value, 'Synthetic Person');
  assert.equal((await act('fill', labelled('Medicines source page'), { value: '1' })).value, '1');
  assert.equal((await act('fill', labelled('Prescribed medicines / directions (one medicine per line)'), { value: 'aspirin 100 mg daily\nmetoprolol 50 mg daily' })).ok, true);
  assert.equal((await act('fill', labelled('Allergy documentation state'), { value: 'Explicitly documented none' })).value, 'explicit_none');
  assert.equal((await act('fill', labelled('Usage preset row 1'), { value: 'daily' })).value, 'daily');
  // radios share a label, so the data-row/table attributes must tell them apart
  const taking0 = snap.controls.find((c) => c.type === 'radio' && c.label === 'Taking' && c.data.row === '0');
  const taking1 = snap.controls.find((c) => c.type === 'radio' && c.label === 'Taking' && c.data.row === '1');
  assert.ok(taking0 && taking1 && taking0.ref !== taking1.ref);
  assert.equal(taking0.data['use-table'], 'found');
  assert.equal((await act('fill', taking0, { checked: true })).checked, true);
  await assert.rejects(act('fill', taking0, { checked: false }), /radio button cannot be unticked/);
  // checkboxes (wrapped label and data-field checkbox), date and search inputs
  assert.equal((await act('fill', labelled('Consent signed'), { checked: true })).checked, true);
  assert.equal((await act('fill', snap.controls.find((c) => c.type === 'date'), { value: '2026-11-21' })).value, '2026-11-21');
  assert.equal((await act('fill', snap.controls.find((c) => c.type === 'search'), { value: 'Synthetic' })).ok, true);
  assert.equal((await act('fill', snap.controls.find((c) => c.id === 'interview-patient'), { value: 'Synthetic Person' })).value, '7');
  // the renderer's own listeners saw real input/change events
  const log = await evaluate('log');
  for (const want of ['input:name=Synthetic Person', 'change:clinical_allergies_status=explicit_none', 'change:use-found-0=true', 'change:signed=true', 'change:date=2026-11-21', 'change:interview-patient=7'])
    assert.ok(log.includes(want), want + ' in ' + JSON.stringify(log));
  // readback through a fresh snapshot
  const back = await evaluate(uiScript('snapshot', { max: 100 }));
  assert.equal(back.controls.find((c) => c.label === 'Name').value, 'Synthetic Person');
  assert.equal(back.controls.find((c) => c.type === 'radio' && c.data.row === '0' && c.label === 'Taking').checked, true);
  assert.equal(back.controls.find((c) => c.label === 'Allergy documentation state').value, 'explicit_none');
  // secrets: sensitive fields hidden and unfillable, token-shaped text redacted
  const pw = back.controls.find((c) => c.type === 'password'), key = back.controls.find((c) => c.id === 'tk');
  assert.equal(pw.sensitive, true); assert.equal(pw.value, undefined); assert.equal(key.sensitive, true); assert.equal(key.value, undefined);
  await assert.rejects(act('fill', pw, { value: 'x' }), /Sensitive field refused/);
  await assert.rejects(act('fill', key, { value: 'x' }), /Sensitive field refused/);
  const full = await evaluate(uiScript('snapshot', { max: 5000 }));
  assert.doesNotMatch(full.text, /0123456789abcdef0123456789abcdef/);
  assert.doesNotMatch(full.text, /oauth\/authorize/);
  assert.match(full.text, /hex removed/); assert.match(full.text, /auth link removed/);
  await assert.rejects(evaluate(uiScript('guard')), /Refused/);
  assert.equal(await evaluate("document.getElementById('p').value"), 'hunter2');
  // blocked controls: flagged in the snapshot and refused on click
  for (const id of ['ack', 'pick', 'opn', 'sig', 'snd', 'mk', 'ai']) {
    const c = full.controls.find((x) => x.id === id);
    assert.equal(c.blocked, true, id + ' should be flagged');
    await assert.rejects(evaluate(uiScript('click', { ref: c.ref })), /Blocked/, id);
  }
  for (const id of ['sv', 'today']) assert.equal(full.controls.find((x) => x.id === id).blocked, undefined, id);
  await assert.rejects(evaluate(uiScript('click', { ref: full.controls.find((x) => x.id === 'off').ref })), /disabled/);
  assert.ok(!full.controls.some((c) => c.id === 'hid'));
  // allowed clicks, including the submit button of the intake form
  await evaluate(uiScript('click', { ref: full.controls.find((x) => x.id === 'sv').ref }));
  await evaluate(uiScript('click', { ref: full.controls.find((x) => x.label === 'Confirm and add patient').ref }));
  const after = await evaluate('log');
  assert.ok(after.includes('click:sv') && after.includes('commit'));
  assert.ok(!after.some((x) => /click:(ack|pick|opn|sig|snd|mk|ai)$/.test(x)), 'no blocked control was clicked');
});

test('refs are rejected after a newer snapshot, a re-render, a screen change or a label change', { skip: !chrome }, async (t) => {
  const { uiScript } = require('../src/control');
  const { evaluate } = await launch(t);
  const first = await evaluate(uiScript('snapshot', { max: 100 }));
  const name = first.controls.find((c) => c.label === 'Name');
  // 1. a newer snapshot retires every older ref
  const second = await evaluate(uiScript('snapshot', { max: 100 }));
  await assert.rejects(evaluate(uiScript('fill', { ref: name.ref, value: 'x' })), /Stale reference/);
  const name2 = second.controls.find((c) => c.label === 'Name');
  // 2. a re-render replaces the elements
  await evaluate("(() => { const r = document.getElementById('root'); r.innerHTML = r.innerHTML; })()");
  await assert.rejects(evaluate(uiScript('fill', { ref: name2.ref, value: 'x' })), /Stale reference/);
  // 3. a screen change with the controls still on the page
  const third = await evaluate(uiScript('snapshot', { max: 100 }));
  await evaluate("page = 'report'");
  await assert.rejects(evaluate(uiScript('click', { ref: third.controls.find((c) => c.id === 'sv').ref })), /screen changed/);
  await evaluate("page = 'intake'");
  // 4. same element, different meaning
  const fourth = await evaluate(uiScript('snapshot', { max: 100 }));
  await evaluate("document.getElementById('sv').textContent = 'Save as final'");
  await assert.rejects(evaluate(uiScript('click', { ref: fourth.controls.find((c) => c.id === 'sv').ref })), /control changed/);
  // 5. malformed refs
  for (const ref of ['u1', 's0.1', 's99999.1', 'x', '']) await assert.rejects(evaluate(uiScript('click', { ref })), /Stale reference/);
  assert.ok(!(await evaluate('log')).some((x) => x.startsWith('click:')), 'nothing was clicked');
});

test('stdio MCP -> control server (fallback port, endpoint file, identity) -> real DOM', { skip: !chrome }, async (t) => {
  const { evaluate } = await launch(t);
  const squatter = http.createServer((q, s) => s.end('other'));
  const fixed = process.env.HMR_SMOKE_DATA ? 18768 : 8768;
  const squatting = await new Promise((r) => { squatter.on('error', () => r(false)); squatter.listen(fixed, '127.0.0.1', () => r(true)); });
  t.after(() => squatter.close());
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'prof-'));
  const dataDir = path.join(profile, 'HMR-Desk-data'); fs.mkdirSync(dataDir);
  t.after(() => fs.rmSync(profile, { recursive: true, force: true }));
  const win = new Proxy({}, { get: (_, key) => (key === 'webContents' ? new Proxy({ executeJavaScript: (code) => evaluate(code) }, { get: (o, k) => o[k] ?? (() => false) }) : () => false) });
  const ctx = { dataDir, getWindow: () => win, views: {}, state: {}, armed: {}, oneOffs: {}, results: [] };
  const server = start(ctx);
  t.after(() => server.close());
  await new Promise((r) => { const w = () => (fs.existsSync(path.join(dataDir, 'control_endpoint.json')) ? r() : setTimeout(w, 50)); w(); });
  const rec = JSON.parse(fs.readFileSync(path.join(dataDir, 'control_endpoint.json'), 'utf8'));
  if (squatting) { assert.equal(rec.fallback, true); assert.notEqual(rec.url, 'http://127.0.0.1:' + fixed); }
  assert.ok(!JSON.stringify(rec).includes(fs.readFileSync(path.join(dataDir, 'app_control_token'), 'utf8').trim()), 'token must not be in the endpoint file');
  const child = spawn(process.execPath, [path.join(__dirname, '../mcp/hmr-desk-mcp.js')], { env: { ...process.env, USERPROFILE: profile, HMR_CONTROL: '' }, stdio: ['pipe', 'pipe', 'inherit'] });
  t.after(() => child.kill());
  const lines = []; let buf = '';
  child.stdout.on('data', (d) => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { lines.push(JSON.parse(buf.slice(0, i))); buf = buf.slice(i + 1); } });
  const rpc = async (id, method, params) => { child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); for (let k = 0; k < 200; k++) { const hit = lines.find((l) => l.id === id); if (hit) return hit; await new Promise((r) => setTimeout(r, 25)); } throw new Error('no reply'); };
  const tool = async (id, name, args) => { const r = await rpc(id, 'tools/call', { name, arguments: args }); return { err: !!r.result.isError, text: r.result.content[0].text }; };
  assert.ok((await rpc(1, 'tools/list')).result.tools.some((x) => x.name === 'app_ui_fill'));
  assert.equal(JSON.parse((await tool(2, 'app_identity', {})).text).data_dir, dataDir);
  const snap = JSON.parse((await tool(3, 'app_ui_snapshot', { max: 200 })).text);
  const ref = (label) => snap.controls.find((c) => c.label === label).ref;
  assert.equal(JSON.parse((await tool(4, 'app_ui_fill', { ref: ref('Name'), value: 'Synthetic Person' })).text).ok, true);
  assert.equal((await tool(5, 'app_ui_fill', { ref: ref('Name') })).err, true);
  assert.equal((await tool(6, 'app_ui_fill', { ref: ref('Password'), value: 'x' })).err, true);
  assert.match((await tool(7, 'app_ui_click', { ref: snap.controls.find((c) => c.id === 'snd').ref })).text, /Blocked/);
  assert.equal((await tool(8, 'app_ui_click', { ref: snap.controls.find((c) => c.label === 'Confirm and add patient').ref })).err, false);
  const log = await evaluate('log');
  assert.ok(log.includes('input:name=Synthetic Person') && log.includes('commit') && !log.includes('click:snd'));
  // stale snapshot through the bridge
  await tool(9, 'app_ui_snapshot', {});
  assert.match((await tool(10, 'app_ui_click', { ref: snap.controls.find((c) => c.id === 'sv').ref })).text, /Stale reference/);
  // the screenshot route refuses a screen that shows a secret (the page above shows a key value and a token-like string)
  assert.match((await tool(11, 'app_screenshot', {})).text, /Refused|sign-in/);
  fs.writeFileSync(path.join(dataDir, 'control_endpoint.json'), JSON.stringify({ url: rec.url, pid: 2 ** 22 + 12345 }));
  const stale = await tool(12, 'app_ui_snapshot', {});
  assert.equal(stale.err, true); assert.match(stale.text, /stale/);
});

test('run-plan.js drives a whole fill, readback and screenshot plan through the stdio MCP, and stops on a refusal', { skip: !chrome }, async (t) => {
  const { run } = require('../mcp/run-plan');
  const { evaluate } = await launch(t);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'prof-'));
  const dataDir = path.join(profile, 'HMR-Desk-data'); fs.mkdirSync(dataDir);
  t.after(() => fs.rmSync(profile, { recursive: true, force: true }));
  const win = new Proxy({}, { get: (_, key) => (key === 'webContents' ? new Proxy({ executeJavaScript: (code) => evaluate(code), capturePage: async () => ({ toPNG: () => Buffer.from('png-bytes') }) }, { get: (o, k) => o[k] ?? (() => false) }) : () => false) });
  const server = start({ dataDir, getWindow: () => win, views: {}, state: {}, armed: {}, oneOffs: {}, results: [] });
  t.after(() => server.close());
  await new Promise((r) => { const w = () => (fs.existsSync(path.join(dataDir, 'control_endpoint.json')) ? r() : setTimeout(w, 50)); w(); });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'plan-')); t.after(() => fs.rmSync(out, { recursive: true, force: true }));
  const planFile = path.join(out, 'plan.json');
  const saved = process.env.USERPROFILE; process.env.USERPROFILE = profile; t.after(() => { process.env.USERPROFILE = saved; });
  const good = { steps: [
    { tool: 'app_identity' },
    { tool: 'app_ui_snapshot', save: 'snap1.json' },
    { name: 'fill name', tool: 'app_ui_fill', find: { label: 'Name' }, args: { value: 'Synthetic Person' } },
    { tool: 'app_ui_snapshot' },
    { name: 'readback', tool: 'app_ui_snapshot', expect: 'Synthetic Person' },
    { name: 'blocked send', tool: 'app_ui_click', find: { id: 'snd' }, optional: true },
    { name: 'ambiguous find', tool: 'app_ui_click', find: { label: 'Taking' }, optional: true },
    { name: 'row 1 radio', tool: 'app_ui_fill', find: { label: 'Taking', 'data.row': '1' }, args: { checked: true } },
  ] };
  fs.writeFileSync(planFile, JSON.stringify(good));
  const result = await run(planFile, path.join(out, 'o1'));
  assert.equal(result.failed, false);
  const by = Object.fromEntries(result.report.map((r) => [r.name, r]));
  assert.equal(by['fill name'].ok, true); assert.equal(by['readback'].ok, true);
  assert.equal(by['blocked send'].ok, false); assert.match(by['blocked send'].problem, /Blocked/);
  assert.equal(by['ambiguous find'].ok, false); assert.match(by['ambiguous find'].problem, /matched 2/);
  assert.equal(by['row 1 radio'].ok, true);
  assert.ok(!(await evaluate('log')).includes('click:snd'));
  assert.ok(fs.existsSync(path.join(out, 'o1', 'snap1.json')));
  // a non-optional refusal stops the plan before later steps run
  fs.writeFileSync(planFile, JSON.stringify({ steps: [{ tool: 'app_ui_snapshot' }, { tool: 'app_ui_click', find: { id: 'mk' } }, { tool: 'app_identity' }] }));
  const stopped = await run(planFile, path.join(out, 'o2'));
  assert.equal(stopped.failed, true); assert.equal(stopped.report.length, 2);
  // saved results land in the output folder
  fs.writeFileSync(planFile, JSON.stringify({ steps: [{ tool: 'app_ui_snapshot' }, { tool: 'app_identity', save: 'id.json' }] }));
  assert.equal((await run(planFile, path.join(out, 'o3'))).failed, false);
});
