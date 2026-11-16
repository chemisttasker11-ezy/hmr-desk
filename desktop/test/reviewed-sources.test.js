const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { ReviewedSources } = require('../src/reviewed-sources');

test('reviewed source opens only the exact hash-verified PDF selected through intake', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-review-'));
  try {
    const file = path.join(dir, 'synthetic referral.pdf');
    fs.writeFileSync(file, '%PDF-1.4\nsynthetic sample only');
    const token = 'a'.repeat(32);
    const sha256 = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    const reviewed = new ReviewedSources();
    reviewed.remember([file], { rows: [{ token, sha256 }] });
    assert.equal(await reviewed.verifiedPath(token), file);
    fs.appendFileSync(file, 'modified');
    await assert.rejects(reviewed.verifiedPath(token), /changed/);
    await assert.rejects(reviewed.verifiedPath('..\\secret.pdf'), /Invalid referral review token/);
    await assert.rejects(reviewed.verifiedPath('b'.repeat(32)), /expired/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('source token expires and never accepts arbitrary renderer paths', async () => {
  let now = 0;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-expiry-'));
  try {
    const file = path.join(dir, 'document.pdf');
    fs.writeFileSync(file, '%PDF-1.4\n');
    const hash = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    const checked = new ReviewedSources({now: () => now, ttl: 100});
    checked.remember([file], {rows:[{token:'c'.repeat(32),sha256:hash}]});
    now = 101;
    await assert.rejects(checked.verifiedPath('c'.repeat(32)), /expired/);
    assert.equal(checked.records.size, 0);
  } finally { fs.rmSync(dir, {recursive:true,force:true}); }
});

test('referral review rejects symlinks and extension substitution', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-link-'));
  try {
    const file = path.join(dir, 'real.pdf');
    fs.writeFileSync(file, '%PDF-1.4\n');
    const hash = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    const links = path.join(dir, 'alias.pdf');
    try { fs.symlinkSync(file, links); } catch { t.skip('Symlink creation unavailable'); return; }
    const checked = new ReviewedSources();
    checked.remember([links], {rows:[{token:'f'.repeat(32),sha256:hash}]});
    await assert.rejects(checked.verifiedPath('f'.repeat(32)), /Invalid source PDF/);
  } finally { fs.rmSync(dir, {recursive:true,force:true}); }
});
