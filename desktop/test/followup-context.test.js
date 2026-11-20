'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '..', 'renderer/followup-context.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const render = new Function('H', code + ';return followupMedicineContextMarkup;')({esc});

test('context loads before interview and treats missing and failed records differently', () => {
  assert.ok(html.indexOf('renderer/followup-context.js') < html.indexOf('renderer/interview.js'));
  assert.match(render({available: false}), /Do not treat this as an empty current medicine list/);
  assert.match(render({error: true}), /could not be loaded/);
  assert.match(render({available: true, medicines: []}), /No medicine rows were recorded/);
});

test('read-only context escapes names and references, preserving not-using and free-text rows', () => {
  const result = render({available: true, medicines: [{name: '<img src=x>', origin: 'Referral', listed_directions: 'One daily', interview_directions: 'Half daily', use: 'Not using', reference: {source: 'amt', code: '1001', display: '<script>bad</script>', release: '20260101'}}]});
  assert.doesNotMatch(result, /<img|<script>/); assert.match(result, /&lt;img/);
  assert.match(result, /Not using/); assert.match(result, /AMT 1001, release 20260101/);
  assert.match(result, /not a confirmation of medicines used now/);
  assert.doesNotMatch(result, /<input|<textarea|<select/);
  assert.doesNotMatch(code, /hmr\.api|\.invoke|interviewRecord\s*=/);
});
