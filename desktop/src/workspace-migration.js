'use strict';
/** Copy-verify-activate preparation of a historical local patient workspace.

Never deletes or renames the original. No automatic patient merging. The caller
switches its configuration only after this returns successfully and the engine
is stopped. No source clinical content is logged.
*/
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const MAX_FILES = 25000;
const MAX_TOTAL = 16 * 1024 ** 3;

async function hash(file) {
  const digest = crypto.createHash('sha256');
  const handle = await fs.open(file, 'r');
  try {
    for await (const chunk of handle.createReadStream({autoClose: false})) digest.update(chunk);
  } finally { await handle.close(); }
  return digest.digest('hex');
}
async function inventory(root) {
  const base = await fs.realpath(root);
  const stat = await fs.lstat(base);
  if (!stat.isDirectory()) throw Error('Source workspace must be an existing folder');
  const result = [];
  let total = 0;
  async function visit(folder, rel = '') {
    for (const entry of await fs.readdir(folder, {withFileTypes:true})) {
      const item = path.join(folder, entry.name);
      const relative = path.join(rel, entry.name);
      const attrs = await fs.lstat(item);
      if (attrs.isSymbolicLink()) throw Error('Workspace contains a symlink; cannot safely migrate');
      if (attrs.isDirectory()) await visit(item, relative);
      else if (attrs.isFile()) {
        total += attrs.size;
        if (total > MAX_TOTAL || result.length >= MAX_FILES)
          throw Error('Workspace exceeds safe migration limits');
        result.push({ relative, size:attrs.size, modified:attrs.mtimeMs, sha256: await hash(item) });
      } else throw Error('Unsupported source workspace file');
    }
  }
  await visit(base);
  return { root:base, entries:result, bytes:total };
}
function nested(parent, child) {
  // Windows paths must be compared case-insensitively and against real parents.
  const canonical = value => path.resolve(value).replaceAll(String.fromCharCode(92), '/').toLowerCase();
  const upper = canonical(parent);
  const lower = canonical(child);
  return lower === upper || lower.startsWith(upper.replace(/\/$/, '') + '/');
}
async function prepareMigration(source, destination, {onBeforeActivation} = {}) {
  if (typeof source !== 'string' || typeof destination !== 'string' ||
      !path.isAbsolute(source) || !path.isAbsolute(destination))
    throw Error('Choose absolute local source and destination folders');
  const before = await inventory(source);
  const target = path.resolve(destination);
  const parent = path.dirname(target);
  // Reject obvious nesting BEFORE touching parent directories.
  if (nested(before.root, target) || nested(target, before.root))
    throw Error('Source and destination must be independent folders');
  // Resolve existing ancestors to reject junction/symlink aliases as well.
  async function canonicalize(directory) {
    const missing = [];
    let current = directory;
    for (;;) {
      try {
        const real = await fs.realpath(current);
        return path.join(real, ...missing.reverse());
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
        const above = path.dirname(current);
        if (above === current) throw Error('Unable to resolve destination parent');
        missing.push(path.basename(current));
        current = above;
      }
    }
  }
  const canonicalTarget = path.join(await canonicalize(parent), path.basename(target));
  if (nested(before.root, canonicalTarget) || nested(canonicalTarget, before.root))
    throw Error('Source and destination must be independent folders');
  try { await fs.lstat(target); throw Error('Destination exists; choose a new empty workspace'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await fs.mkdir(parent, {recursive:true});
  const stage = await fs.mkdtemp(path.join(parent, '.hmr-migrate-'));
  let activated = false;
  try {
    for (const entry of before.entries) {
      const item = path.join(stage, entry.relative);
      await fs.mkdir(path.dirname(item), {recursive:true});
      await fs.copyFile(path.join(before.root, entry.relative), item,  fs.constants.COPYFILE_EXCL);
      if ((await hash(item)) !== entry.sha256) throw Error('Copied workspace checksum mismatch');
    }
    const confirmed = await inventory(before.root);
    if (before.entries.length !== confirmed.entries.length ||
        before.bytes !== confirmed.bytes ||
        before.entries.some((r,i) => r.relative !== confirmed.entries[i].relative ||
          r.sha256 !== confirmed.entries[i].sha256 || r.size !== confirmed.entries[i].size))
      throw Error('Original workspace changed during migration; retry after closing other writers');
    if (typeof onBeforeActivation === 'function') await onBeforeActivation({files:before.entries.length,bytes:before.bytes});
    await fs.rename(stage, target);
    activated = true;
    return {destination:target,files:before.entries.length,bytes:before.bytes,sourcePreserved:true};
  } finally {
    if (!activated) await fs.rm(stage, {recursive:true,force:true});
  }
}
module.exports = {inventory, prepareMigration};
