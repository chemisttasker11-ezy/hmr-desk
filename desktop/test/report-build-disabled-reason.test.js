const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../renderer/helpers.js');

test('no findings gives a visible reason, one or more gives none', () => {
  assert.match(H.buildDisabledReason(0), /at least one finding/);
  assert.equal(H.buildDisabledReason(1), '');
  assert.equal(H.buildDisabledReason(7), '');
});

test('the editor shows the reason in the build status line and on both disabled buttons', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/report-editor.js'), 'utf8');
  assert.match(source, /esc\(reportBuildStatus \|\| H\.buildDisabledReason\(reportRecord\.issues\.length\)\)/);
  assert.equal((source.match(/disabled title="\$\{esc\(H\.buildDisabledReason\(0\)\)\}"/g) || []).length, 2);
});
