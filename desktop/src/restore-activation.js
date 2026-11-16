'use strict';
/** Two-phase activation of an already isolated HMR backup with recovery journal.

Requires the caller to stop the local engine, after first creating an encrypted
backup of the currently active workspace. Previous patient workspace and DB
remain available for recovery. Never silently activates during restore.
*/
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {prepareMigration} = require('./workspace-migration');

function inside(root, child) {
  const relative = path.relative(root, child);
  return relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}
async function hash(file) {
  const h = crypto.createHash('sha256');
  const fh = await fs.open(file,'r');
  try { for await (const chunk of fh.createReadStream({autoClose:false})) h.update(chunk); }
  finally {await fh.close();}
  return h.digest('hex');
}
async function writeAtomic(destination, content) {
  const temp = destination + '.new-' + crypto.randomUUID();
  try {
    await fs.writeFile(temp, content, {flag:'wx',mode:0o600});
    await fs.rename(temp,destination);
  } finally {await fs.rm(temp,{force:true});}
}
async function verifyRestored(root) {
  const folder = await fs.realpath(root);
  const marker = path.join(folder,'restore-manifest.json');
  const meta = JSON.parse(await fs.readFile(marker,'utf8'));
  const records = meta.files;
  if (meta.format !== 1 || !records || typeof records !== 'object' ||
      !records['data/hmr.db'] || Object.keys(records).length > 25000)
    throw Error('Restored dataset manifest is invalid');
  let bytes = 0;
  for (const [relative, expected] of Object.entries(records)) {
    const parts = relative.split('/');
    if (parts.length < 2 || !['data','workspace'].includes(parts[0]) ||
        parts.some(part => !part || part === '.' || part === '..') ||
        !expected || typeof expected.sha256 !== 'string' ||
        !/^[a-f0-9]{64}$/.test(expected.sha256) ||
        !Number.isSafeInteger(expected.size) || expected.size < 0)
      throw Error('Restored dataset has unsafe manifest fields');
    const candidate = path.join(folder,...parts);
    const checked = await fs.realpath(candidate);
    if (!inside(folder,checked) || (await fs.lstat(candidate)).isSymbolicLink())
      throw Error('Restored dataset has an unsafe source path');
    const actual = await fs.stat(checked);
    if (!actual.isFile() || actual.size !== expected.size || await hash(checked) !== expected.sha256)
      throw Error('Restored dataset file checksum changed');
    bytes += actual.size;
    if (bytes > 16 * 1024 ** 3) throw Error('Restored dataset is too large');
  }
  const workspace = path.join(folder,'workspace');
  if (!(await fs.stat(workspace)).isDirectory()) throw Error('Restored workspace is missing');
  return {folder,workspace,database:path.join(folder,'data','hmr.db'),
    files:Object.keys(records).length,bytes};
}
async function moveIfExists(source,destination) {
  try { await fs.rename(source,destination);return true; }
  catch(e) {if(e.code==='ENOENT')return false;throw e;}
}
async function recoverInterruptedRestore(dataDir,configPath) {
  const journalPath = path.join(dataDir,'restore-activation-journal.json');
  let entry;
  try {entry=JSON.parse(await fs.readFile(journalPath,'utf8'));}
  catch(e) {if(e.code==='ENOENT')return false;throw e;}
  // Recovery journal paths are required to live under the expected private tree.
  const rollback = entry.rollback;
  if (typeof rollback !== 'string' || !inside(path.resolve(dataDir),path.resolve(rollback)))
    throw Error('Invalid restoration recovery journal');
  const active = path.join(dataDir,'hmr.db');
  const saved = path.join(rollback,'hmr.db');
  try {
    await fs.access(saved);
    await fs.rm(active,{force:true});
    for (const suffix of ('','-wal','-shm')) {
      const old = path.join(rollback,'hmr.db'+suffix);
      await moveIfExists(old,path.join(dataDir,'hmr.db'+suffix));
    }
  } catch(e) {
    if (e.code!=='ENOENT')throw e;
  }
  if (typeof entry.originalConfig === 'string')
    await writeAtomic(configPath,entry.originalConfig);
  await fs.rm(journalPath,{force:true});
  return true;
}
async function activateRestored(restoredDir,dataDir,configPath) {
  const restored = await verifyRestored(restoredDir);
  const data = path.resolve(dataDir);
  const stamp = Date.now() + '-' + crypto.randomUUID();
  const previousConfig = await fs.readFile(configPath,'utf8');
  const config = JSON.parse(previousConfig);
  if (!config || typeof config.base !== 'string' || !path.isAbsolute(config.base))
    throw Error('Current workspace configuration is invalid');
  if (inside(restored.folder,data) || inside(data,restored.folder))
    throw Error('Restore data must be outside the active app data directory');
  const targetWorkspace = path.join(data,'activated-workspaces','restore-'+stamp);
  const rollback = path.join(data,'restore-rollbacks','rollback-'+stamp);
  const staged = path.join(data,'.incoming-'+stamp+'.db');
  const journalPath = path.join(data,'restore-activation-journal.json');
  try {await fs.access(journalPath);throw Error('Previous restore activation requires recovery');}
  catch(e) {if(e.code!=='ENOENT')throw e;}
  const saved = await fs.stat(restored.database);
  await fs.copyFile(restored.database,staged);
  if (await hash(staged)!==await hash(restored.database) || (await fs.stat(staged)).size!==saved.size)
    throw Error('Restored SQLite copy failed verification');
  await prepareMigration(restored.workspace,targetWorkspace);
  await fs.mkdir(rollback,{recursive:true});
  await fs.writeFile(journalPath,JSON.stringify({rollback,originalConfig:previousConfig,
    newWorkspace:targetWorkspace}),{flag:'wx',mode:0o600});
  try {
    for (const suffix of ('','-wal','-shm')) {
      await moveIfExists(path.join(data,'hmr.db'+suffix),path.join(rollback,'hmr.db'+suffix));
    }
    await fs.rename(staged,path.join(data,'hmr.db'));
    await writeAtomic(configPath,JSON.stringify({...config,base:targetWorkspace},null,2));
    await fs.writeFile(path.join(data,'last-activation.json'),JSON.stringify({
      rollback,previousConfig,newWorkspace:targetWorkspace
    }),{mode:0o600});
    await fs.rm(journalPath,{force:true});
    return {activated:true,previousDataPreserved:true,workspace:targetWorkspace,
      recoveryFolder:rollback,files:restored.files};
  } catch(e) {
    await recoverInterruptedRestore(data,configPath);
    throw e;
  } finally {await fs.rm(staged,{force:true});}
}
module.exports = {verifyRestored,activateRestored,recoverInterruptedRestore};
