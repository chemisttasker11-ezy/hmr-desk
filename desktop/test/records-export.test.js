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
