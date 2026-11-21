const { test } = require('node:test');
const assert = require('node:assert/strict');
const { shape, selectQueue, emptyQueueMessage } = require('../src/browser-queue');

test('one-off entries use the helper formats and require a folder and essential fields', () => {
  assert.deepEqual(
    shape('emims', { name: 'Example', meds: 'Aspirin, Brand\nMetformin', allergies: 'Penicillin' }, 'C:/x'),
    { folder: 'Example', folder_path: 'C:/x', meds: [['Aspirin', 'Brand'], 'Metformin'], allergies: ['Penicillin'] },
  );
  assert.equal(shape('mhr', { last: 'Example', dob: '01-Jan-1980', sex: 'F', ihi: '123' }, 'C:/x').ihi, '123');
  assert.throws(() => shape('mhr', { last: 'Example' }, 'C:/x'));
  assert.throws(() => shape('emims', { name: 'Example', meds: 'A' }, ''));
});

test('browser lists only contain matching waiting patients, or all entries when none wait', () => {
  const entries = [{ id: 1 }, { id: 2 }];
  const tasks = [
    { id: 'a', patient_id: 2, state: 'waiting', waiting_for: 'emims' },
    { id: 'b', patient_id: 1, state: 'done', waiting_for: 'emims' },
  ];
  assert.deepEqual(selectQueue('emims', entries, tasks).entries, [entries[1]]);
  assert.deepEqual(selectQueue('mhr', entries, tasks).entries, entries);
  assert.deepEqual(selectQueue('emims', [], tasks).entries, []);
});

test('an empty queue says why when the build has no helper, and stays the plain message otherwise', () => {
  assert.equal(emptyQueueMessage({ lists: [], helper_available: false, message: ' The eMIMS list helper is not installed. ' }), 'The eMIMS list helper is not installed.');
  assert.equal(emptyQueueMessage({ lists: [], helper_available: true }), 'Nothing to run');
  assert.equal(emptyQueueMessage({ lists: [] }), 'Nothing to run');  // an older engine without the field
  assert.equal(emptyQueueMessage([]), 'Nothing to run');
  assert.equal(emptyQueueMessage({ helper_available: false, message: 5 }), 'Nothing to run');
  assert.equal(emptyQueueMessage({ helper_available: false, message: 'x'.repeat(900) }).length, 400);
});
