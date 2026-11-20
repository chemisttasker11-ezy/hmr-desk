const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');

test('digits without separators get a hint and the text is not rewritten', () => {
  const rows = [['HbA1c', '7.1', '01102026', ''], ['eGFR', '60', '1/10/2026', ''], ['K', '4', '011026', ''], ['Na', '140', '', '']];
  assert.deepEqual(H.pathologyDateHints(rows), [
    'Row 1: "01102026" has no separators. Write it as DD/MM/YYYY so the day and month cannot be misread.',
    'Row 3: "011026" has no separators. Write it as DD/MM/YYYY so the day and month cannot be misread.',
  ]);
  assert.equal(rows[0][2], '01102026');
});

test('separated, empty, or non-date text gets no hint', () => {
  for (const value of ['01/10/2026', '1-10-26', '2026-10-01', 'Oct 2026', '', '  ', '12345', '123456789', null, undefined, 'unknown'])
    assert.equal(H.dateTextHint(value), '', String(value));
  assert.deepEqual(H.pathologyDateHints(undefined), []);
});
