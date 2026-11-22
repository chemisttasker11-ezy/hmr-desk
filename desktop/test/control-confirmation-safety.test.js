// Synthetic regression for a native confirm() blocking the Electron renderer.
// Only read-only snapshots are timed out. Never time out or replay click/fill actions.
const test = require('node:test');
const assert = require('node:assert/strict');
const { UI_BLOCKED, boundedUiSnapshot } = require('../src/control');

test('automated UI refuses confirm-backed pharmacist actions before triggering dialogs', () => {
  const blocked = new RegExp(UI_BLOCKED, 'i');
  for (const label of [
    'Refresh', 'Refresh from interview and pathology',
    'Use patient record', 'Keep report text',
    'Load all report', 'Restore backup', 'Reset report',
    'Sign off', 'Send offer', 'Acknowledge reviewed discrepancies',
  ]) {
    assert.equal(blocked.test(label), true, label);
  }
  for (const label of ['Save', 'Today', 'Results', 'Interview']) {
    assert.equal(blocked.test(label), false, label);
  }
});

test('read-only snapshot returns an answer if renderer is responsive', async () => {
  const webContents = { executeJavaScript: async (script) => ({ script, ok: true }) };
  assert.deepEqual(await boundedUiSnapshot(webContents, 'synthetic-snapshot', 100),
    { script: 'synthetic-snapshot', ok: true });
});

test('read-only snapshot fails promptly while a native confirmation blocks the renderer', async () => {
  const webContents = { executeJavaScript: () => new Promise(() => {}) };
  await assert.rejects(boundedUiSnapshot(webContents, 'synthetic-snapshot', 15),
    /human confirmation or is not responding/);
});

test('read-only snapshot propagates renderer errors', async () => {
  const webContents = { executeJavaScript: () => Promise.reject(new Error('renderer closed')) };
  await assert.rejects(boundedUiSnapshot(webContents, 'synthetic-snapshot', 100), /renderer closed/);
});
