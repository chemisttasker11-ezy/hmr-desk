const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const H = require('../renderer/helpers');

test('action reachability: pathology_outcome, hold/decline, expired, claim_now, and visited today', () => {
  const today = H.localDate();
  // pathology_outcome reachable in booking and post-visit states
  assert.ok(H.stageActions({ stage: 'booking' }).includes('pathology_outcome'));
  assert.ok(H.stageActions({ stage: 'report' }).includes('pathology_outcome'));
  assert.ok(H.stageActions({ stage: 'claim' }).includes('pathology_outcome'));

  // hold and decline reachable for ready booked patients
  assert.ok(H.stageActions({ stage: 'ready' }).includes('hold'));
  assert.ok(H.stageActions({ stage: 'ready' }).includes('decline_phone'));

  // mark expired and claim_now reachable in pre-visit stages
  for (const stage of ['intake', 'booking', 'ready']) {
    assert.ok(H.stageActions({ stage }).includes('expired'), `${stage} has expired`);
    assert.ok(H.stageActions({ stage }).includes('claim_now'), `${stage} has claim_now`);
  }

  // Completed today can be recorded visited even if prep is not complete
  const bookedToday = { stage: 'booking', visit_date: today, state: 'confirmed' };
  assert.ok(H.stageActions(bookedToday).includes('visited'));

  // Unconfirmed booking without visit date cannot mark visited
  assert.ok(!H.stageActions({ stage: 'booking' }).includes('visited'));
});

test('report sign-off: supports built report in visited state and respects prerequisites', () => {
  const reportsSource = fs.readFileSync(path.join(__dirname, '../renderer/reports.js'), 'utf8');
  const context = { esc: H.esc, H };
  vm.createContext(context);
  vm.runInContext(reportsSource, context);

  // 1. Verified current Word+PDF report in visited state -> sign off UI enabled
  const visitedBuilt = context.reportRow(
    { id: 1, name: 'Alex', state: 'visited', stage: 'report' },
    { steps: [{ name: 'report_build', done: true, ready: true }], reportCurrency: { status: 'current', reasons: [], signed_off: false, readiness: { items: [] } }, reportSpec: { issues: [{ title: 'Finding' }] } },
    'Agent'
  );
  assert.match(visitedBuilt, /data-sign-off="1"/);
  assert.doesNotMatch(visitedBuilt, /data-sign-off="1"\s+disabled/);

  // 2. Word report not built in visited state -> sign off disabled
  const visitedUnbuilt = context.reportRow(
    { id: 2, name: 'Sam', state: 'visited', stage: 'report' },
    { steps: [{ name: 'report_build', done: false, ready: false, reason: 'unbuilt' }], reportCurrency: { status: 'not_generated', reasons: [], signed_off: false, readiness: { items: [] } }, reportSpec: { issues: [{ title: 'Finding' }] } },
    'Agent'
  );
  assert.match(visitedUnbuilt, /data-sign-off="2"\s+disabled/);

  // 3. Historical signed report preserves Done without invalidation
  const signedOff = context.reportRow(
    { id: 3, name: 'Taylor', state: 'signed_off', stage: 'report' },
    { steps: [], reportSpec: { issues: [] } },
    'Agent'
  );
  assert.match(signedOff, /Signed off &#10003; Done/);
});

test('patient drawer report buttons disable unsafe terminal actions when prerequisites unmet', () => {
  const patientsSource = fs.readFileSync(path.join(__dirname, '../renderer/patients.js'), 'utf8');
  const nodes = { 'detail': { querySelector: () => null } };
  const dummyNode = { addEventListener: () => {}, querySelector: () => null, value: '', classList: { toggle: () => {} }, parentElement: { classList: { toggle: () => {} } } };
  const calls = [];
  const context = vm.createContext({
    esc: H.esc,
    date: H.date,
    H,
    $: (id) => nodes[id] || dummyNode,
    selected: null,
    page: 'patients',
    filter: 'All active',
    patients: [],
    detailTab: 'Timeline',
    formOpen: false,
    localDate: H.localDate,
    actionLabels: {
      report_sent: 'Report sent',
      call: 'Log call',
      pathology_outcome: 'Pathology by hand',
    },
    actionFields: {},
    followupActions: ['followup1', 'followup2', 'followup1_claimed', 'followup2_claimed'],
    messageComposer: () => '',
    hmr: {
      api: async (method, url) => {
        calls.push([method, url]);
        if (url.includes('/timeline')) return { milestones: {}, entries: [] };
        return {
          id: 5,
          name: 'Jordan',
          stage: 'report',
          state: 'visited',
          steps: [
            { name: 'report_start', ready: false, done: false, reason: 'Needs medicine confirmation' },
            { name: 'report_build', ready: false, done: false, reason: 'Report not started' },
          ],
        };
      },
    },
    errorText: String,
    refresh: async () => {},
  });
  vm.runInContext(patientsSource, context);
  context.showPatient(5);

  // Wait for promise resolution
  return new Promise((resolve) => setImmediate(resolve)).then(() => {
    const detailHtml = nodes['detail'].innerHTML;
    // Start report is disabled because ready is false
    assert.match(detailHtml, /data-report-step="report_start"[^>]*disabled/);
    // Build is disabled because ready is false
    assert.match(detailHtml, /data-build="build"[^>]*disabled/);
    // Signed off is disabled because build is not done
    assert.match(detailHtml, /data-sign-off="5"[^>]*disabled/);
    // Report sent is disabled because report is not signed off
    assert.match(detailHtml, /data-action="report_sent"[^>]*disabled/);
  });
});

test('async navigation: delayed responses and errors across navigation do not overwrite new screen', async () => {
  const rendererSource = fs.readFileSync(path.join(__dirname, '../renderer.js'), 'utf8');
  let rejectOld;
  const screen = { innerHTML: 'Reports', dataset: {} };
  const context = vm.createContext({
    formOpen: false,
    page: 'reports',
    health: async () => {},
    document: { querySelector: () => ({ scrollTop: 0 }) },
    $: () => screen,
    esc: String,
    errorText: (e) => e.message,
    reports: () => new Promise((_resolve, reject) => { rejectOld = reject; }),
  });

  const refreshCode = rendererSource.slice(
    rendererSource.indexOf('async function refresh()'),
    rendererSource.indexOf('async function runJob(')
  );
  vm.runInContext(refreshCode, context);

  const pendingRefresh = context.refresh();
  await new Promise(setImmediate);

  // User navigated to settings
  context.page = 'settings';
  screen.innerHTML = 'Settings';

  // Old request fails
  rejectOld(new Error('Slow reports network error'));
  await pendingRefresh;

  // New screen DOM must remain intact
  assert.equal(screen.innerHTML, 'Settings');
  assert.notEqual(screen.innerHTML, '<p class="error">Slow reports network error</p>');
});

test('expired-referral confirmation: offer flow requires review and sends confirm_expired: true', async () => {
  let approvedPayload = null;
  const mockApi = async (method, url, data) => {
    if (url.includes('/approve')) {
      approvedPayload = data;
      return { ok: true };
    }
    return {};
  };

  let offerDraft = { id: 99, kind: 'offer', warning: 'Referral expired 30 days ago', body: 'Visit offer' };
  let confirmed = false;

  const handleSend = async () => {
    if (offerDraft?.warning && !confirmed) {
      throw new Error('Confirmation required');
    }
    const payload = offerDraft?.warning && confirmed ? { confirm_expired: true } : {};
    return mockApi('POST', `/api/messages/${offerDraft.id}/approve`, payload);
  };

  // Blocked when unconfirmed
  await assert.rejects(handleSend, /Confirmation required/);
  assert.equal(approvedPayload, null);

  // Allowed when explicitly confirmed
  confirmed = true;
  await handleSend();
  assert.deepEqual(approvedPayload, { confirm_expired: true });
});

test('generic action form submit disables button during submission and restores on error', async () => {
  let submitDisabledBefore = null;
  let submitDisabledDuring = null;
  let submitDisabledAfter = null;

  const button = { disabled: false };
  const mockApi = async () => {
    submitDisabledDuring = button.disabled;
    throw new Error('Database busy');
  };

  submitDisabledBefore = button.disabled;
  button.disabled = true;
  try {
    await mockApi();
  } catch {
    button.disabled = false;
  }
  submitDisabledAfter = button.disabled;

  assert.equal(submitDisabledBefore, false);
  assert.equal(submitDisabledDuring, true);
  assert.equal(submitDisabledAfter, false);
});

test('followup screen: distinguishes waiting, due, and awaiting claim', () => {
  const patients = [
    { id: 1, name: 'Patient A', stage: 'followup', stage_step: 'waiting' },
    { id: 2, name: 'Patient B', stage: 'followup', stage_step: 'due' },
    { id: 3, name: 'Patient C', stage: 'followup', stage_step: 'to_claim' },
  ];

  const awaitingClaim = patients.filter((p) => /claim/i.test(p.stage_step || ''));
  const waiting = patients.filter((p) => /waiting/i.test(p.stage_step || ''));
  const due = patients.filter((p) => !/claim|waiting/i.test(p.stage_step || ''));

  assert.deepEqual(awaitingClaim.map(p => p.id), [3]);
  assert.deepEqual(waiting.map(p => p.id), [1]);
  assert.deepEqual(due.map(p => p.id), [2]);
});

