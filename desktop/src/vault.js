const fs = require('node:fs');
const path = require('node:path');

function allowedSave(url, start, site) {
  try {
    const u = new URL(url);
    const hosts = [new URL(start).hostname, ...(site === 'mhr' ? ['proda.humanservices.gov.au'] : [])];
    return (
      u.protocol === 'https:' &&
      !u.username &&
      !u.password &&
      hosts.some((h) => u.hostname === h || u.hostname.endsWith('.' + h))
    );
  } catch {
    return false;
  }
}
function allowedFill(url, origin) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && u.origin === origin;
  } catch {
    return false;
  }
}
function createGuard(clock = Date.now) {
  const submitted = {};
  return {
    failed(site, url, generation) {
      const s = submitted[site];
      return !!s && !s.handled && s.generation !== generation && s.url === url && clock() - s.time <= 30000;
    },
    canSubmit(site) {
      return !submitted[site] || clock() - submitted[site].time >= 120000;
    },
    submit(site, url, generation) {
      submitted[site] = { time: clock(), url, generation };
    },
    handled(site) {
      if (submitted[site]) submitted[site].handled = true;
    },
  };
}
function createVault(file, safeStorage) {
  const available = () => safeStorage.isEncryptionAvailable();
  function read() {
    if (!available()) throw Error('Encrypted storage is unavailable');
    if (!fs.existsSync(file)) return {};
    try {
      return JSON.parse(safeStorage.decryptString(fs.readFileSync(file)));
    } catch {
      throw Error('Could not open encrypted sign-ins');
    }
  }
  function write(data) {
    if (!available()) throw Error('Encrypted storage is unavailable');
    const encrypted = safeStorage.encryptString(JSON.stringify(data));
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temp = file + '.tmp';
    fs.writeFileSync(temp, encrypted);
    fs.renameSync(temp, file);
  }
  return { available, read, write };
}
function publicEntry(site, entry) {
  return entry
    ? { site, origin: entry.origin, username: entry.username, mode: entry.mode, saved: true }
    : { site, origin: '', username: '', mode: 'off', saved: false };
}
module.exports = { allowedSave, allowedFill, createGuard, createVault, publicEntry };
