'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../renderer/intake.js'), 'utf8');
function setup(status, flags) {
  const target = {innerHTML: ''};
  const context = {document: {addEventListener() {}}, hmr: {onReferralDrop() {}},
    $: () => target, esc: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')};
  vm.createContext(context);
  vm.runInContext(source, context);
  context.fixture = {status, flags, file:'synthetic.pdf', kind:'referral', fields:{name:'synthetic person',suburb:'testville'}, patient_id:status === 'added' ? 1 : undefined};
  vm.runInContext('referralRows = [fixture]; renderReferrals()', context);
  return {context, target};
}
test('original warnings remain labelled as provenance after reviewed suburb is saved', () => {
  const {context, target} = setup('added', ['Missing suburb', 'Missing phone']);
  assert.match(target.innerHTML, /Original extraction warnings \(before your review\)/);
  assert.match(target.innerHTML, /patient was added with the fields you reviewed/);
  assert.match(target.innerHTML, /not a check of your corrected fields/);
  assert.match(target.innerHTML, /Missing suburb<br>Missing phone/);
  assert.equal(context.fixture.fields.suburb, 'testville');
  assert.deepEqual(context.fixture.flags, ['Missing suburb', 'Missing phone']);
  assert.match(target.innerHTML, /Open patient/);
});
test('pending review never claims fields have already been saved', () => {
  const {target} = setup('review', ['Missing suburb']);
  assert.match(target.innerHTML, /Original extraction warnings/);
  assert.doesNotMatch(target.innerHTML, /patient was added with the fields you reviewed/);
  assert.match(target.innerHTML, /name="suburb" value="testville"/);
});
test('warning markup is escaped and empty warnings produce no provenance block', () => {
  assert.match(setup('added', ['<synthetic>']).target.innerHTML, /&lt;synthetic&gt;/);
  assert.doesNotMatch(setup('added', []).target.innerHTML, /referral-extraction-warnings/);
});
