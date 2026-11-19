const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers');

test('with no single next action but real choices, the panel names them and opens them', () => {
  const hint = H.nextActionHint(null, 7);
  assert.equal(hint.openOthers, true);
  assert.match(hint.text, /choose what happened next/);
});

test('with no action at all the old wording stays and nothing is opened', () => {
  assert.deepEqual(H.nextActionHint(null, 0), { text: 'Review this patient before continuing.', openOthers: false });
});

test('with a primary action there is no hint and the other actions stay collapsed', () => {
  assert.deepEqual(H.nextActionHint('interview', 3), { text: '', openOthers: false });
});
