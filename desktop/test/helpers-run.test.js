const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const helpers = require('../src/helpers-run');
const mimsSource = [
  'const sleep = ms => new Promise(r => setTimeout(r, ms));',
  'async function add(input, name) {}', 'async function details() {}', 'async function runOne(list) {}',
  'for (const [i, list] of MIMS_LISTS.entries()) {}', "const b = document.createElement('button');",
].join('\n');

test('saved interactions and filled claims report their matching tasks only', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-report-'));
  const oldPatterns = process.env.HMR_SMOKE_PATTERNS,
    oldUrl = process.env.HMR_SMOKE_URL;
  process.env.HMR_SMOKE_PATTERNS = JSON.stringify(['https://example.com/*']);
  process.env.HMR_SMOKE_URL = 'https://example.com/';
  try {
    await fs.mkdir(path.join(root, 'mims'));
    await fs.writeFile(path.join(root, 'mims', 'content.js'), mimsSource);
    let token;
    const emims = { getURL: () => 'https://example.com/check', executeJavaScript: async script => { token = /const token = "([^"]+)"/.exec(script)?.[1]; }, isDestroyed: () => false };
    const ppa = { getURL: () => 'https://example.com/claim' };
    const calls = [];
    const waitingTasks = {
      emims: [
        { id: 'a', patient_id: 1 },
        { id: 'b', patient_id: 2 },
      ],
      ppa: [{ id: 'c', patient_id: 2 }],
    };
    const run = helpers({
      views: { emims: { webContents: emims }, ppa: { webContents: ppa } },
      armed: { emims: true, ppa: true },
      queues: {
        emims: [
          { id: 1, folder: 'One', folder_path: root, meds_revision: 'a'.repeat(64) },
          { folder: 'Guest', folder_path: root },
        ],
        ppa: [{ id: 2 }],
      },
      saved: {},
      sites: { emims: { dir: 'mims', key: 'MIMS_LISTS' }, ppa: { dir: 'ppa' } },
      config: { base: root },
      dataDir: root,
      waitingTasks,
      notify() {},
      api: async (...args) => calls.push(args),
    });
    await run.inject('emims');
    const download = (filename) => ({ filename, url: 'data:text/plain,hello', hmrRun: token });
    assert.equal((await run.saveHelper({ sender: emims }, download('HMR Interactions/One.txt'))).error, undefined);
    assert.equal((await run.saveHelper({ sender: emims }, download('HMR Interactions/Guest.txt'))).error, undefined);
    assert.equal((await run.saveHelper({ sender: ppa }, { type: 'filled', index: 0 })).ok, true);
    assert.match(calls[0][2].mims_result, /^MIMS interactions generated a{64} [a-f0-9]{64}\.txt$/);
    assert.deepEqual(
      calls.map((call) => call[1]),
      ['/api/run/a/result', '/api/run/c/result'],
    );
    assert.deepEqual(
      waitingTasks.emims.map((task) => task.id),
      ['b'],
    );
  } finally {
    if (oldPatterns === undefined) delete process.env.HMR_SMOKE_PATTERNS;
    else process.env.HMR_SMOKE_PATTERNS = oldPatterns;
    if (oldUrl === undefined) delete process.env.HMR_SMOKE_URL;
    else process.env.HMR_SMOKE_URL = oldUrl;
    await fs.rm(root, { recursive: true, force: true });
  }
});


test('old MIMS output cannot be accepted under a newly armed queue', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-run-'));
  const oldPatterns = process.env.HMR_SMOKE_PATTERNS, oldUrl = process.env.HMR_SMOKE_URL;
  process.env.HMR_SMOKE_PATTERNS = JSON.stringify(['https://example.com/*']); process.env.HMR_SMOKE_URL = 'https://example.com/';
  try {
    await fs.mkdir(path.join(root, 'mims')); await fs.writeFile(path.join(root, 'mims', 'content.js'), mimsSource);
    let token;
    const view = { getURL: () => 'https://example.com/check', isDestroyed: () => false,
      executeJavaScript: async script => { token = /const token = "([^"]+)"/.exec(script)?.[1] || token; } };
    const armed = { emims: true }, queues = { emims: [{ id: 1, folder: 'One', folder_path: root, meds_revision: 'a'.repeat(64) }] };
    const run = helpers({ views: { emims: { webContents: view } }, armed, queues, saved: {},
      sites: { emims: { dir: 'mims', key: 'MIMS_LISTS' } }, config: { base: root }, dataDir: root,
      waitingTasks: { emims: [] }, api: async () => ({}), notify() {} });
    await run.inject('emims'); const old = token;
    armed.emims = false; await run.cancel('emims');
    queues.emims = [{ ...queues.emims[0], meds_revision: 'b'.repeat(64) }]; armed.emims = true;
    await run.inject('emims'); const current = token;
    assert.notEqual(old, current);
    const message = { filename: 'HMR Interactions/One.txt', url: 'data:text/plain,result' };
    assert.match((await run.saveHelper({ sender: view }, { ...message, hmrRun: old })).error, /no longer active/);
    const saved = await run.saveHelper({ sender: view }, { ...message, hmrRun: current });
    assert.match(saved.filename, /^MIMS interactions generated b{64}/);
  } finally {
    if (oldPatterns === undefined) delete process.env.HMR_SMOKE_PATTERNS; else process.env.HMR_SMOKE_PATTERNS = oldPatterns;
    if (oldUrl === undefined) delete process.env.HMR_SMOKE_URL; else process.env.HMR_SMOKE_URL = oldUrl;
    await fs.rm(root, { recursive: true, force: true });
  }
});
