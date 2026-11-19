const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');

test('a finished build says what was built and where the files are', () => {
  assert.equal(H.buildOutcomeText({ state: 'done', output: 'Built Synthetic-v2.docx' }, false), 'Word built: Built Synthetic-v2.docx. The files are in the patient folder.');
  assert.equal(H.buildOutcomeText({ state: 'done', output: '' }, true), 'Word and PDF built. The files are in the patient folder.');
});

test('a failed build says it did not finish and gives the first line of the reason', () => {
  assert.equal(H.buildOutcomeText({ state: 'failed', output: 'Local PDF conversion failed; prior Word draft preserved. Reason: x\nmore' }, true), 'Build did not finish: Local PDF conversion failed; prior Word draft preserved. Reason: x');
  assert.equal(H.buildOutcomeText(null, false), 'Build did not finish');
});
