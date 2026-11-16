const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeVault } = require('../src/draft-vault');

function fakeProtectedStore() {
  // Simulates successful DPAPI encrypt/decrypt contract. Security depends on
  // native Windows DPAPI, which is independently verified at packaged runtime.
  return {
    isEncryptionAvailable: () => true,
    encryptString: value => Buffer.from(value).map(byte => byte ^ 0x5a),
    decryptString: bytes => Buffer.from(bytes).map(byte => byte ^ 0x5a).toString('utf8'),
  };
}

test('protected draft vault roundtrips, enumerates, and refuses unsafe keys', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-draft-vault-'));
  try {
    const vault = makeVault(path.join(dir, 'secure'), fakeProtectedStore());
    const key = 'hmr-draft:interview:123';
    vault.setItem(key, JSON.stringify({ notes: 'synthetic sensitive clinical notes' }));
    assert.equal(vault.keys()[0], key);
    assert.deepEqual(JSON.parse(vault.getItem(key)), { notes: 'synthetic sensitive clinical notes' });
    const raw = fs.readFileSync(path.join(dir, 'secure', fs.readdirSync(path.join(dir, 'secure'))[0]));
    assert.ok(!raw.includes(Buffer.from('synthetic sensitive clinical notes')));
    assert.throws(() => vault.setItem('../other', '{}'), /key/);
    vault.removeItem(key);
    assert.equal(vault.getItem(key), null);
    assert.deepEqual(vault.keys(), []);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('missing OS encryption fails closed and refuses plaintext writes', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-draft-vault-no-key-'));
  try {
    const vault = makeVault(path.join(dir, 'secure'), { isEncryptionAvailable: () => false });
    assert.throws(() => vault.setItem('hmr-draft:interview:123', 'text'), /protected draft storage unavailable/i);
    assert.ok(!fs.existsSync(path.join(dir, 'secure')));
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
