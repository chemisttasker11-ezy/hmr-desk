'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const main = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
const recordsIpc = fs.readFileSync(path.join(__dirname, '..', 'src', 'records-ipc.js'), 'utf8');
const register = require('../src/records-ipc');
function load(deps) { const handlers = {}; register({ ipcMain: { handle: (name, fn) => { handlers[name] = fn; } }, documentsDir: () => '/docs', ...deps }); return handlers; }
const preload = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf8');
const settings = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'settings.js'), 'utf8');

test('page code cannot call the record export or migrate routes through the generic bridge', () => {
  assert.match(main, /p\.startsWith\('\/api\/records\/'\) && p !== '\/api\/records\/status'/);
});

test('export folder comes from a native dialog in the main process, not from the page', () => {
  const handler = recordsIpc.slice(recordsIpc.indexOf("ipcMain.handle('records-export'"), recordsIpc.indexOf("ipcMain.handle('encrypted-backup'"));
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
  const handler = recordsIpc.slice(recordsIpc.indexOf("ipcMain.handle('records-retire'"), recordsIpc.indexOf("ipcMain.handle('records-export'"));
  assert.match(handler, /e\.sender !== getWin\(\)\.webContents/);
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
  const sender = {}; let response = 0; const calls = [];
  const h = load({ getWin: () => ({ webContents: sender }), dialog: { showMessageBox: async () => ({ response }) },
    api: async (...args) => { calls.push(args); return { removed: 2 }; } });
  const handler = h['records-retire'];
  assert.equal((await handler({ sender })).cancelled, true);
  assert.equal(calls.length, 0);
  response = 1;
  assert.equal((await handler({ sender })).removed, 2);
  assert.equal(calls[0][0], 'POST'); assert.equal(calls[0][1], '/api/records/retire');
  assert.equal(calls[0][2].confirmed, true);
  await assert.rejects(handler({ sender: {} }), /Invalid request/);
  assert.equal(calls.length, 1);
});

test('shared export is an explicit zero id and native folder selection can be cancelled', async () => {
  const sender = {}; let canceled = true; const calls = [];
  const h = load({ getWin: () => ({ webContents: sender }),
    dialog: { showOpenDialog: async () => ({ canceled, filePaths: ['/synthetic-export'] }) },
    api: async (...args) => { calls.push(args); return { files: {} }; } });
  const handler = h['records-export'];
  assert.equal((await handler({ sender }, 0)).cancelled, true); assert.equal(calls.length, 0);
  canceled = false; await handler({ sender }, 0);
  assert.equal(calls[0][2].patient_id, 0);
  assert.match(calls[0][2].destination, /HMR exported shared records$/);
  await assert.rejects(handler({ sender }, -1), /Invalid export request/);
});

test('encrypted backup validates the request before any dialog or engine call', async () => {
  const sender = {}; const calls = []; let dialogs = 0;
  const h = load({ getWin: () => ({ webContents: sender }),
    dialog: { showSaveDialog: async () => { dialogs++; return { canceled: true }; }, showOpenDialog: async () => { dialogs++; return { canceled: true }; } },
    api: async (...args) => { calls.push(args); return {}; } });
  const handler = h['encrypted-backup'];
  await assert.rejects(handler({ sender: {} }, 'create', 'a-long-enough-passphrase'), /Invalid backup request/);
  await assert.rejects(handler({ sender }, 'create', 'short'), /Invalid backup request/);
  await assert.rejects(handler({ sender }, 'delete', 'a-long-enough-passphrase'), /Invalid backup request/);
  assert.equal(dialogs, 0); assert.equal(calls.length, 0);
  assert.equal((await handler({ sender }, 'create', 'a-long-enough-passphrase')).cancelled, true);
  assert.equal(calls.length, 0);
});
