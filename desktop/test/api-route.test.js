const test = require('node:test');
const assert = require('node:assert/strict');
const { isCanonicalApiRoute } = require('../src/api-route');

test('dot-segment, encoded and doubled-slash routes are rejected', () => {
  for (const bad of ['/api/x/../records/export', '/api/%2e%2e/records/export', '/api/%2E%2E/records/export',
    '/api//records/export', '/api/records/./export', '/api/records/..', '/api/x\\..\\records', '/api/x%2f..%2frecords',
    'api/patients', '/other/api/x', '', null, undefined, 5])
    assert.equal(isCanonicalApiRoute(bad), false, String(bad));
});

test('ordinary renderer routes stay allowed', () => {
  for (const good of ['/api/patients', '/api/patients/12/pathology-records', '/api/records/status',
    '/api/medicines/status', '/api/patients?archived=1', '/api/patients/abc-123/interview'])
    assert.equal(isCanonicalApiRoute(good), true, good);
});

test('main.js applies the check before the blocklist and inside api()', () => {
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'main.js'), 'utf8');
  assert.match(src, /ipcMain\.handle\('api'[\s\S]{0,200}isCanonicalApiRoute\(p\)/);
  assert.match(src, /async function api\([\s\S]{0,400}isCanonicalApiRoute\(apiPath\)/);
});
