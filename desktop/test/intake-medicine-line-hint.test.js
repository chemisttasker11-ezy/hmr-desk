const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// The engine makes one interview row per non-empty line of this box and never splits on semicolons.
// The label must say so, so a reviewer does not type several medicines on one line.
test('intake medicines box says one medicine per line', () => {
  const source = fs.readFileSync(path.join(__dirname, '../renderer/intake.js'), 'utf8');
  assert.match(source, /<label>Prescribed medicines \/ directions \(one medicine per line\)<textarea name="clinical_medicines"/);
});
