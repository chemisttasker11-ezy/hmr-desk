'use strict';
/** Electron-side Windows DPAPI-protected crash-recovery drafts.
 *
 * Never fall back to plaintext storage when running the packaged desktop app.
 * File names are hashes, values and local patient IDs inside encrypted payloads.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const MAX_DRAFT_BYTES = 2 * 1024 * 1024;
const MAX_DRAFTS = 2000;

function makeVault(directory, safeStorage) {
  function encrypted() {
    if (!safeStorage?.isEncryptionAvailable?.())
      throw Error('Windows protected draft storage unavailable; keep the interview open until connected');
  }
  function filename(key) {
    if (typeof key !== 'string' || !/^hmr-draft:[a-z_]+:[A-Za-z0-9_-]{1,128}(?::conflict-history)?$/.test(key))
      throw Error('Invalid protected draft key');
    return path.join(directory, crypto.createHash('sha256').update(key).digest('hex') + '.bin');
  }
  function store(key, value) {
    encrypted();
    if (typeof value !== 'string' || Buffer.byteLength(value) > MAX_DRAFT_BYTES)
      throw Error('Protected draft exceeds maximum size');
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const data = Buffer.from(JSON.stringify({ key, value }), 'utf8');
    const bytes = safeStorage.encryptString(data.toString('utf8'));
    if (bytes.length > MAX_DRAFT_BYTES + 4096) throw Error('Encrypted draft too large');
    const target = filename(key);
    const temp = target + '.' + crypto.randomBytes(8).toString('hex') + '.tmp';
    let file;
    try {
      file = fs.openSync(temp, 'wx', 0o600);
      fs.writeSync(file, bytes);
      fs.fsyncSync(file);
      fs.closeSync(file);
      file = null;
      fs.renameSync(temp, target);
    } finally {
      if (file !== null && file !== undefined) fs.closeSync(file);
      if (fs.existsSync(temp)) fs.unlinkSync(temp);
    }
  }
  function retrieve(key) {
    encrypted();
    const filenameValue = filename(key);
    if (!fs.existsSync(filenameValue)) return null;
    const file = fs.readFileSync(filenameValue);
    if (file.length > MAX_DRAFT_BYTES + 4096) throw Error('Protected draft is invalid or too large');
    const value = JSON.parse(safeStorage.decryptString(file));
    if (value.key !== key || typeof value.value !== 'string')
      throw Error('Protected draft integrity mismatch');
    return value.value;
  }
  function remove(key) {
    encrypted();
    const file = filename(key);
    if (fs.existsSync(file)) fs.unlinkSync(file);
  }
  function keys() {
    encrypted();
    if (!fs.existsSync(directory)) return [];
    const entries = fs.readdirSync(directory).filter(item => /^[0-9a-f]{64}\.bin$/.test(item));
    if (entries.length > MAX_DRAFTS) throw Error('Too many protected draft entries');
    const keys = [];
    for (const item of entries) {
      const bytes = fs.readFileSync(path.join(directory, item));
      if (bytes.length > MAX_DRAFT_BYTES + 4096) continue;
      try {
        const record = JSON.parse(safeStorage.decryptString(bytes));
        if (record && filename(record.key) === path.join(directory, item)) keys.push(record.key);
      } catch { /* Preserve unreadable encrypted draft for manual recovery. */ }
    }
    return keys;
  }
  return { getItem: retrieve, setItem: store, removeItem: remove, keys };
}

module.exports = { makeVault, MAX_DRAFT_BYTES };
