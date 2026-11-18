const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');
test('the submission note stops saying queued once no task is active', () => {
  const note = '2 task(s) queued (full flow for 1 patient(s)).\nSkipped: x';
  assert.equal(H.runStatusText(note, [{ state: 'done' }, { state: 'failed' }]), '2 task(s) submitted (full flow for 1 patient(s)). None still queued, running or waiting.\nSkipped: x');
  assert.equal(H.runStatusText(note, [{ state: 'running' }, { state: 'done' }]), '2 task(s) submitted (full flow for 1 patient(s)). 1 still queued, running or waiting.\nSkipped: x');
  assert.equal(H.runStatusText(note, undefined), note, 'no task list loaded: leave it alone');
  assert.equal(H.runStatusText('Nothing started: x', []), 'Nothing started: x');
  assert.equal(H.runStatusText('', []), '');
});
