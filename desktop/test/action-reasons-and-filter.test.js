'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'renderer', f), 'utf8');

test('disabled Build, Signed off and Report sent buttons show their reason as visible text', () => {
  const src = read('patients.js');
  assert.equal((src.match(/class="action-reason"/g) || []).length, 3);
});

test('the Found medicines table draws the filter that it applies, and a new patient resets it', () => {
  const src = read('interview.js');
  assert.equal((src.match(/data-interview-progress-filter/g) || []).length === 2, true);
  assert.match(src, /previous !== target\) interviewProgressFilter = 'all'/);
});
