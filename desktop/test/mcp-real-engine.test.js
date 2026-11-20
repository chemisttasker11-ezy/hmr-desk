// The MCP against the REAL Python engine process (not a fake fetch): API port, X-HMR-Token auth from the api_token the
// engine writes, JSON routes, the endpoint record, and the webhook port that must never be mistaken for the API.
// Skipped when python3 or the engine's modules are unavailable. Linux only; not the packaged Windows engine.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const net = require('node:net');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { call } = require('../mcp/hmr-desk-mcp');

const engineDir = path.join(__dirname, '..', '..', 'HMR Desk', 'engine');
const have = spawnSync('python3', ['-c', 'import service'], { cwd: engineDir, env: process.env }).status === 0;
const freePort = () => new Promise((r) => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });

test('hmr_* reads work against the real engine through the recorded endpoint, and fail loudly when it is stale or wrong', { skip: !have }, async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eng-'));
  const [api, hook] = [await freePort(), await freePort()];
  const token = 'tok' + 'x'.repeat(40);
  const child = spawn('python3', ['engine_main.py', '--data-dir', dir, '--workspace', path.join(dir, 'ws'), '--port', String(api)], {
    cwd: engineDir, stdio: 'ignore',
    env: { ...process.env, LOCALAPPDATA: dir, APPDATA: dir, USERPROFILE: dir, HMR_DATA_DIR: dir, HMR_WORKSPACE: path.join(dir, 'ws'), HMR_SESSION_TOKEN: token, HMR_API_PORT: String(api), HMR_WEBHOOK_PORT: String(hook) },
  });
  t.after(() => { child.kill('SIGKILL'); fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }); });
  let up = false;
  for (let i = 0; i < 80 && !up; i++) { try { up = (await fetch(`http://127.0.0.1:${api}/api/health`, { headers: { 'X-HMR-Token': token } })).ok; } catch {} if (!up) await new Promise((r) => setTimeout(r, 250)); }
  assert.ok(up, 'engine did not become ready');
  // the file the packaged app writes beside the token (engine-owner.js)
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'prof-'));
  t.after(() => fs.rmSync(profile, { recursive: true, force: true }));
  const root = path.join(profile, 'HMR-Desk-data'); fs.mkdirSync(root);
  fs.copyFileSync(path.join(dir, 'api_token'), path.join(root, 'api_token'));
  fs.writeFileSync(path.join(root, 'engine_endpoint.json'), JSON.stringify({ url: `http://127.0.0.1:${api}`, pid: child.pid }));
  const saved = { u: process.env.USERPROFILE, a: process.env.HMR_API };
  process.env.USERPROFILE = profile; delete process.env.HMR_API;
  t.after(() => { process.env.USERPROFILE = saved.u; if (saved.a === undefined) delete process.env.HMR_API; else process.env.HMR_API = saved.a; });
  const read = async (name, args = {}) => JSON.parse((await call(name, args))[0].text);
  const status = await read('hmr_status');
  assert.equal(status.outbox_mode, 'test');
  assert.ok('patients' in status && 'messages' in status);
  assert.equal(typeof (await read('hmr_patients')), 'object');
  assert.equal(typeof (await read('hmr_settings_get')), 'object');
  // the webhook port is HTML, never the API: pointing HMR_API at it must fail, not return data
  process.env.HMR_API = `http://127.0.0.1:${hook}`;
  await assert.rejects(call('hmr_status', {}), /engine is not running|Unexpected token|not valid JSON|JSON/);
  // wrong token file: rejected by the engine
  delete process.env.HMR_API;
  fs.writeFileSync(path.join(root, 'api_token'), 'wrong');
  await assert.rejects(call('hmr_status', {}), /not responding|401|Unauthorized|engine is not running/);
  fs.writeFileSync(path.join(root, 'api_token'), fs.readFileSync(path.join(dir, 'api_token')));
  // stale: engine process gone
  child.kill('SIGKILL');
  await new Promise((r) => child.once('exit', r));
  await assert.rejects(call('hmr_status', {}), /stale|not responding/);
});
