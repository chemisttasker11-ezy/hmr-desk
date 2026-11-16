'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');
const lookup = read('renderer', 'medicine-lookup.js');

test('lookup script loads before the interview and the row template calls it', () => {
  const html = read('index.html');
  assert.ok(html.indexOf('renderer/medicine-lookup.js') > 0 && html.indexOf('renderer/medicine-lookup.js') < html.indexOf('renderer/interview.js'));
  assert.match(read('renderer', 'interview.js'), /interviewLookupControls\(key, meta, i\)/);
});

test('results are built with textContent, never inserted as HTML', () => {
  const body = lookup.slice(lookup.indexOf('async function medicineLookupClick'));
  assert.doesNotMatch(body, /innerHTML/);
  assert.match(body, /textContent/);
});

test('the pharmacist chooses; no automatic link and free text stays valid', () => {
  assert.match(lookup, /Use this/);
  assert.match(lookup, /Keep typing the name by hand/);
  assert.doesNotMatch(lookup, /results\[0\]\)\s*;?\s*interviewRecord/);
});

test('rendered link escapes values from the reference file', () => {
  const ctx = { H: { esc: (v) => String(v).replace(/</g, '&lt;') } };
  const fn = new Function('H', lookup.slice(0, lookup.indexOf('async function medicineLookupClick')) + '; return interviewLookupControls;')(ctx.H);
  const html = fn('meds', { reference: { source: 'amt', code: '1', display: '<img src=x>', release: '20260101' } }, 0);
  assert.ok(!html.includes('<img'));
  assert.match(html, /Linked: &lt;img src=x>/);
  assert.doesNotMatch(fn('meds', {}, 0), /Linked/);
});
