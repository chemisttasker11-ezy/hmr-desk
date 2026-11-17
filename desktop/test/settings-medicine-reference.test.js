'use strict';
// Settings medicine-reference install: truthful result wording and safe status refresh.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../renderer/settings.js'), 'utf8');
const clickCode = source.slice(source.indexOf('async function agentClick'), source.indexOf('async function agentSubmit'));

const SRC = { source: 'amt', release: '20261031', row_count: 171257 };
const STALE = 'No medicine reference installed. Type medicine names by hand.';

function setup(hmr) {
  const elements = new Map();
  const el = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', innerHTML: '', dataset: {}, disabled: false });
    return elements.get(id);
  };
  el('medicine-reference-persistent').textContent = STALE;
  const context = vm.createContext({
    $: el,
    esc: s => String(s),
    errorText: e => (e && e.message) ? e.message : String(e),
    hmr,
    confirm: () => true,
    alert: () => {},
  });
  vm.runInContext(clickCode, context);
  return { context, el };
}

const button = () => ({ dataset: { medicineReferenceInstall: '' }, disabled: false });

test('first install reports no retained previous reference and refreshes the status line', async () => {
  const { context, el } = setup({
    installMedicineReference: async () => ({ installed: true, sources: [SRC], previous_retained: false }),
    api: async (method, path) => ({ installed: true, sources: [SRC] }),
  });
  const b = button();
  await context.agentClick(b);
  assert.equal(el('medicine-reference-status').textContent, 'Medicine reference installed: amt 20261031 (171257 records).');
  assert.equal(el('medicine-reference-persistent').textContent, 'Installed: amt 20261031 (171257 records)');
  assert.equal(b.disabled, false);
});

test('replacing an existing reference says the previous one is retained', async () => {
  const { context, el } = setup({
    installMedicineReference: async () => ({ installed: true, sources: [SRC], previous_retained: true }),
    api: async () => ({ installed: true, sources: [SRC] }),
  });
  await context.agentClick(button());
  assert.equal(el('medicine-reference-status').textContent, 'Medicine reference installed: amt 20261031 (171257 records). Previous reference retained for rollback.');
});

test('a failed status refresh never rewrites the install truth or claims a false state', async () => {
  const { context, el } = setup({
    installMedicineReference: async () => ({ installed: true, sources: [SRC], previous_retained: false }),
    api: async () => { throw new Error('engine gone'); },
  });
  await context.agentClick(button());
  const out = el('medicine-reference-status').textContent;
  assert.ok(out.startsWith('Medicine reference installed: amt 20261031 (171257 records).'));
  assert.ok(out.includes('Status line above refreshes next time you open Settings.'));
  assert.equal(el('medicine-reference-persistent').textContent, STALE);
});

test('a cancelled install leaves every line untouched and never re-fetches status', async () => {
  let apiCalls = 0;
  const { context, el } = setup({
    installMedicineReference: async () => ({ cancelled: true }),
    api: async () => { apiCalls++; return { installed: true, sources: [SRC] }; },
  });
  await context.agentClick(button());
  assert.equal(el('medicine-reference-status').textContent, 'Medicine reference installation cancelled; current reference unchanged');
  assert.equal(el('medicine-reference-persistent').textContent, STALE);
  assert.equal(apiCalls, 0);
});

test('a rejected file reports the error, keeps the current reference claim, and never re-fetches', async () => {
  let apiCalls = 0;
  const { context, el } = setup({
    installMedicineReference: async () => { throw new Error('The selected file could not be read as a valid medicine reference database'); },
    api: async () => { apiCalls++; return {}; },
  });
  await context.agentClick(button());
  assert.equal(el('medicine-reference-status').textContent, 'The selected file could not be read as a valid medicine reference database Current reference unchanged.');
  assert.equal(el('medicine-reference-persistent').textContent, STALE);
  assert.equal(apiCalls, 0);
});
