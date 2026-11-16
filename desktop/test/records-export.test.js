'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const main = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf8');
const settings = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'settings.js'), 'utf8');

test('page code cannot call the record export or migrate routes through the generic bridge', () => {
  assert.match(main, /p\.startsWith\('\/api\/records\/'\) && p !== '\/api\/records\/status'/);
});

test('export folder comes from a native dialog in the main process, not from the page', () => {
  const handler = main.slice(main.indexOf("ipcMain.handle('records-export'"), main.indexOf("ipcMain.handle('encrypted-backup'"));
  assert.match(handler, /dialog\.showOpenDialog/);
  assert.match(handler, /Number\.isInteger\(patientId\)/);
  assert.match(preload, /exportRecords: patientId => ipcRenderer\.invoke\('records-export', patientId\)/);
  assert.doesNotMatch(settings, /records\/export/);
});

test('settings labels unprotected plain copies and the unencrypted export', () => {
  assert.match(settings, /NOT protected/);
  assert.match(settings, /outside the (app's )?encryption/);
});

test('plain-copy removal uses a native cancel-by-default confirmation', () => {
  const handler = main.slice(main.indexOf("ipcMain.handle('records-retire'"), main.indexOf("ipcMain.handle('records-export'"));
  assert.match(handler, /e\.sender !== win\.webContents/);
  assert.match(handler, /dialog\.showMessageBox/);
  assert.match(handler, /defaultId: 0, cancelId: 0/);
  assert.match(handler, /choice\.response !== 1/);
  assert.match(handler, /not secure erasure/);
  assert.match(preload, /retireRecordCopies: \(\) => ipcRenderer\.invoke\('records-retire'\)/);
  assert.doesNotMatch(settings, /records\/retire/);
});

test('export starts with an explicit choice, shared records are labelled', () => {
  assert.match(settings, /id: '', name: 'Choose records to export'/);
  assert.match(settings, /Shared records \(all patients\)/);
  assert.match(settings, /existing files left unchanged/);
});

test('native removal cancellation never calls the engine; confirmation calls only the fixed endpoint', async () => {
  const vm = require('node:vm');
  const code = main.slice(main.indexOf("ipcMain.handle('records-retire'"), main.indexOf('// Record export gets its own channel:'));
  const sender = {}; let handler; let response = 0; const calls = [];
  vm.runInNewContext(code, {ipcMain: {handle: (name, fn) => { assert.equal(name, 'records-retire'); handler = fn; }},
    win: {webContents: sender}, dialog: {showMessageBox: async () => ({response})},
    api: async (...args) => { calls.push(args); return {removed: 2}; }});
  assert.equal((await handler({sender})).cancelled, true);
  assert.equal(calls.length, 0);
  response = 1;
  assert.equal((await handler({sender})).removed, 2);
  assert.equal(calls[0][0], 'POST'); assert.equal(calls[0][1], '/api/records/retire');
  assert.equal(calls[0][2].confirmed, true);
  await assert.rejects(handler({sender: {}}), /Invalid request/);
  assert.equal(calls.length, 1);
});

test('shared export is an explicit zero id and native folder selection can be cancelled', async () => {
  const vm = require('node:vm');
  const code = main.slice(main.indexOf("ipcMain.handle('records-export'"), main.indexOf("ipcMain.handle('encrypted-backup'"));
  const sender = {}; let handler; let canceled = true; const calls = [];
  vm.runInNewContext(code, {ipcMain: {handle: (_name, fn) => { handler = fn; }},
    win: {webContents: sender}, path,
    dialog: {showOpenDialog: async () => ({canceled, filePaths: ['/synthetic-export']})},
    api: async (...args) => { calls.push(args); return {files: {}}; }});
  assert.equal((await handler({sender}, 0)).cancelled, true); assert.equal(calls.length, 0);
  canceled = false; await handler({sender}, 0);
  assert.equal(calls[0][2].patient_id, 0);
  assert.match(calls[0][2].destination, /HMR exported shared records$/);
  await assert.rejects(handler({sender}, -1), /Invalid export request/);
});
