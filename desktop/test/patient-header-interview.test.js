'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const read = (f) => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');

test('the patient header always offers an Interview button for the shown patient', () => {
  const src = read('renderer/patients.js');
  const head = src.match(/<div class="detail-head">[\s\S]*?<button class="detail-close"/)[0];
  assert.match(head, /<button data-open-interview="\$\{esc\(p\.id\)\}"[^>]*>Interview<\/button>/);
});

test('that button runs the existing openInterview path only (no stage action, no task)', () => {
  const r = read('renderer.js');
  const line = r.split('\n').find(l => l.includes('b.dataset.openInterview'));
  assert.match(line, /return await openInterview\(b\.dataset\.openInterview\)/);
  assert.doesNotMatch(line, /run-task|hmr\.api|action/);
});
