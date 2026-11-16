const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

test('referral review keeps other edited rows when a row is committed or another PDF is selected', async () => {
  const listeners = {}, nodes = { screen: {}, 'referral-results': {}, 'referral-status': {} };
  const document = { addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); } };
  let onDrop;
  const ctx = vm.createContext({ document, $: id => nodes[id], esc: H.esc, formOpen: false, page: 'intake',
    FormData: class { constructor(form) { return Object.entries(form.values); } },
    hmr: { onReferralDrop: fn => { onDrop = fn; }, referralPick: async () => ({rows:[{file:'third.pdf',status:'review', fields:{name:'Third'}}]}), api: async () => ({patient_id:9}) },
    errorText: e => e.message, openPatientWorkspace: async () => {} });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/intake.js'), 'utf8'), ctx);
  vm.runInContext("referralRows = [{file:'first.pdf',status:'review',token:'a',fields:{name:'First'}},{file:'second.pdf',status:'review',token:'b',fields:{name:'Second'}}]", ctx);
  await ctx.intake();
  const second = {dataset:{referralCommit:'1'}, values:{name:'Corrected Second'}};
  listeners.input[0]({target:{closest: () => second}});
  assert.equal(ctx.formOpen, true);
  const first = {dataset:{referralCommit:'0'}, values:{name:'First'}, querySelector: selector => selector === 'button' ? {} : {}};
  await listeners.submit[0]({target:{closest: () => first}, preventDefault(){}});
  assert.match(nodes['referral-results'].innerHTML, /Corrected Second/);
  assert.equal(ctx.formOpen, true);
  const button = {dataset:{referralPick:'files'}};
  await listeners.click[0]({target:{closest: () => button}});
  assert.match(nodes['referral-results'].innerHTML, /Corrected Second/);
  assert.match(nodes['referral-results'].innerHTML, /third.pdf/);
  onDrop({rows:[{file:'fourth.pdf',status:'error'}]});
  assert.match(nodes['referral-results'].innerHTML, /Corrected Second/);
});
