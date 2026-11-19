'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'renderer', f), 'utf8');

test('empty allergies and conditions in the report editor say unknown, not none', () => {
  const src = read('report-editor.js');
  assert.match(src, /data-report-unrecorded/);
  assert.match(src, /unknown, not "none"/);
  assert.match(src, /key === 'allergies' \|\| key === 'conditions'/);
});

test('the medicines panel warns when the interview allergies differ from the earlier confirmed list', () => {
  const src = read('reports.js');
  assert.match(src, /allergies_confirmed_earlier/);
  assert.match(src, /The interview now lists/);
  assert.match(src, /Check it, then save/);
});
