'use strict';
/** Two-phase activation of an already isolated HMR backup with recovery journal.

Requires the caller to stop the local engine, after first creating an encrypted
backup of the currently active workspace. Previous patient workspace, DB and approved
template folder remain available for recovery. Never silently activates during restore.

After activation the app must prove a healthy launch (engine ready on the new data).
An activation that is not confirmed healthy within MAX_UNCONFIRMED_LAUNCHES launches,
or whose engine fails to start, rolls back to the previous installation automatically
or, on request, from the Settings page.
*/
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {prepareMigration} = require('./workspace-migration');

const MAX_UNCONFIRMED_LAUNCHES = 2;
const ACTIVATION_RECORD = 'last-activation.json';
const FAILURE_RECORD = 'last-activation-failure.json';
/** Parse JSON text that a Windows editor or PowerShell 5.1 may have saved with a UTF-8 byte order mark.
    Startup (config-load.js) already tolerates the mark; activation and rollback must read the same file the same way.
    Only parsing strips it: the raw text is stored and restored byte-for-byte. */
function parseJsonText(text) { return JSON.parse(String(text).replace(/^\uFEFF/, '')); }
/** Tag an operational error with the activation stage that raised it.
    Stage names and messages are operational only: no patient content, no key material. */
function fail(stage, message) {
  const error = Error(message);
  error.stage = stage;
  throw error;
}
async function withStage(stage, operation) {
  try { return await operation(); }
  catch (error) {
    if (error && typeof error === 'object' && !error.stage) error.stage = stage;
    throw error;
  }
}
/** Reduce an error to values that cannot carry paths, patient names or key material:
    an allowlisted stage, an OS-style error code (e.g. EACCES) and a fixed reason category.
    The raw message is never stored. */
const STAGES = new Set(['verify','config','validate','stage-database','migrate-workspace','stage-templates','activate']);
const REASONS = [
  [/manifest is invalid|unsafe manifest fields/i,'manifest-invalid'],
  [/checksum (changed|mismatch)|failed verification/i,'checksum-mismatch'],
  [/unsafe source path|symlink|Unsupported source workspace file/i,'unsafe-or-unsupported-file'],
  [/too large|exceeds safe migration limits/i,'size-limit'],
  [/configuration is invalid/i,'config-invalid'],
  [/outside the active app data|independent folders|Destination exists/i,'folder-conflict'],
  [/requires recovery/i,'journal-present'],
  [/^SyntaxError/,'invalid-json'],
  [/changed during migration/i,'source-changed'],
];
function safeFailure(error) {
  const message = String((error && error.message) || error || '');
  const kind = error && error.name === 'SyntaxError' ? 'SyntaxError' : '';
  const code = error && typeof error.code === 'string' && /^[A-Z0-9_]{2,40}$/.test(error.code) ? error.code : null;
  const hit = REASONS.find(([pattern]) => pattern.test(message) || (kind && pattern.test(kind)));
  return {code, reason: hit ? hit[1] : (code ? 'os-error' : 'unclassified')};
}
/** Persist the last activation failure privately beside the data (mode 0600, atomic).
    Sanitized only: stage, error code and reason category for the activation error and,
    when the engine restart also failed, the same for that error. Never throws into the failure path. */
async function recordActivationFailure(dataDir, entry) {
  const record = {at: new Date().toISOString()};
  if (entry && entry.activation) {
    const stage = STAGES.has(entry.activation.stage) ? entry.activation.stage : 'unknown';
    record.activation = {stage, ...safeFailure(entry.activation.error)};
  }
  if (entry && entry.restart) record.restart = safeFailure(entry.restart.error);
  await writeAtomic(path.join(path.resolve(dataDir), FAILURE_RECORD), JSON.stringify(record, null, 2));
}

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
    const dataFile = parts[0] === 'data' &&
      (relative === 'data/hmr.db' || (parts[1] === 'templates' && parts.length >= 3));
    if (parts.length < 2 || !(parts[0] === 'workspace' || dataFile) ||
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
  const templateNames = Object.keys(records).filter(name => name.startsWith('data/templates/'));
  return {folder,workspace,database:path.join(folder,'data','hmr.db'),
    templates:templateNames.length ? path.join(folder,'data','templates') : null,
    templateFiles:templateNames.length,
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
    for (const suffix of ['', '-wal', '-shm']) {
      const old = path.join(rollback,'hmr.db'+suffix);
      await moveIfExists(old,path.join(dataDir,'hmr.db'+suffix));
    }
  } catch(e) {
    if (e.code!=='ENOENT')throw e;
  }
  if (entry.templates === true) {
    // The activation replaced the approved-template folder: put the previous one back.
    await fs.rm(path.join(dataDir,'templates'),{recursive:true,force:true});
    await moveIfExists(path.join(rollback,'templates'),path.join(dataDir,'templates'));
  }
  if (typeof entry.originalConfig === 'string')
    await writeAtomic(configPath,entry.originalConfig);
  await fs.rm(journalPath,{force:true});
  return true;
}
async function readRecord(dataDir) {
  try {return JSON.parse(await fs.readFile(path.join(dataDir,ACTIVATION_RECORD),'utf8'));}
  catch(e) {if(e.code==='ENOENT')return null;throw e;}
}
async function writeRecord(dataDir,record) {
  await writeAtomic(path.join(dataDir,ACTIVATION_RECORD),JSON.stringify(record));
}
/** True while the newest activation has not yet been proven healthy or rolled back. */
async function hasUnconfirmedActivation(dataDir) {
  const record = await readRecord(dataDir);
  return !!record && record.status === 'pending-health';
}
/** Put the previous database, approved templates and configuration back. */
async function rollbackLastActivation(dataDir,configPath) {
  const data = path.resolve(dataDir);
  const record = await readRecord(data);
  if (!record || record.status === 'rolled-back') return {rolledBack:false,reason:'No activation to roll back'};
  const rollback = record.rollback;
  if (typeof rollback !== 'string' || !inside(data,path.resolve(rollback)) ||
      typeof record.previousConfig !== 'string')
    throw Error('Invalid last-activation record');
  try {await fs.access(path.join(rollback,'hmr.db'));}
  catch {throw Error('The previous database is no longer available for rollback');}
  const failed = path.join(rollback,'failed-activation-'+Date.now());
  await fs.mkdir(failed,{recursive:true});
  for (const suffix of ['', '-wal', '-shm'])
    await moveIfExists(path.join(data,'hmr.db'+suffix),path.join(failed,'hmr.db'+suffix));
  for (const suffix of ['', '-wal', '-shm'])
    await moveIfExists(path.join(rollback,'hmr.db'+suffix),path.join(data,'hmr.db'+suffix));
  if (record.templates === true) {
    await moveIfExists(path.join(data,'templates'),path.join(failed,'templates'));
    await moveIfExists(path.join(rollback,'templates'),path.join(data,'templates'));
  }
  await writeAtomic(configPath,record.previousConfig);
  await writeRecord(data,{...record,status:'rolled-back',rolledBackAt:new Date().toISOString(),
    failedActivationFolder:failed});
  return {rolledBack:true,workspace:parseJsonText(record.previousConfig).base,failedActivationFolder:failed};
}
/** Call once at every launch before the engine opens data. */
async function checkPendingActivation(dataDir,configPath) {
  const data = path.resolve(dataDir);
  const record = await readRecord(data);
  if (!record || record.status !== 'pending-health') return {state:'none'};
  const attempts = (Number(record.launchAttempts) || 0) + 1;
  if (attempts > MAX_UNCONFIRMED_LAUNCHES)
    return {state:'rolled-back',...await rollbackLastActivation(data,configPath),attempts};
  await writeRecord(data,{...record,launchAttempts:attempts});
  return {state:'pending',attempts};
}
/** Call after the engine reports ready on the activated data. */
async function markActivationHealthy(dataDir) {
  const data = path.resolve(dataDir);
  const record = await readRecord(data);
  if (!record || record.status !== 'pending-health') return false;
  await writeRecord(data,{...record,status:'confirmed',confirmedAt:new Date().toISOString()});
  return true;
}
async function activateRestored(restoredDir,dataDir,configPath) {
  const restored = await withStage('verify', () => verifyRestored(restoredDir));
  const data = path.resolve(dataDir);
  const stamp = Date.now() + '-' + crypto.randomUUID();
  const previousConfig = await withStage('config', async () => {
    const raw = await fs.readFile(configPath,'utf8');
    const parsed = parseJsonText(raw);
    if (!parsed || typeof parsed.base !== 'string' || !path.isAbsolute(parsed.base))
      throw Error('Current workspace configuration is invalid');
    return raw;
  });
  const config = parseJsonText(previousConfig);
  if (inside(restored.folder,data) || inside(data,restored.folder))
    fail('validate', 'Restore data must be outside the active app data directory');
  const targetWorkspace = path.join(data,'activated-workspaces','restore-'+stamp);
  const rollback = path.join(data,'restore-rollbacks','rollback-'+stamp);
  const staged = path.join(data,'.incoming-'+stamp+'.db');
  const stagedTemplates = path.join(data,'.incoming-templates-'+stamp);
  const journalPath = path.join(data,'restore-activation-journal.json');
  try {await fs.access(journalPath);fail('validate', 'Previous restore activation requires recovery');}
  catch(e) {if(e.code!=='ENOENT')throw e;}
  try {
  const saved = await withStage('stage-database', () => fs.stat(restored.database));
  await withStage('stage-database', async () => {
    await fs.copyFile(restored.database,staged);
    if (await hash(staged)!==await hash(restored.database) || (await fs.stat(staged)).size!==saved.size)
      throw Error('Restored SQLite copy failed verification');
  });
  await withStage('migrate-workspace', () => prepareMigration(restored.workspace,targetWorkspace));
  const hasTemplates = !!restored.templates;
  if (hasTemplates) {
    await withStage('stage-templates', async () => {
      await fs.cp(restored.templates,stagedTemplates,{recursive:true,errorOnExist:true});
      const records = JSON.parse(await fs.readFile(path.join(restored.folder,'restore-manifest.json'),'utf8')).files;
      for (const [relative, expected] of Object.entries(records)) {
        if (!relative.startsWith('data/templates/')) continue;
        const copy = path.join(stagedTemplates,...relative.split('/').slice(2));
        if (await hash(copy) !== expected.sha256) throw Error('Restored approved template copy failed verification');
      }
    });
  }
  return await withStage('activate', async () => {
  await fs.mkdir(rollback,{recursive:true});
  await fs.writeFile(journalPath,JSON.stringify({rollback,originalConfig:previousConfig,
    newWorkspace:targetWorkspace,templates:hasTemplates}),{flag:'wx',mode:0o600});
  try {
    for (const suffix of ['', '-wal', '-shm']) {
      await moveIfExists(path.join(data,'hmr.db'+suffix),path.join(rollback,'hmr.db'+suffix));
    }
    await fs.rename(staged,path.join(data,'hmr.db'));
    if (hasTemplates) {
      await moveIfExists(path.join(data,'templates'),path.join(rollback,'templates'));
      await fs.rename(stagedTemplates,path.join(data,'templates'));
    }
    await writeAtomic(configPath,JSON.stringify({...config,base:targetWorkspace},null,2));
    await writeRecord(data,{rollback,previousConfig,newWorkspace:targetWorkspace,
      templates:hasTemplates,status:'pending-health',launchAttempts:0,
      activatedAt:new Date().toISOString()});
    await fs.rm(journalPath,{force:true});
    return {activated:true,previousDataPreserved:true,workspace:targetWorkspace,
      recoveryFolder:rollback,files:restored.files};
  } catch(e) {
    await recoverInterruptedRestore(data,configPath);
    throw e;
  }
  });
  } finally {
    await fs.rm(staged,{force:true});
    await fs.rm(stagedTemplates,{recursive:true,force:true});
  }
}
module.exports = {parseJsonText,verifyRestored,activateRestored,recoverInterruptedRestore,
  hasUnconfirmedActivation,rollbackLastActivation,checkPendingActivation,
  markActivationHealthy,recordActivationFailure,MAX_UNCONFIRMED_LAUNCHES,
  FAILURE_RECORD};
