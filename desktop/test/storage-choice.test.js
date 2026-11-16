const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { verifyWorkspace } = require('../src/storage-choice');

test('workspace verification creates a truly writable local folder without leftover probe files', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-storage-'));
  try {
    const target = verifyWorkspace(path.join(folder, 'patient work', 'folder'), 10000);
    assert.ok(fs.statSync(target).isDirectory());
    assert.ok(!fs.readdirSync(target).some(name => name.startsWith('.hmr-write-check')));
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('workspace rejects relative paths and insufficient free space', () => {
  assert.throws(() => verifyWorkspace('relative'), /absolute/);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-storage-low-'));
  try { assert.throws(() => verifyWorkspace(folder, Number.MAX_SAFE_INTEGER), /free space/); }
  finally { fs.rmSync(folder, { recursive: true, force: true }); }
});
