const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const main = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
const handler = main.slice(main.indexOf("ipcMain.handle('open-report-version'"),
  main.indexOf("ipcMain.handle('open-patient-folder'"));

test('PDF report review opens in the bundled viewer, never through a Windows file association', () => {
  const pdfBranch = handler.slice(handler.indexOf("if (format === 'pdf')"),
    handler.indexOf("const openError"));
  assert.match(pdfBranch, /openBundledPdfViewer\(/);
  assert.doesNotMatch(pdfBranch, /shell\.openPath/);
});

test('the bundled PDF window is sandboxed and cannot navigate or open windows', () => {
  const fn = main.slice(main.indexOf('async function openBundledPdfViewer'),
    main.indexOf("ipcMain.handle('open-report-version'"));
  assert.match(fn, /sandbox: true/);
  assert.match(fn, /nodeIntegration: false/);
  assert.match(fn, /contextIsolation: true/);
  assert.match(fn, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/);
  assert.match(fn, /will-navigate/);
  assert.doesNotMatch(fn, /preload/);
});

test('the Word version stays optional and the PDF button is first', () => {
  const reports = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'reports.js'), 'utf8');
  assert.ok(reports.indexOf('data-report-preview="pdf"') < reports.indexOf('data-report-preview="docx"'));
});
