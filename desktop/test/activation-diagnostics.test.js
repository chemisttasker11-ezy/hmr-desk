const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {activateRestored, recordActivationFailure, FAILURE_RECORD} = require('../src/restore-activation');

function sha(bytes){return crypto.createHash('sha256').update(bytes).digest('hex');}
function scenario(){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'hmr-diag-'));
  const data=path.join(root,'private data');
  const oldWorkspace=path.join(root,'old workspace');
  const recovered=path.join(root,'isolated');
  fs.mkdirSync(data,{recursive:true});
  fs.mkdirSync(oldWorkspace,{recursive:true});
  fs.mkdirSync(path.join(recovered,'workspace'),{recursive:true});
  fs.mkdirSync(path.join(recovered,'data'),{recursive:true});
  const newDb=Buffer.from('new synthetic SQLite database contents');
  fs.writeFileSync(path.join(data,'hmr.db'),'old synthetic');
  fs.writeFileSync(path.join(oldWorkspace,'original.json'),'{"old":true}');
  fs.writeFileSync(path.join(recovered,'data','hmr.db'),newDb);
  const manifest={format:1,files:{'data/hmr.db':{sha256:sha(newDb),size:newDb.length}}};
  fs.writeFileSync(path.join(recovered,'restore-manifest.json'),JSON.stringify(manifest));
  const configPath=path.join(data,'app-config.json');
  fs.writeFileSync(configPath,JSON.stringify({base:oldWorkspace}));
  return {root,data,oldWorkspace,recovered,configPath};
}

test('recordActivationFailure stores only sanitized stage, code and category', async ()=>{
  const s=scenario();
  try {
    const target=path.join(s.data,FAILURE_RECORD);
    const secretPath='C:\\Users\\Jane Citizen\\Patients\\John Smith 1960\\case.json';
    const osError=Object.assign(Error("EACCES: permission denied, open '"+secretPath+"'"),{code:'EACCES'});
    const restartError=Error('engine for John Smith failed at '+secretPath);
    await recordActivationFailure(s.data,{activation:{stage:'stage-database',error:osError},restart:{error:restartError}});
    const raw=await fsp.readFile(target,'utf8');
    assert.ok(!/Jane|Citizen|John|Smith|Users|case\.json|permission denied/.test(raw),raw);
    const first=JSON.parse(raw);
    assert.deepEqual(first.activation,{stage:'stage-database',code:'EACCES',reason:'os-error'});
    assert.deepEqual(first.restart,{code:null,reason:'unclassified'});
    assert.ok(first.at);
    assert.equal((await fsp.stat(target)).mode & 0o777, 0o600);
    // Unknown stage names and hostile codes are not stored; a newer failure replaces the record.
    await recordActivationFailure(s.data,{activation:{stage:'C:\\secret',
      error:Object.assign(Error('Restored dataset manifest is invalid'),{code:'bad code with spaces'})}});
    const second=JSON.parse(await fsp.readFile(target,'utf8'));
    assert.deepEqual(second.activation,{stage:'unknown',code:null,reason:'manifest-invalid'});
    assert.equal(second.restart,undefined);
    assert.deepEqual((await fsp.readdir(s.data)).filter(n=>n.includes('.new-')),[]);
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('a failing record write does not replace the original activation error', async ()=>{
  const s=scenario();
  try {
    fs.writeFileSync(path.join(s.recovered,'restore-manifest.json'),'{"format":9}');
    const original=await activateRestored(s.recovered,s.data,s.configPath).catch(e=>e);
    // Recording into a missing folder fails; the caller's pattern (try/catch around record) keeps the original.
    await assert.rejects(recordActivationFailure(path.join(s.root,'missing'),{activation:{stage:'verify',error:original}}));
    assert.equal(original.stage,'verify');
    assert.match(original.message,/manifest is invalid/);
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('activation failure is tagged with the verify stage', async ()=>{
  const s=scenario();
  try {
    fs.writeFileSync(path.join(s.recovered,'restore-manifest.json'),'{"format":9}');
    await assert.rejects(activateRestored(s.recovered,s.data,s.configPath),
      error => error.stage==='verify' && /manifest is invalid/.test(error.message));
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('activation failure is tagged with the config stage', async ()=>{
  const s=scenario();
  try {
    fs.writeFileSync(s.configPath,JSON.stringify({base:'relative/workspace'}));
    await assert.rejects(activateRestored(s.recovered,s.data,s.configPath),
      error => error.stage==='config' && /configuration is invalid/.test(error.message));
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('activation failure is tagged with the validate stage', async ()=>{
  const s=scenario();
  try {
    const nested=path.join(s.data,'restored-inside-data');
    fs.cpSync(s.recovered,nested,{recursive:true});
    await assert.rejects(activateRestored(nested,s.data,s.configPath),
      error => error.stage==='validate' && /outside the active app data directory/.test(error.message));
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('activation failure is tagged with the stage-database stage', async ()=>{
  const s=scenario();
  try {
    // A non-writable data folder fails the staged database copy, after verification passed.
    await fsp.chmod(s.data,0o555);
    await assert.rejects(activateRestored(s.recovered,s.data,s.configPath),
      error => error.stage==='stage-database');
    await fsp.chmod(s.data,0o755);
    // The staging file is cleaned up and the active database is untouched.
    assert.deepEqual((await fsp.readdir(s.data)).filter(n=>n.startsWith('.incoming-')),[]);
    assert.equal(await fsp.readFile(path.join(s.data,'hmr.db'),'utf8'),'old synthetic');
  } finally { await fsp.chmod(s.data,0o755).catch(()=>{}); await fsp.rm(s.root,{recursive:true,force:true}); }
});

test('activation failure is tagged with the migrate-workspace stage', async ()=>{
  const s=scenario();
  try {
    // A symlink absent from the manifest passes verifyRestored but must fail the workspace inventory.
    fs.symlinkSync(path.join(s.recovered,'data','hmr.db'),path.join(s.recovered,'workspace','linked.db'));
    await assert.rejects(activateRestored(s.recovered,s.data,s.configPath),
      error => error.stage==='migrate-workspace' && /symlink/.test(error.message));
  } finally { await fsp.rm(s.root,{recursive:true,force:true}); }
});
