const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function setup(api) {
  const listeners = {}, nodes = { screen: {}, 'referral-results': {}, 'referral-status': {} };
  const document = { addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); } };
  const ctx = vm.createContext({ document, $: id => nodes[id], esc: H.esc, formOpen: false, page: 'intake',
    FormData: class { constructor(form) { return Object.entries(form.values); } },
    hmr: { onReferralDrop() {}, api }, errorText: e => e.message, openPatientWorkspace: async () => {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/intake.js'), 'utf8'), ctx);
  vm.runInContext("referralRows = [{file:'one.pdf',status:'review',token:'a'.repeat(32),fields:{name:'Synthetic One'},clinical:{allergies:'kept text',allergies_status:'explicit_none'}}]", ctx);
  const pending = { textContent: '' }, error = { textContent: 'old', scrolled: null, focused: null,
    scrollIntoView(options) { this.scrolled = options; }, focus(options) { this.focused = options; } };
  const button = { disabled: false, textContent: 'Confirm and add patient' };
  const values = { name: 'Synthetic One', clinical_allergies: 'kept text', clinical_allergies_status: 'explicit_none', clinical_page_allergies: '2' };
  const form = { dataset: { referralCommit: '0' }, values,
    querySelector: s => (s === 'button' ? button : s === '.referral-pending' ? pending : s === '.error' ? error : null) };
  return { ctx, listeners, nodes, pending, error, button, form, values };
}

test('markup has a pending line and a focusable alert paragraph after the button', async () => {
  const x = setup(async () => ({}));
  await x.ctx.intake();
  const html = x.nodes['referral-results'].innerHTML;
  assert.match(html, /Confirm and add patient<\/button><p class="referral-pending" role="status"><\/p><p class="error" role="alert" tabindex="-1"><\/p>/);
});

test('a refused add shows the reason, scrolls and focuses it, re-enables the button and keeps every entered value', async () => {
  const x = setup(async () => { throw new Error('Explicitly no known allergies cannot be combined with an allergy list'); });
  await x.ctx.intake();
  const settled = x.listeners.submit[0]({ target: { closest: () => x.form }, preventDefault() {} });
  await settled;
  assert.equal(x.button.disabled, false);
  assert.equal(x.button.textContent, 'Confirm and add patient');
  assert.equal(x.pending.textContent, '');
  assert.match(x.error.textContent, /^Not added: Explicitly no known allergies cannot be combined with an allergy list$/);
  assert.equal(JSON.stringify(x.error.scrolled), JSON.stringify({ block: 'center', behavior: 'smooth' }));
  assert.equal(JSON.stringify(x.error.focused), JSON.stringify({ preventScroll: true }));
  // the form was not re-rendered: values the pharmacist typed are untouched, and the stored row still has them
  assert.equal(x.values.clinical_allergies, 'kept text');
  assert.equal(vm.runInContext('referralRows[0].status', x.ctx), 'review');
  assert.equal(vm.runInContext('referralRows[0].clinical.allergies', x.ctx), 'kept text');
});

test('while the add is pending the button is disabled with a clear status and no timeout is imposed', async () => {
  let finish; const answer = new Promise(resolve => { finish = resolve; });
  const x = setup(() => answer);
  await x.ctx.intake();
  const settled = x.listeners.submit[0]({ target: { closest: () => x.form }, preventDefault() {} });
  assert.equal(x.button.disabled, true);
  assert.equal(x.button.textContent, 'Adding patient...');
  assert.match(x.pending.textContent, /Adding the patient\. Wait for the result before trying again\./);
  assert.equal(x.error.textContent, '');
  finish({ patient_id: 7 });
  await settled;
  assert.equal(vm.runInContext('referralRows[0].status', x.ctx), 'added');
  assert.equal(vm.runInContext('referralRows[0].patient_id', x.ctx), 7);
  const source = fs.readFileSync(require.resolve('../renderer/intake.js'), 'utf8');
  assert.doesNotMatch(source, /setTimeout|AbortController|AbortSignal/);
});
