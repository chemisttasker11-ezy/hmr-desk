const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {verifyRestored,activateRestored,recoverInterruptedRestore} = require('../src/restore-activation');

function sha(bytes){return crypto.createHash('sha256').update(bytes).digest('hex');}
function scenario(){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'hmr-activate-'));
  const data=path.join(root,'private data');
  const oldWorkspace=path.join(root,'old workspace');
  const recovered=path.join(root,'isolated');
  fs.mkdirSync(data,{recursive:true});
  fs.mkdirSync(oldWorkspace,{recursive:true});
  fs.mkdirSync(path.join(recovered,'workspace','TO SORT'),{recursive:true});
  fs.mkdirSync(path.join(recovered,'data'),{recursive:true});
  const oldDb=Buffer.from('old synthetic SQLite database contents');
  const newDb=Buffer.from('new synthetic SQLite database contents');
  const file=Buffer.from('{"patient":"Synthetic Only"}');
  fs.writeFileSync(path.join(data,'hmr.db'),oldDb);
  fs.writeFileSync(path.join(oldWorkspace,'original.json'),'{"old":true}');
  fs.writeFileSync(path.join(recovered,'workspace','TO SORT','case.json'),file);
  fs.writeFileSync(path.join(recovered,'data','hmr.db'),newDb);
  const manifest={format:1,files:{
    'data/hmr.db':{sha256:sha(newDb),size:newDb.length},
    'workspace/TO SORT/case.json':{sha256:sha(file),size:file.length},
  }};
  fs.writeFileSync(path.join(recovered,'restore-manifest.json'),JSON.stringify(manifest));
  const configPath=path.join(data,'app-config.json');
  fs.writeFileSync(configPath,JSON.stringify({base:oldWorkspace}));
  return {root,data,oldWorkspace,recovered,configPath,oldDb,newDb};
}

test('isolated activation retains prior DB and workspace for rollback', async ()=>{
  const s=scenario();
  try {
    const preview=await verifyRestored(s.recovered);
    assert.equal(preview.files,2);
    const result=await activateRestored(s.recovered,s.data,s.configPath);
    assert.equal(result.activated,true);
    assert.ok(fs.readFileSync(path.join(s.data,'hmr.db')).equals(s.newDb));
    assert.ok(fs.readFileSync(path.join(result.recoveryFolder,'hmr.db')).equals(s.oldDb));
    assert.equal(fs.readFileSync(path.join(s.oldWorkspace,'original.json'),'utf8'),'{"old":true}');
    const config=JSON.parse(fs.readFileSync(s.configPath));
    assert.equal(config.base,result.workspace);
    assert.equal(fs.readFileSync(path.join(result.workspace,'TO SORT','case.json'),'utf8'),
      '{"patient":"Synthetic Only"}');
    assert.equal(fs.existsSync(path.join(s.data,'restore-activation-journal.json')),false);
  } finally {fs.rmSync(s.root,{recursive:true,force:true});}
});

test('modified restored case is rejected before touching live SQLite', async ()=>{
  const s=scenario();
  try {
    fs.appendFileSync(path.join(s.recovered,'workspace','TO SORT','case.json'),'tampered');
    await assert.rejects(activateRestored(s.recovered,s.data,s.configPath),/checksum changed/);
    assert.ok(fs.readFileSync(path.join(s.data,'hmr.db')).equals(s.oldDb));
    assert.equal(JSON.parse(fs.readFileSync(s.configPath)).base,s.oldWorkspace);
  } finally {fs.rmSync(s.root,{recursive:true,force:true});}
});

test('interrupted activation restores old DB and configuration from journal', async ()=>{
  const s=scenario();
  try {
    const rollback=path.join(s.data,'restore-rollbacks','old');
    fs.mkdirSync(rollback,{recursive:true});
    fs.renameSync(path.join(s.data,'hmr.db'),path.join(rollback,'hmr.db'));
    fs.writeFileSync(path.join(s.data,'hmr.db'),s.newDb);
    const previous=fs.readFileSync(s.configPath,'utf8');
    fs.writeFileSync(s.configPath,JSON.stringify({base:path.join(s.root,'wrong')}));
    fs.writeFileSync(path.join(s.data,'restore-activation-journal.json'),JSON.stringify({
      rollback,originalConfig:previous,newWorkspace:path.join(s.root,'wrong')
    }));
    assert.equal(await recoverInterruptedRestore(s.data,s.configPath),true);
    assert.ok(fs.readFileSync(path.join(s.data,'hmr.db')).equals(s.oldDb));
    assert.equal(JSON.parse(fs.readFileSync(s.configPath)).base,s.oldWorkspace);
    assert.equal(await recoverInterruptedRestore(s.data,s.configPath),false);
  } finally {fs.rmSync(s.root,{recursive:true,force:true});}
});
