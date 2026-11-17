const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { allowedSave, allowedFill, createGuard, createVault, publicEntry } = require('../src/vault');
const { loginFields } = require('../view-preload');

test('vault encrypts and round trips; renderer data has no password', () => {
  const dir = fs.mkdtempSync(path.join(__dirname, 'vault-test-'));
  try {
    const safe = {
      isEncryptionAvailable: () => true,
      encryptString: (s) => Buffer.from(s).reverse(),
      decryptString: (b) => Buffer.from(b).reverse().toString(),
    };
    const file = path.join(dir, 'sign-ins.bin');
    const vault = createVault(file, safe);
    const entry = { origin: 'https://example.com', username: 'person', password: 'secret', mode: 'fill' };
    vault.write({ mhr: entry });
    assert.deepEqual(vault.read(), { mhr: entry });
    assert.equal(fs.readFileSync(file).includes('secret'), false);
    assert.equal(Object.hasOwn(publicEntry('mhr', entry), 'password'), false);
    assert.throws(() => createVault(file, { isEncryptionAvailable: () => false }).read());
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
test('save and fill origins require HTTPS and exact host boundaries', () => {
  const start = 'https://proda.humanservices.gov.au/';
  assert.equal(allowedSave(start, start, 'mhr'), true);
  assert.equal(allowedSave('https://login.proda.humanservices.gov.au/', start, 'mhr'), true);
  assert.equal(allowedSave('https://proda.humanservices.gov.au.evil.example/', start, 'mhr'), false);
  assert.equal(allowedSave('http://proda.humanservices.gov.au/', start, 'mhr'), false);
  assert.equal(allowedFill('https://proda.humanservices.gov.au/login', 'https://proda.humanservices.gov.au'), true);
  assert.equal(allowedFill('https://login.proda.humanservices.gov.au/', 'https://proda.humanservices.gov.au'), false);
  assert.equal(allowedFill('http://proda.humanservices.gov.au/', 'http://proda.humanservices.gov.au'), false);
});
test('visible one-time code fields prevent login field selection', () => {
  global.getComputedStyle = () => ({ visibility: 'visible' });
  const input = (type, name = '') => ({ type, name, getClientRects: () => [1] });
  const user = input('text');
  const password = input('password');
  const otp = input('text', 'verification');
  const form = { querySelectorAll: () => [user, password, otp] };
  password.form = form;
  let inputs = [user, password];
  const doc = { querySelectorAll: () => inputs };
  assert.equal(loginFields(doc).password, password);
  inputs = [user, password, otp];
  assert.equal(loginFields(doc), null);
  otp.getClientRects = () => [];
  assert.equal(loginFields(doc).password, password);
  delete global.getComputedStyle;
});
test('automatic submit cooldown and failed login timing', () => {
  let now = 0;
  const guard = createGuard(() => now);
  guard.submit('mhr', 'https://example.com/login', 1);
  assert.equal(guard.failed('mhr', 'https://example.com/login', 1), false);
  assert.equal(guard.failed('mhr', 'https://example.com/login', 2), true);
  assert.equal(guard.canSubmit('mhr'), false);
  now = 30001;
  assert.equal(guard.failed('mhr', 'https://example.com/login', 2), false);
  now = 120000;
  assert.equal(guard.canSubmit('mhr'), true);
});
