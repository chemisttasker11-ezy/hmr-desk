// Regression coverage for the recorded-observations panel integrity fixes:
// 1. failed reload clears cached observations and shows the error
// 2. late completion from a previous patient/request generation is rejected
// 3. a candidate-checks failure cannot take down the pathology editor load
// 4. the panel anchor is unique (no clash with the Observations form section)
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function setup(apiImpl) {
  let html = '';
  const screenEl = { set innerHTML(v) { html = v; }, get innerHTML() { return html; },
    querySelector: () => null, focus: () => {} };
  const saver = { changed: () => {}, save: async () => true, dirty: () => false,
    reset: () => ({}), leave: async () => true, hasConflict: () => false,
    offlineDraft: () => null };
  const autosaverConfigs = [];
  const mountedContent = { innerHTML: '<table><tbody><tr><td>old rows</td></tr></tbody></table>' };
  const listeners = {};
  const context = vm.createContext({
    H: { ...H, autosaver: config => { autosaverConfigs.push(config); return saver; } }, esc: H.esc, page: 'interview',
    errorText: e => String(e && e.message || e),
    patients: [{ id: 1, name: 'Synthetic A' }, { id: 2, name: 'Synthetic B' }],
    hmr: { api: apiImpl }, growInterview: () => {},
    $: id => (id === 'screen' ? screenEl : null),
    document: { addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); },
      querySelector: () => null, querySelectorAll: () => [],
      getElementById: id => (id === 'observations-content' ? mountedContent : null) },
    window: { innerHeight: 900, scrollX: 0, scrollY: 0, scrollTo: () => {}, scrollBy: () => {} },
    crypto: { randomUUID: () => 'cccccccc-cccc-cccc-cccc-' + String(Math.random()).slice(2, 14) },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({
      meds: [], other_meds: [], obs: [], notes: '',
      details: { meds: [], other_meds: [] }, saved: true });
    interviewId = '1'; interviewRequest = 7;`, context);
  return { context, html: () => html, autosaverConfigs, mountedContent, listeners };
}

const candidatePayload = marker => ({ observations: [], review_status: 'pharmacist_review_required',
  unassessed_pathology_ids: [],
  limitations: ['Check output is an arithmetic observation, not a clinical finding.', 'Synthetic limitation ' + marker] });

test('failed reload clears cached observations and surfaces the error', async () => {
  let calls = 0;
  const { context } = setup(async (method, path) => {
    calls++;
    if (path.endsWith('/candidate-checks')) throw new Error('Interview medicines changed; reload and review');
    return {};
  });
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify(candidatePayload('cached'))};
    interviewCandidateChecksError = '';`, context);
  await vm.runInContext('interviewLoadCandidateChecks(7)', context);
  assert.equal(vm.runInContext('interviewCandidateChecks', context), null);
  assert.match(vm.runInContext('interviewCandidateChecksError', context), /reload and review/i);
  assert.equal(calls, 1);
});

test('a late completion from a previous patient or request is rejected', async () => {
  const deferred = [];
  const { context } = setup((method, path) => {
    if (path.endsWith('/candidate-checks')) return new Promise(resolve => deferred.push(resolve));
    return Promise.resolve({});
  });
  const first = vm.runInContext('interviewLoadCandidateChecks(7)', context);
  // Patient switch: generation advances and interviewId changes before the fetch settles.
  vm.runInContext(`interviewRequest = 8; interviewId = '2'; interviewCandidateChecks = null; interviewCandidateChecksError = '';`, context);
  deferred[0](candidatePayload('stale-A'));
  await first;
  assert.equal(vm.runInContext('interviewCandidateChecks', context), null, 'stale result must not render');
  assert.equal(vm.runInContext('interviewCandidateChecksError', context), '');
  // Same generation, patient changed mid-flight: also rejected.
  vm.runInContext(`interviewRequest = 9;`, context);
  const second = vm.runInContext('interviewLoadCandidateChecks(9)', context);
  vm.runInContext(`interviewId = '1';`, context);
  deferred[1](candidatePayload('stale-B'));
  await second;
  assert.equal(vm.runInContext('interviewCandidateChecks', context), null, 'wrong-patient result must not render');
  // Current generation and patient: accepted.
  vm.runInContext(`interviewRequest = 10;`, context);
  const third = vm.runInContext('interviewLoadCandidateChecks(10)', context);
  deferred[2](candidatePayload('current'));
  await third;
  assert.equal(vm.runInContext('interviewCandidateChecks.limitations[1]', context), 'Synthetic limitation current');
  assert.equal(vm.runInContext('interviewCandidateChecksStale', context), false);
  // A late error from an old generation is rejected too: start a load, advance
  // the generation, then reject its fetch - the current state must not change.
  vm.runInContext(`interviewRequest = 11;`, context);
  const failing = vm.runInContext('interviewLoadCandidateChecks(11).catch(() => {})', context);
  vm.runInContext(`interviewRequest = 12; interviewCandidateChecksError = '';`, context);
  deferred[3](Promise.reject(new Error('late failure')));
  await failing;
  assert.equal(vm.runInContext('interviewCandidateChecks.limitations[1]', context), 'Synthetic limitation current');
  assert.equal(vm.runInContext('interviewCandidateChecksError', context), '');
});

test('evidence epoch: out-of-order reloads and fetch-before-save never install old evidence', async () => {
  const deferred = [];
  const { context } = setup((method, path) => {
    if (path.endsWith('/candidate-checks')) return new Promise(resolve => deferred.push(resolve));
    return Promise.resolve({});
  });
  // Two reloads for the same patient complete out of order: the older one must lose.
  const older = vm.runInContext('interviewLoadCandidateChecks(7)', context);
  const newer = vm.runInContext('interviewLoadCandidateChecks(7)', context);
  deferred[1](candidatePayload('newer'));
  await newer;
  assert.match(vm.runInContext('interviewCandidateChecks.limitations[1]', context), /newer/);
  deferred[0](candidatePayload('older'));
  await older;
  assert.match(vm.runInContext('interviewCandidateChecks.limitations[1]', context), /newer/,
    'out-of-order older completion must not overwrite the newer result');
  // A GET begun before a save/edit completes after it: the epoch bump on edit
  // makes the completion reject, leaving the stale flag set.
  const before = vm.runInContext('interviewLoadCandidateChecks(7)', context);
  vm.runInContext('interviewInvalidateObservations()', context); // what an edit/save does
  deferred[2](candidatePayload('pre-save'));
  await before;
  assert.equal(vm.runInContext('interviewCandidateChecksStale', context), true,
    'pre-save evidence must not reset the stale flag');
  assert.match(vm.runInContext('interviewCandidateChecks.limitations[1]', context), /newer/,
    'pre-save evidence must not be installed');
});

test('evidence edits hide the mounted panel immediately, without rerendering the form', async () => {
  const { context, mountedContent, listeners } = setup(async () => ({}));
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify(candidatePayload('mounted'))};
    interviewCandidateChecksStale = false;
    interviewPathology = { revision: 1, records: [{ id: 'x', test: 'eGFR', value: '28', unit: 'mL/min/1.73m2', reference_interval: '60-120', sample_date: '2026-11-10', source: 'synthetic.pdf page 1', verified: true, comment: '' }] };`, context);
  assert.match(mountedContent.innerHTML, /old rows/, 'panel starts mounted with data');
  // Drive the real document input handler with a pathology cell edit.
  const input = { dataset: { pathologyEntry: '0', pathologyField: 'value' }, value: '31', closest: () => input };
  for (const fn of listeners.input || []) fn({ target: input });
  assert.match(mountedContent.innerHTML, /Observations hidden/,
    'pathology edit must hide mounted observations immediately');
  assert.doesNotMatch(mountedContent.innerHTML, /old rows/);
  assert.equal(vm.runInContext('interviewPathology.records[0].value', context), '31',
    'the edit itself still lands');
  assert.equal(vm.runInContext('interviewCandidateChecksStale', context), true);
  // An interview field edit through the real change path does the same.
  vm.runInContext(`interviewCandidateChecksStale = false;`, context);
  mountedContent.innerHTML = '<table><tbody><tr><td>old rows</td></tr></tbody></table>';
  vm.runInContext(`interviewChanged('meds')`, context);
  assert.match(mountedContent.innerHTML, /Observations hidden/,
    'interview edit must hide mounted observations immediately');
});

test('a candidate-checks failure does not block pathology editor load', async () => {
  const pathologyPayload = { revision: 1, records: [] };
  const { context, html } = setup(async (method, path) => {
    if (path.endsWith('/pathology-records')) return pathologyPayload;
    if (path.endsWith('/pathology/sources')) return { sources: [] };
    if (path.endsWith('/candidate-checks')) throw new Error('Saved evidence changed during checks; reload and review');
    if (path.endsWith('/interview')) return { meds: [], other_meds: [], obs: [], notes: '', details: {}, consent: {} };
    return {};
  });
  vm.runInContext(`interviewRecord = null; interviewId = '1';`, context);
  await vm.runInContext('interviewScreen()', context);
  assert.deepEqual(vm.runInContext('interviewPathology', context), pathologyPayload);
  assert.equal(vm.runInContext('interviewPathologyError', context), '');
  assert.equal(vm.runInContext('interviewCandidateChecks', context), null);
  assert.match(vm.runInContext('interviewCandidateChecksError', context), /reload and review/i);
  assert.match(html(), /Saved evidence changed during checks/);
});

test('panel anchor is unique across the rendered interview page', async () => {
  const { context, html } = setup(async () => ({}));
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify(candidatePayload('x'))};`, context);
  vm.runInContext('renderInterview()', context);
  const ids = [...html().matchAll(/id="(section-[^"]+)"/g)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length, 'duplicate section ids: ' + ids.join(','));
  assert(ids.includes('section-recorded-lab-observations'));
  assert(!ids.includes('section-observations'), 'must not shadow the Observations nav anchor');
});

test('post-save observations hide until reloaded (no stale-as-current)', async () => {
  let saved = false;
  const { context, html, autosaverConfigs } = setup(async (method, path) => {
    if (path.endsWith('/candidate-checks')) return candidatePayload('v1');
    if (path.endsWith('/interview') && method === 'POST') { saved = true; return { revision: '2' }; }
    return {};
  });
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify(candidatePayload('v1'))};
    interviewCandidateChecksStale = false;`, context);
  // Drive the real autosaver endpoint wrapper (manual and autosaves share it).
  const endpoint = autosaverConfigs[0].endpoint;
  await endpoint('1', { meds: [] });
  assert.equal(saved, true);
  assert.equal(vm.runInContext('interviewCandidateChecksStale', context), true);
  vm.runInContext('renderInterview()', context);
  assert.match(html(), /Observations hidden/);
  assert.doesNotMatch(html(), /Synthetic limitation v1/);
  // Reload clears the flag and shows fresh data.
  await vm.runInContext('interviewLoadCandidateChecks(7)', context);
  vm.runInContext('renderInterview()', context);
  assert.match(html(), /Synthetic limitation v1/);
  assert.doesNotMatch(html(), /Observations hidden/);
});

test('unverified coverage and zero-verified states are explicit', async () => {
  const { context, html } = setup(async () => ({}));
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify({
      observations: [], review_status: 'pharmacist_review_required',
      unassessed_pathology_ids: ['pathology:unverified-1'], limitations: 'Same-row arithmetic only.' })};`, context);
  vm.runInContext('renderInterview()', context);
  assert.match(html(), /No verified pathology results are available to this check/);
  assert.match(html(), /not reassurance/i);
  assert.match(html(), /not covered by any observation/);
});

test('pathology add/remove/use-source invalidate observations immediately', async () => {
  const { context, mountedContent } = setup(async () => ({}));
  vm.runInContext(`interviewCandidateChecks = ${JSON.stringify(candidatePayload('x'))};
    interviewCandidateChecksStale = false;
    interviewPathology = { revision: 1, records: [{ id: 'x', test: 'eGFR', value: '28', unit: '', reference_interval: '', sample_date: '', source: '', verified: false, comment: '' }] };
    pathologySourceIndex = { sources: [{ id: 's1', name: 'synthetic.pdf', page_count: 2, sha256: 'a'.repeat(64), pages: [] }] };`, context);
  for (const click of [
    { dataset: { pathologyAdd: '' } },
    { dataset: { pathologyRemove: '0' } },
    { dataset: { pathologyUseSource: 's1', sourcePage: '1' } },
  ]) {
    mountedContent.innerHTML = '<table><tbody><tr><td>old rows</td></tr></tbody></table>';
    vm.runInContext('interviewCandidateChecksStale = false; renderInterview = () => {};', context);
    await vm.runInContext(`interviewClick(${JSON.stringify(click).replace(/"/g, "'").replace(/'/g, '"')})`, context);
    assert.match(mountedContent.innerHTML, /Observations hidden/,
      'click ' + JSON.stringify(click.dataset) + ' must hide observations immediately');
    assert.equal(vm.runInContext('interviewCandidateChecksStale', context), true);
  }
});

test('a late pathology save response after switching patient is dropped', async () => {
  const deferred = [];
  const { context } = setup((method, path) => {
    if (path.endsWith('/pathology-records') && method === 'POST')
      return new Promise(resolve => deferred.push(resolve));
    return Promise.resolve({});
  });
  vm.runInContext(`interviewId = '1'; interviewRequest = 7;
    interviewPathology = { revision: 1, records: [] };
    interviewPathologyDirty = true;`, context);
  const saving = vm.runInContext('savePathologyRecords()', context);
  // Patient switch while the save is in flight.
  vm.runInContext(`interviewRequest = 8; interviewId = '2'; interviewPathology = null; interviewPathologyError = '';`, context);
  deferred[0]({ revision: 2, records: [] });
  const result = await saving;
  assert.equal(result, false, 'stale save must report failure, not success');
  assert.equal(vm.runInContext('interviewPathology', context), null,
    'old patient records must not install after switching');
  assert.equal(vm.runInContext('interviewPathologyError', context), '');
});

test('pathology import response after switching patient is dropped', async () => {
  const deferred = [];
  const { context, html } = setup((method, path) => {
    if (path.endsWith('/pathology/sources')) return new Promise(resolve => deferred.push(resolve));
    return Promise.resolve({});
  });
  vm.runInContext(`interviewId = '1'; interviewRequest = 7;
    hmr.pickPathologySource = async () => ({ cancelled: false }); renderInterview = () => {};`, context);
  const importing = vm.runInContext(`interviewClick({ dataset: { pathologyImport: '' } })`, context);
  await new Promise(resolve => setImmediate(resolve)); // let the pick resolve so the sources fetch starts
  vm.runInContext(`interviewRequest = 8; interviewId = '2'; pathologySourceIndex = { sources: [] }; interviewCandidateChecksStale = false;`, context);
  assert.equal(deferred.length, 1, 'sources fetch must be in flight');
  deferred[0]({ sources: [{ id: 'late', name: 'late.pdf', page_count: 1, sha256: 'b'.repeat(64), pages: [] }] });
  await importing;
  assert.equal(JSON.stringify(vm.runInContext('pathologySourceIndex', context)), '{"sources":[]}',
    'late import sources must not install after switching');
});
