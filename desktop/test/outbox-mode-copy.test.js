const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');

test('test-mode banner does not imply that nothing can be sent or that other actions are blocked', () => {
  const src = read('renderer/messages.js');
  assert.ok(src.includes('Test mode - only the test phone receives messages'));
  assert.ok(src.includes('can still be sent'));
  assert.ok(src.includes('does not stop reports, claims or portal actions'));
});

test('Outbox chip explains that test mode is not a no-send mode', () => {
  const src = read('renderer.js');
  assert.ok(src.includes('Not a no-send mode'));
  assert.ok(src.includes('Live: text messages can reach patients'));
});
