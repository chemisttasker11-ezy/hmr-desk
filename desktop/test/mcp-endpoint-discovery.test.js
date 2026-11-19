const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { call } = require('../mcp/hmr-desk-mcp');
const { start } = require('../src/engine-owner');

const reader = files => async file => {
  const name = path.basename(file);
  if (name in files) return files[name];
  const error = new Error('missing'); error.code = 'ENOENT'; throw error;
};
const fakeFetch = urls => async url => { urls.push(url); return { ok: true, status: 200, json: async () => ({ ok: true }) }; };
const withEnv = async (patch, run) => {
  const saved = {}; for (const k of Object.keys(patch)) { saved[k] = process.env[k]; if (patch[k] === null) delete process.env[k]; else process.env[k] = patch[k]; }
  try { await run(); } finally { for (const k of Object.keys(saved)) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; } }
};

test('recorded live engine endpoint is used when HMR_API is unset', async () => {
  await withEnv({ HMR_API: null, USERPROFILE: os.tmpdir() }, async () => {
    const urls = [];
    const rec = JSON.stringify({ url: 'http://127.0.0.1:59177', pid: process.pid });
    await call('hmr_status', {}, fakeFetch(urls), reader({ api_token: 'tk', 'engine_endpoint.json': rec }));
    assert.ok(urls[0].startsWith('http://127.0.0.1:59177/'), urls[0]);
  });
});

test('HMR_API overrides the recorded endpoint, and no record keeps the development default', async () => {
  await withEnv({ HMR_API: 'http://127.0.0.1:61000', USERPROFILE: os.tmpdir() }, async () => {
    const urls = [];
    const rec = JSON.stringify({ url: 'http://127.0.0.1:59177', pid: process.pid });
    await call('hmr_status', {}, fakeFetch(urls), reader({ api_token: 't', 'engine_endpoint.json': rec }));
    assert.ok(urls[0].startsWith('http://127.0.0.1:61000/'));
  });
  await withEnv({ HMR_API: null, USERPROFILE: os.tmpdir() }, async () => {
    const urls = [];
    await call('hmr_status', {}, fakeFetch(urls), reader({ api_token: 't' }));
    assert.ok(urls[0].startsWith('http://127.0.0.1:8767/'));
  });
});

test('stale or invalid endpoint record fails loudly and never falls back to a guessed port', async () => {
  await withEnv({ HMR_API: null, USERPROFILE: os.tmpdir() }, async () => {
    const urls = [];
    const dead = JSON.stringify({ url: 'http://127.0.0.1:59177', pid: 2147483646 });
    await assert.rejects(call('hmr_status', {}, fakeFetch(urls), reader({ api_token: 't', 'engine_endpoint.json': dead })), /stale/);
    const remote = JSON.stringify({ url: 'http://example.test:80', pid: process.pid });
    await assert.rejects(call('hmr_status', {}, fakeFetch(urls), reader({ api_token: 't', 'engine_endpoint.json': remote })), /invalid/);
    assert.equal(urls.length, 0);
    const down = async () => { throw new Error('refused'); };
    const live = JSON.stringify({ url: 'http://127.0.0.1:59177', pid: process.pid });
    await assert.rejects(call('hmr_status', {}, down, reader({ api_token: 't', 'engine_endpoint.json': live })), /engine_endpoint\.json/);
  });
});

test('app does not write the endpoint record into a data dir it did not start, and the record never holds the token', { skip: process.platform === 'win32' }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-ep-'));
  const res = path.join(root, 'res'), exeDir = path.join(res, 'engine', 'hmr-engine'), data = path.join(root, 'data');
  fs.mkdirSync(exeDir, { recursive: true });
  const exe = path.join(exeDir, 'hmr-engine.exe');
  fs.writeFileSync(exe, `#!${process.execPath}\nconst http=require('http');const port=Number(process.env.HMR_API_PORT);\nhttp.createServer((q,r)=>{r.setHeader('content-type','application/json');if(q.url==='/api/engine/stop'){r.end('{}');process.exit(0)}r.end(JSON.stringify({ready:true,engine_version:'0.1.0'}))}).listen(port,'127.0.0.1');\n`, { mode: 0o755 });
  fs.mkdirSync(data, { recursive: true });
  fs.writeFileSync(path.join(data, 'engine_endpoint.json'), '{"url":"http://127.0.0.1:1","pid":1}');
  const config = {};
  const owner = await start({ resourcesPath: res, dataDir: data, workspace: path.join(data, 'ws'), config, timeoutMs: 8000 });
  const raw = fs.readFileSync(path.join(data, 'engine_endpoint.json'), 'utf8');
  const rec = JSON.parse(raw);
  assert.equal(rec.url, owner.url);
  assert.equal(rec.pid, owner.child.pid);
  assert.deepEqual(Object.keys(rec).sort(), ['app_pid', 'pid', 'url', 'written_at']);
  await owner.stop();
  assert.equal(fs.existsSync(path.join(data, 'engine_endpoint.json')), false);
});

test('a live process id with a rejecting endpoint (reused id or another profile) fails loudly and sends no data request', async () => {
  await withEnv({ HMR_API: null, USERPROFILE: os.tmpdir() }, async () => {
    const urls = [];
    const rejecting = async url => { urls.push(url); return { ok: false, status: 401, json: async () => ({}) }; };
    const live = JSON.stringify({ url: 'http://127.0.0.1:59177', pid: process.pid });
    await assert.rejects(call('hmr_patients', {}, rejecting, reader({ api_token: 'tk', 'engine_endpoint.json': live })), /another profile/);
    assert.deepEqual(urls, ['http://127.0.0.1:59177/api/health']);
  });
});

test('real stdio client: server answers tools/list and reports a stale record as a tool error', { skip: process.platform === 'win32' }, async () => {
  const { spawn } = require('node:child_process');
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-stdio-'));
  const dir = path.join(home, 'HMR-Desk-data'); fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, 'api_token'), 'tk');
  fs.writeFileSync(path.join(dir, 'engine_endpoint.json'), JSON.stringify({ url: 'http://127.0.0.1:59177', pid: 2147483646 }));
  const env = { ...process.env, USERPROFILE: home, HOME: home }; delete env.HMR_API;
  const child = spawn(process.execPath, [path.join(__dirname, '..', 'mcp', 'hmr-desk-mcp.js')], { env, stdio: ['pipe', 'pipe', 'ignore'] });
  const lines = []; let buffer = '';
  child.stdout.on('data', d => { buffer += d; let i; while ((i = buffer.indexOf('\n')) >= 0) { lines.push(JSON.parse(buffer.slice(0, i))); buffer = buffer.slice(i + 1); } });
  const waitFor = async n => { for (let i = 0; i < 100 && lines.length < n; i++) await new Promise(r => setTimeout(r, 50)); assert.ok(lines.length >= n, 'no reply'); };
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) + '\n'); await waitFor(1);
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'hmr_status', arguments: {} } }) + '\n'); await waitFor(2);
  child.kill();
  assert.ok(lines[0].result.tools.some(t => t.name === 'hmr_status'));
  assert.equal(lines[1].result.isError, true);
  assert.match(lines[1].result.content[0].text, /stale/);
});
