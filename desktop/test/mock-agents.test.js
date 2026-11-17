const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');

test('mock agent endpoints keep keys private and persist selections', async () => {
  const child = spawn(process.execPath, [path.join(__dirname, '../dev/mock-api.js')], {
    env: { ...process.env, PORT: '0' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  try {
    const address = await new Promise((resolve, reject) => {
      child.once('error', reject);
      child.stdout.once('data', (data) => resolve(data.toString().trim()));
      child.once('exit', (code) => reject(Error(`Mock exited: ${code}`)));
    });
    const base = `http://127.0.0.1:${address.split(' ').pop()}`;
    const post = (url, body) =>
      fetch(base + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then((r) => r.json());
    await post('/api/agents', { name: 'API', type: 'api', enabled: true, key: 'secret' });
    await post('/api/agents/select', { default: 'API', per_step: { report_draft: 'API' } });
    const data = await fetch(base + '/api/agents').then((r) => r.json());
    assert.equal(data.default, 'API');
    assert.equal(data.per_step.report_draft, 'API');
    assert.equal(data.agents.find((a) => a.name === 'API').has_key, true);
    assert.equal(JSON.stringify(data).includes('secret'), false);
    assert.equal((await post('/api/agents/test', { name: 'API' })).reply, 'OK');
    await post('/api/agents/delete', { name: 'API' });
    assert.equal((await fetch(base + '/api/agents').then((r) => r.json())).default, null);
  } finally {
    child.kill();
  }
});
