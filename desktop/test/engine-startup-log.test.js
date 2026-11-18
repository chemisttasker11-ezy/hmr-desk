const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { start, lifecycleLog, LOG_NAME } = require('../src/engine-owner');

function temp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-startlog-')); }

test('lifecycle log keeps only short safe values and never throws', () => {
  const dir = temp();
  const log = lifecycleLog(dir);
  log('probe', { code: 3, secret: 'C:\\Users\\someone\\token abc', none: null });
  const text = fs.readFileSync(path.join(dir, LOG_NAME), 'utf8');
  assert.match(text, /probe code=3 secret=other none=-/);
  assert.ok(!text.includes('someone') && !text.includes('token'));
  assert.doesNotThrow(() => lifecycleLog(path.join(dir, 'missing', 'deeper'))('probe'));
  assert.doesNotThrow(() => lifecycleLog(null)('probe'));
});

test('missing engine is recorded without changing the error', async () => {
  const dir = temp();
  await assert.rejects(start({ resourcesPath: path.join(dir, 'none'), dataDir: dir,
    workspace: path.join(dir, 'ws'), config: {} }), /Bundled HMR clinical engine is missing/);
  assert.match(fs.readFileSync(path.join(dir, LOG_NAME), 'utf8'), / engine_missing/);
});

test('early engine exit records code, timing and the failure reason, not arguments or paths',
  { skip: process.platform === 'win32' }, async () => {
    const dir = temp();
    const exe = path.join(dir, 'res', 'engine', 'hmr-engine', 'hmr-engine.exe');
    fs.mkdirSync(path.dirname(exe), { recursive: true });
    fs.writeFileSync(exe, '#!/bin/sh\nexit 3\n', { mode: 0o755 });
    await assert.rejects(start({ resourcesPath: path.join(dir, 'res'), dataDir: path.join(dir, 'data'),
      workspace: path.join(dir, 'ws'), config: {}, timeoutMs: 5000 }), /exited during startup/);
    const text = fs.readFileSync(path.join(dir, 'data', LOG_NAME), 'utf8');
    assert.match(text, / spawned pid=\d+ timeout_ms=5000/);
    assert.match(text, / child_exit code=3 signal=- /);
    assert.match(text, / start_failed reason=exited /);
    assert.ok(!text.includes(dir) && !/--port|--data-dir|HMR_SESSION/.test(text));
  });
