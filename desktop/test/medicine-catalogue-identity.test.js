const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({ H: {}, document: { addEventListener() {} } });
vm.runInContext(fs.readFileSync(require.resolve('../renderer/medicine-lookup.js'), 'utf8') + '\nthis.catalogueIdentity = catalogueIdentity;', context);
const identity = (listings) => JSON.parse(JSON.stringify(context.catalogueIdentity(listings)));

test('a group whose listings agree carries the catalogue generic and brand', () => {
  assert.deepEqual(identity([{ generic_name: 'G', brand_name: 'B' }, { generic_name: 'G', brand_name: 'B' }]), { generic_name: 'G', brand_name: 'B' });
});
test('a group that mixes brands carries the generic only, brand stays unknown', () => {
  assert.deepEqual(identity([{ generic_name: 'G', brand_name: 'B1' }, { generic_name: 'G', brand_name: 'B2' }]), { generic_name: 'G' });
});
test('missing, blank or null catalogue names are never filled in', () => {
  assert.deepEqual(identity([{ generic_name: null, brand_name: '' }]), {});
  assert.deepEqual(identity([]), {});
  assert.deepEqual(identity(undefined), {});
  assert.deepEqual(identity([{ generic_name: 'G' }, { brand_name: 'B' }]), {});
});
test('the display label is not consulted', () => {
  assert.deepEqual(identity([{ display: 'Brandex | Tablet 20 mg' }]), {});
});
