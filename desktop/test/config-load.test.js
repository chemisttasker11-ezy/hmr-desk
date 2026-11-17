const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {loadConfig} = require('../src/config-load');

test('existing legacy workspace config survives exact round trip', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-config-'));
  try {
    const file = path.join(dir, 'app-config.json');
    const base = path.join(dir, 'old patients');
    fs.writeFileSync(file, JSON.stringify({base, api:'http://127.0.0.1:1111',legacy_marker:'preserve'}));
    const read = loadConfig(file, {base:path.join(dir,'default')});
    assert.equal(read.firstRun, false);
    assert.equal(read.config.base, base);
    assert.equal(read.config.legacy_marker, 'preserve');
    assert.deepEqual(fs.readdirSync(dir), ['app-config.json']);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test('damaged app configuration is preserved and requires deliberate workspace selection', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-config-corrupt-'));
  try {
    const file = path.join(dir, 'app-config.json');
    fs.writeFileSync(file, '{bad JSON');
    const read = loadConfig(file, {base:path.join(dir,'new workspace')});
    assert.equal(read.firstRun, true);
    assert.match(read.recovery, /Previous configuration/);
    assert.ok(fs.readdirSync(dir).some(p=>p.startsWith('app-config.json.invalid-')));
    assert.equal(fs.existsSync(file), false);
    assert.match(fs.readFileSync(path.join(dir,fs.readdirSync(dir)[0]),'utf8'), /bad JSON/);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test('config rejects relative patient folder without silent import', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-config-badpath-'));
  try {
    const file = path.join(dir,'app-config.json');
    fs.writeFileSync(file, JSON.stringify({base:'relative'}));
    const output = loadConfig(file,{base:path.join(dir,'default')});
    assert.equal(output.firstRun,true);
    assert.equal(output.config.base,path.join(dir,'default'));
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
