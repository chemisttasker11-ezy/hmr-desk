const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { freePort, bundledEngine, start } = require('../src/engine-owner');

test('startup resources use the packaged engine not a developer Python runtime', () => {
  assert.equal(bundledEngine('C:\\Program Files\\HMR Desk\\resources'),
    path.join('C:\\Program Files\\HMR Desk\\resources', 'engine', 'hmr-engine', 'hmr-engine.exe'));
});

test('engine chooses ephemeral unprivileged loopback port', async () => {
  const port = await freePort();
  assert.ok(Number.isInteger(port) && port > 0 && port <= 65535);
});

test('missing bundled executable fails explicitly and never starts a system runtime', async () => {
  await assert.rejects(start({ resourcesPath: path.join(__dirname, 'unbundled'),
    dataDir: '/no-special-data', workspace: '/no-special-workspace', config: {} }), /Bundled HMR clinical engine is missing/);
});
