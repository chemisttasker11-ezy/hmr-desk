'use strict';
// The alternative picker wording must not claim a historical stopped name is a current fact, and must say when it is needed.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(require.resolve('../renderer/reports.js'), 'utf8');

test('alternative picker label says it is only needed when saving asks, and refers to the recorded interview status', () => {
  assert.match(source, /Only needed if saving asks for it\. If this medicine shares an ingredient with one recorded as not using in the interview/);
  assert.doesNotMatch(source, /If a stopped medicine shares an ingredient, enter the exact name/);
});

test('the picker is still offered when a medicine is recorded as not using, so ingredient-mode alternatives stay possible', () => {
  assert.match(source, /some\(item => item\.status === 'not_using'\) \? `<label>Only needed/);
  assert.match(source, /<select name="alternative">/);
});
