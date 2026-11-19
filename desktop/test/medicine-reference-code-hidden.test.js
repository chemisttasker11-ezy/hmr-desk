'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const read = (f) => fs.readFileSync(path.join(__dirname, '..', 'renderer', f), 'utf8');

test('no renderer prints a PBS catalogue code for a linked medicine; other sources keep theirs', () => {
  for (const file of ['reports.js', 'followup-context.js', 'medicine-lookup.js']) {
    const src = read(file);
    assert.match(src, /source === 'pbs' \? 'PBS'/, file);
  }
  const lookup = read('medicine-lookup.js');
  const fn = new Function('H', lookup.slice(0, lookup.indexOf('async function medicineLookupClick')) + '; return interviewLookupControls;')({esc: (v) => String(v)});
  const pbs = fn('meds', {reference: {source: 'pbs', code: 'GE:1001A:9001', display: 'Brandex | Tablet 20 mg | pack 30 | oral', release: 'SYN'}}, 0);
  assert.doesNotMatch(pbs, /1001A|9001/);
  assert.match(pbs, /\(PBS, release SYN\)/);
  assert.match(fn('meds', {reference: {source: 'amt', code: '1001', display: 'X', release: 'R'}}, 0), /AMT 1001/);
});
