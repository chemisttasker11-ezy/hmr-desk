'use strict';
/** Validate a writable, sufficiently capacious patient workspace before first use. */
const fs = require('node:fs');
const path = require('node:path');

function verifyWorkspace(folder, minimumFree = 250 * 1024 * 1024) {
  if (typeof folder !== 'string' || !path.isAbsolute(folder)) throw Error('Choose an absolute workspace folder');
  const resolved = path.resolve(folder);
  fs.mkdirSync(resolved, { recursive: true });
  if (!fs.statSync(resolved).isDirectory()) throw Error('The selected workspace is not a folder');
  const sample = fs.mkdtempSync(path.join(resolved, '.hmr-write-check-'));
  try {
    fs.writeFileSync(path.join(sample, 'check.tmp'), Buffer.from('HMROK'));
  } finally {
    fs.rmSync(sample, { recursive: true, force: true });
  }
  const stats = fs.statfsSync(resolved, { bigint: true });
  const available = stats.bavail * stats.bsize;
  if (available < BigInt(minimumFree)) {
    throw Error('Not enough free space for the clinical workspace (at least 250 MB required)');
  }
  return resolved;
}

module.exports = { verifyWorkspace };
