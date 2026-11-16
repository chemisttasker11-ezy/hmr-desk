const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { inside } = require('../src/folder');
test('patient folder must be strictly inside the configured base', () => {
  const base = path.resolve('base');
  assert.equal(inside(base, path.join(base, 'patient')), true);
  assert.equal(inside(base, base), false);
  assert.equal(inside(base, path.resolve('base-other', 'patient')), false);
  assert.equal(inside(base, path.resolve(base, '..', 'patient')), false);
});
