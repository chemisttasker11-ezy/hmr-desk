const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { inventory, prepareMigration } = require('../src/workspace-migration');

test('hashed staged migration retains originals and verifies nested patient documents', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-mig-'));
  try {
    const source = path.join(root, 'old workspace');
    const patient = path.join(source, 'TO SORT', 'Synthetic Example');
    fs.mkdirSync(patient, {recursive:true});
    fs.writeFileSync(path.join(patient, 'interview.json'), '{"synthetic":true}');
    fs.writeFileSync(path.join(patient, 'referral.pdf'), '%PDF-1.4\n');
    const count = await inventory(source);
    assert.equal(count.entries.length, 2);
    const destination = path.join(root, 'new workspace');
    const result = await prepareMigration(source, destination);
    assert.equal(result.sourcePreserved, true);
    assert.equal(result.files, 2);
    assert.deepEqual(fs.readFileSync(path.join(destination, 'TO SORT','Synthetic Example','interview.json')),
      fs.readFileSync(path.join(patient,'interview.json')));
    assert.ok(fs.existsSync(path.join(patient,'referral.pdf')));
    await assert.rejects(prepareMigration(source,destination), /Destination exists/);
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});

test('source modification before activation rolls back only the new copy', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-mig-change-'));
  try {
    const source = path.join(root,'source');
    fs.mkdirSync(source);
    fs.writeFileSync(path.join(source,'interview.json'),'{"revision":1}');
    const target = path.join(root,'target');
    await assert.rejects(prepareMigration(source,target,{onBeforeActivation:()=>{
      throw Error('Interrupted activation');
    }}),/Interrupted activation/);
    assert.equal(fs.readFileSync(path.join(source,'interview.json'),'utf8'),'{"revision":1}');
    assert.equal(fs.existsSync(target),false);
    assert.ok(!fs.readdirSync(root).some(x=>x.startsWith('.hmr-migrate-')));
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});

test('rejects nested destination and symlink escape', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-mig-link-'));
  try {
    const source = path.join(root,'source');
    fs.mkdirSync(source);
    fs.writeFileSync(path.join(source,'safe.json'),'{}');
    await assert.rejects(prepareMigration(source,path.join(source,'inside')), /independent/);
    const link = path.join(source,'shortcut');
    try {fs.symlinkSync(root,link,'dir');}
    catch {t.skip('Symlink creation unavailable');return;}
    await assert.rejects(inventory(source),/symlink/);
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});
