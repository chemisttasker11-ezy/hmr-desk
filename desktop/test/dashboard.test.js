const { test } = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers');
test('attention actions have the requested labels and a fallback', () => {
  const labels = { open_interview: 'Open interview', not_visited: 'Did not happen', visited: 'Record visit', open_messages: 'Open messages', offer: 'Offer a new time', pathology: 'Collect pathology', interview_sheet: 'Make sheet', open_report: 'Open report', claim: 'Open claim', followup1: 'Open follow-up form', followup2: 'Open follow-up form', expired: 'Mark expired', retry: 'Retry', check_phone: 'Check phone' };
  for (const [action, label] of Object.entries(labels)) assert.equal(H.attentionLabel(action), label);
  assert.equal(H.attentionLabel('other'), 'Open patient');
});
test('attention details format fields and escape patient data', () => {
  assert.equal(H.attentionDetail({ time: '10:00', suburb: 'Pimpama', pathology_done: false }, 'today_visits'), '10:00 &middot; Pimpama &middot; pathology missing');
  assert.equal(H.attentionDetail({ visit_date: '2026-11-12', visit_time: '09:00' }, 'offers_passed'), 'Offered for 12/11/2026 09:00');
  assert.equal(H.attentionDetail({ days_left: -22 }, 'referrals'), 'Expired 22 days ago');
  assert.equal(H.attentionDetail({ reply: '<yes>' }, 'replies_waiting'), '&quot;&lt;yes&gt;&quot;');
  assert.equal(H.attentionDetail({ detail: 'Waiting' }, 'reports'), 'Waiting');
});
test('dashboard groups, confirmation and retry follow the engine actions', async () => {
  const vm = require('node:vm'), fs = require('node:fs');
  const groups = [
    { key: 'today_visits', title: 'Visits', items: [{ patient_id: 1, name: 'Alex', action: 'not_visited', time: '10:00' }] },
    { key: 'stuck', title: 'Stuck', items: [{ patient_id: null, name: 'Batch', action: 'retry', step: 'pathology' }] },
    { key: 'reports', title: 'Reports', items: [] },
  ];
  const nodes = { screen: {}, 'attention-confirm-today_visits-0': {}, 'attention-status': {} }, calls = [];
  const context = vm.createContext({ H, esc: H.esc, page: 'today', formOpen: false, selected: null,
    $: (id) => nodes[id], hmr: { api: async (...args) => { calls.push(args); return { groups }; } },
    enqueue: async (...args) => { calls.push(args); }, runMessage: 'Queued' });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/dashboard.js'), 'utf8'), context);
  await context.dashboard();
  assert.ok(nodes.screen.innerHTML.indexOf('Stuck') < nodes.screen.innerHTML.indexOf('All clear'));
  assert.match(nodes.screen.innerHTML, /No reports waiting/);
  await context.dashboardClick({ dataset: { attentionGroup: 'today_visits', attentionIndex: '0' } });
  assert.equal(context.formOpen, true);
  assert.match(nodes['attention-confirm-today_visits-0'].innerHTML, /Mark as not visited/);
  await context.dashboardClick({ dataset: { attentionGroup: 'today_visits', attentionIndex: '0', attentionYes: '1' } });
  assert.equal(context.formOpen, false);
  assert.equal(calls[1][1], '/api/patients/1/action');
  assert.equal(calls[1][2].action, 'not_visited');
  await context.dashboardClick({ dataset: { attentionGroup: 'stuck', attentionIndex: '0' } });
  assert.equal(calls.at(-1)[0][0], 'pathology');
  assert.equal(calls.at(-1)[1].length, 0);
});
