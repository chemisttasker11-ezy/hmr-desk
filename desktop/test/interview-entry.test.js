const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

test('interview controls preserve medicine identity, annotations, and explicit choices', async () => {
  const events = {};
  const dispatch = (name, event) => (events[name] || []).forEach(fn => fn(event));
  let changes = 0;
  const saver = { changed: () => changes++, save: async () => true, dirty: () => false };
  const context = vm.createContext({
    H: { ...H, autosaver: () => saver }, esc: H.esc, page: 'interview',
    document: { addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, querySelector: () => null },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = {meds: [['A','One daily','Actual use','', ''],['B','Twice daily','','','Human note'],['C','Daily','','AI suggestion','']], details: {daa:'yes', meds:[{packed:'unknown', as_instructed:false},{packed:'packed', as_instructed:false},{packed:'', as_instructed:false}]}}; renderInterview = () => {};`, context);
  const before = vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context);
  assert(before.indexOf('>B</textarea>') < before.indexOf('>A</textarea>'));
  assert(before.indexOf('>A</textarea>') < before.indexOf('>C</textarea>'));
  assert.match(before, /1m — 1 in the morning/);
  assert.match(before, /2bd — 2 twice daily/);
  assert.match(before, /PRN — When required/);
  assert.match(before, /value="unknown" checked/);
  assert.match(before, /data-badge-kind="note" >Note/);
  await vm.runInContext(`interviewClick({dataset:{interviewDetails:'meds',row:'1'}})`, context);
  assert.match(vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context), /data-interview-details="meds" data-row="1" aria-expanded="true"/);
  await vm.runInContext(`interviewClick({dataset:{interviewAsInstructed:'2'}})`, context);
  assert.equal(vm.runInContext('interviewRecord.details.meds[2].use_status', context), 'taking');
  assert.equal(vm.runInContext('interviewRecord.details.meds[2].as_instructed', context), true);
  assert.equal(vm.runInContext('interviewRecord.details.meds[2].checked', context), true);
  assert.equal(vm.runInContext('interviewRecord.meds[2][2]', context), 'Daily');
  const changesAfterQuick = changes;
  await vm.runInContext(`interviewClick({dataset:{interviewAsInstructed:'2'}})`, context);
  assert.equal(changes, changesAfterQuick);
  dispatch('input', { target: { dataset: { medDetail: 'checked', row: '2' }, type: 'checkbox', checked: false } });
  dispatch('input', { target: { dataset: { field: 'meds', row: '2', col: '2' }, type: 'text', tagName: 'INPUT', value: '' } });
  dispatch('input', { target: { dataset: { useField: 'use_status', useTable: 'meds', row: '0' }, value: 'not_using' } });
  dispatch('input', { target: { dataset: { useField: 'use_reason', useTable: 'meds', row: '0' }, value: 'side_effects' } });
  dispatch('input', { target: { dataset: { useField: 'use_details', useTable: 'meds', row: '0' }, value: 'Reported rash' } });
  assert.equal(vm.runInContext('interviewRecord.meds[0][1]', context), 'One daily');
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), 'Actual use');
  assert.doesNotMatch(vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context), />A<\/textarea>/);
  const stopped = vm.runInContext('interviewMedicineTable(interviewRecord.meds, true)', context);
  assert.match(stopped, /Side effects/);
  assert.match(stopped, /<textarea rows="1" hidden data-field="meds" data-row="0" data-col="2"/);
  assert.match(stopped, /<span hidden><select data-usage-preset/);
  dispatch('input', { target: { dataset: { medDetail: 'checked', row: '0' }, type: 'checkbox', checked: true } });
  await vm.runInContext(`interviewClick({dataset:{interviewTop:'0'}})`, context);
  vm.runInContext(`interviewRecord = JSON.parse(JSON.stringify(interviewRecord))`, context);
  assert.match(vm.runInContext('interviewMedicineTable(interviewRecord.meds, true)', context), />A<\/textarea>/);
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].checked', context), true);
  const savedPriority = vm.runInContext('interviewRecord.details.meds[0].priority', context);
  dispatch('input', { target: { dataset: { useField: 'use_status', useTable: 'meds', row: '0' }, value: 'taking' } });
  assert.match(vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context), />A<\/textarea>/);
  assert.doesNotMatch(vm.runInContext('interviewMedicineTable(interviewRecord.meds, true)', context), />A<\/textarea>/);
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].priority', context), savedPriority);
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].checked', context), true);
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), 'Actual use');
  dispatch('input', { target: { dataset: { medDetail: 'checked', row: '0' }, type: 'checkbox', checked: false } });
  assert.match(before, /3 remaining · 0 checked/);
  dispatch('input', { target: { dataset: { medDetail: 'checked', row: '1' }, type: 'checkbox', checked: true } });
  assert.equal(vm.runInContext('interviewRecord.details.meds[1].checked', context), true);
  assert.match(vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context), /2 remaining · 1 checked/);
  await vm.runInContext(`interviewClick({dataset:{interviewTop:'1'}})`, context);
  assert.equal(vm.runInContext('interviewRecord.details.meds[1].checked', context), true);
  assert.equal(vm.runInContext('interviewRecord.meds[1][0]', context), 'B');
  dispatch('input', { target: { dataset: { medDetail: 'checked', row: '1' }, type: 'checkbox', checked: false } });
  await vm.runInContext(`interviewClick({dataset:{interviewTop:'2'}})`, context);
  const moved = vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context);
  assert(moved.indexOf('>C</textarea>') < moved.indexOf('>B</textarea>'));
  dispatch('input', { target: { dataset: { interviewProgressFilter: '' }, value: 'checked' } });
  assert.doesNotMatch(vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context), />A<\/textarea>/);
  dispatch('input', { target: { dataset: { interviewProgressFilter: '' }, value: 'all' } });
  dispatch('input', { target: { dataset: { medDetail: 'as_instructed', row: '0' }, type: 'checkbox', checked: true } });
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), 'One daily');
  assert.match(vm.runInContext('interviewRecord.meds[0][4]', context), /Actual use/);
  dispatch('input', { target: { dataset: { field: 'meds', row: '0', col: '2' }, type: 'text', tagName: 'INPUT', value: 'Custom use' } });
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].as_instructed', context), false);
  dispatch('input', { target: { dataset: { usagePreset: '', row: '2' }, value: 'PRN' } });
  assert.equal(vm.runInContext('interviewRecord.meds[2][2]', context), 'When required');
  dispatch('input', { target: { dataset: { usagePreset: '', row: '0' }, value: '2bd' } });
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), '2 twice daily');
  assert.match(vm.runInContext('interviewRecord.meds[0][4]', context), /Custom use/);
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].as_instructed', context), false);
  await vm.runInContext(`interviewClick({dataset:{interviewRemove:'meds',row:'0'}})`, context);
  assert.equal(vm.runInContext('interviewRecord.meds[0][0]', context), 'B');
  assert.equal(vm.runInContext('interviewRecord.details.meds[0].packed', context), 'packed');
  await vm.runInContext(`interviewClick({dataset:{interviewAdd:'meds'}})`, context);
  assert.equal(vm.runInContext('interviewRecord.details.meds[2].packed', context), '');
  await vm.runInContext(`interviewClick({dataset:{interviewAdd:'other_meds'}})`, context);
  vm.runInContext(`interviewRecord.other_meds[0][0] = 'Found medicine'`, context);
  dispatch('input', { target: { dataset: { otherChecked: '', row: '0' }, checked: true } });
  assert.match(vm.runInContext('interviewOtherMedicineTable(interviewRecord.other_meds)', context), /0 remaining · 1 checked/);
  await vm.runInContext(`interviewClick({dataset:{interviewTopOther:'0'}})`, context);
  dispatch('input', { target: { dataset: { useField: 'use_status', useTable: 'other_meds', row: '0' }, value: 'not_using' } });
  dispatch('input', { target: { dataset: { useField: 'use_reason', useTable: 'other_meds', row: '0' }, value: 'ran_out_of_scripts' } });
  assert.match(vm.runInContext('interviewOtherMedicineTable(interviewRecord.other_meds)', context), /Ran out of scripts/);
  assert.equal(vm.runInContext('interviewRecord.details.other_meds[0].checked', context), true);
  assert.equal(vm.runInContext('interviewRecord.other_meds[0][0]', context), 'Found medicine');
  assert(changes >= 4);
});

test('medicine controls keep existing PRN details visible and protect empty referral directions', async () => {
  const events = {}, prn = { hidden: false }, button = {};
  let changes = 0;
  const context = vm.createContext({ H: { ...H, autosaver: () => ({ changed: () => changes++ }) }, esc: H.esc, page: 'interview',
    document: { addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, querySelector: selector => selector.startsWith('[data-prn-row') ? prn : selector.startsWith('[data-interview-as-instructed') ? button : null } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({meds: [['Medicine','  ','Daily','','']], details: {meds: [{prn_use:'Twice weekly'}]}}); renderInterview = () => {}`, context);
  let html = vm.runInContext('interviewMedicineTable(interviewRecord.meds)', context);
  assert.match(html, /data-prn-row="0" >How often used/);
  assert.match(html, /data-interview-as-instructed="0" disabled title="No referral directions to copy"/);
  assert.doesNotMatch(html, /aria-pressed/);
  await vm.runInContext(`interviewClick({dataset:{interviewAsInstructed:'0'}})`, context);
  assert.equal(vm.runInContext('interviewRecord.meds[0][2]', context), 'Daily');
  assert.equal(vm.runInContext('interviewRecord.meds[0][4]', context), '');
  assert.equal(changes, 0);
  const input = (col, value) => events.input.forEach(fn => fn({ target: { dataset: { field: 'meds', row: '0', col }, tagName: 'INPUT', value } }));
  input('2', 'Daily'); assert.equal(prn.hidden, false);
  input('1', 'Daily'); assert.equal(button.disabled, false);
  vm.runInContext('interviewRecord.details.meds[0].as_instructed = true', context);
  input('1', 'Nightly'); assert.equal(prn.hidden, false);
  vm.runInContext(`interviewRecord.details.meds[0].use_status = 'not_using'`, context);
  html = vm.runInContext('interviewMedicineTable(interviewRecord.meds, true)', context);
  assert.match(html, /data-prn-row="0" >How often used/);
});

test('interview Save and recovery choices call the saver and retain unresolved conflicts', async () => {
  const calls = [];
  let conflict = true, renders = 0;
  const status = { textContent: '' };
  const saver = {
    save: async force => { calls.push(['save', force]); return true; },
    resolveConflict: choice => { calls.push(['resolve', choice]); conflict = choice === 'restore'; },
    hasConflict: () => conflict,
  };
  const context = vm.createContext({
    H: { ...H, autosaver: () => saver }, esc: H.esc, page: 'interview',
    document: { addEventListener: () => {} }, countRender: () => renders++, patients: [], $: () => status,
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = {}; interviewConflict = true; renderInterview = () => countRender();`, context);
  vm.runInContext(`interviewStatus('Recovered local draft');`, context);
  assert.equal(status.textContent, 'Recovered local draft');
  const picker = vm.runInContext('interviewPicker()', context);
  assert.match(picker, /data-interview-resolve="restore"/);
  assert.match(picker, /data-interview-resolve="discard"/);
  await vm.runInContext(`interviewClick({dataset:{interviewSave:''}})`, context);
  await vm.runInContext(`interviewClick({dataset:{interviewResolve:'restore'}})`, context);
  assert.equal(vm.runInContext('interviewConflict', context), true);
  await vm.runInContext(`interviewClick({dataset:{interviewResolve:'discard'}})`, context);
  assert.equal(vm.runInContext('interviewConflict', context), false);
  assert.deepEqual(calls, [['save', true], ['resolve', 'restore'], ['resolve', 'discard']]);
  assert.equal(renders, 2);
});

test('legacy records acquire empty structured controls without altering existing clinical text', () => {
  const context = vm.createContext({ H: { ...H, autosaver: () => ({}) }, document: { addEventListener: () => {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  const result = vm.runInContext(`normalizeInterviewDetails({obs:[['Height / weight / BMI','170 cm / 70 kg','']], alcohol_smoking:'Never smoked', meds:[['Drug','Daily','Clinical note','','']]})`, context);
  assert.equal(result.obs[0][1], '170 cm / 70 kg');
  assert.equal(result.alcohol_smoking, 'Never smoked');
  assert.equal(result.details.smoking, '');
  assert.equal(result.details.height_referral, '');
  assert.equal(result.meds[0][2], 'Clinical note');
  assert.equal(result.details.meds[0].packed, '');
  const withReason = vm.runInContext("normalizeInterviewDetails({details:{reason:'Review', extra:'keep'}, meds:[[]]})", context);
  assert.equal(withReason.details.reason, 'Review');
  assert.equal(withReason.details.extra, 'keep');
  assert.equal(withReason.details.meds.length, 1);
});

test('Record visit waits for successful save and opens the existing date action for the same patient', async () => {
  const calls = []; let saveOk = false;
  const context = vm.createContext({
    H: { ...H, autosaver: () => ({ save: async force => { calls.push(['save', force]); return saveOk; } }) },
    page: 'interview', document: { addEventListener: () => {} },
    navigate: async id => { calls.push(['navigate', id]); context.page = id; },
    showPatient: async (id, action) => calls.push(['showPatient', id, action]),
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewId = '42'; interviewRecord = {};`, context);
  await vm.runInContext(`interviewClick({dataset:{interviewRecordVisit:''}})`, context);
  assert.deepEqual(calls, [['save', true]]);
  saveOk = true;
  await vm.runInContext(`interviewClick({dataset:{interviewRecordVisit:''}})`, context);
  assert.deepEqual(calls.slice(1), [['save', true], ['navigate', 'patients'], ['showPatient', '42', 'visited']]);
});


test('incomplete authorised signed checkbox persists as an unsigned draft until complete', () => {
  const events = {}; let changes = 0;
  const context = vm.createContext({ H: { ...H, autosaver: () => ({ changed: () => changes++ }) }, page: 'interview',
    document: { addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, querySelector: () => null } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext("interviewRecord = { consent: { signed:false, by:'authorised', relationship:0, authorised_name:'', date:'' } }", context);
  const input = (prop, value, type = 'text') => events.input.forEach(fn => fn({ target: { dataset: { field:'consent', prop }, type, value, checked: value } }));
  input('signed', true, 'checkbox');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), false);
  assert.equal(vm.runInContext('interviewRecord.consent_signed_draft', context), true);
  input('authorised_name', 'Representative'); input('relationship', '2');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), true);
  assert.equal(vm.runInContext('interviewRecord.consent_signed_draft', context), false);
  assert.equal(changes, 3);
});


test('signed intent remains a draft while authorised details are incomplete', () => {
  const events = {};
  const details = { hidden: false, querySelectorAll: () => [] };
  const context = vm.createContext({
    H: { ...H, autosaver: () => ({ changed() {} }) }, esc: H.esc, page: 'interview',
    $: () => details,
    document: { addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, querySelector: () => null },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = { consent: { signed: true, by: 'patient', relationship: 0, authorised_name: '', date: '' } }`, context);
  const input = (prop, value, type = 'text') => events.input.forEach(fn => fn({target: {dataset: {field: 'consent', prop}, type, tagName: 'INPUT', value}}));
  input('by', 'authorised');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), false);
  assert.equal(vm.runInContext('interviewRecord.consent_signed_draft', context), true);
  input('relationship', '2');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), false);
  input('authorised_name', 'Representative');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), true);
  input('authorised_name', '');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), false);
  assert.equal(vm.runInContext('interviewRecord.consent_signed_draft', context), true);
  events.input.forEach(fn => fn({target: {dataset: {field: 'consent', prop: 'signed'}, type: 'checkbox', tagName: 'INPUT', checked: false}}));
  input('authorised_name', 'Representative');
  assert.equal(vm.runInContext('interviewRecord.consent.signed', context), false);
});


test('outstanding interview counts reflect active lists, status, clarify and consent', () => {
  const record = { meds: [[], [], [], []], other_meds: [[]], details: { meds: [
    { use_status: 'taking', checked: true }, { use_status: 'unknown' },
    { use_status: '' }, { use_status: 'not_using', checked: true },
  ], other_meds: [{ checked: true }] }, clarify: ['One', '  ', '', 'Two'], consent: {} };
  assert.deepEqual(H.interviewOutstanding(record), { checked: 2, total: 4, withoutStatus: 2, clarify: 2, consentMissing: true, healthUnanswered: 0 });
  for (const signed of [{ consent_file: 'signed.pdf' }, { consent_signed_draft: true }, { consent: { signed: true } }]) {
    assert.equal(H.interviewOutstanding({ ...record, ...signed }).consentMissing, false);
  }
  assert.deepEqual(H.interviewOutstanding({}), { checked: 0, total: 0, withoutStatus: 0, clarify: 0, consentMissing: true, healthUnanswered: 0 });
  assert.equal(H.interviewOutstanding({ details: { sx_falls: 'not_asked' } }).healthUnanswered, 9);
});

test('outstanding chips show short labels with full accessible descriptions', () => {
  const context = vm.createContext({ H: { ...H, autosaver: () => ({}) }, esc: H.esc, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = {meds:[[],[],[]], details:{meds:[{checked:true,use_status:'taking'},{checked:true,use_status:'taking'},{}], sx_falls:'not_asked'}, clarify:['one','two','three']}`, context);
  const html = vm.runInContext('interviewOutstanding()', context);
  for (const [label, title] of [['2/3 checked','2 of 3 medicines checked'], ['1 no status','1 medicines without a status'], ['9 health check','9 health-check questions unanswered'], ['3 to clarify','3 to clarify'], ['Consent','Consent not signed']]) {
    assert.ok(html.includes(`title="${title}" aria-label="${title}">${label}</button>`));
  }
});

test('new interview entries retain old data and support conditional details', () => {
  const context = vm.createContext({ H: { ...H, autosaver: () => ({}) }, esc: H.esc, document: { addEventListener() {} } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({details:{extra:'keep', meds:[{}], other_meds:[{}]}, meds:[[]], other_meds:[[]]})`, context);
  assert.equal(vm.runInContext(`interviewEntryChoices.every(e => interviewRecord.details[e.key] === '' && (!e.detailWhen || interviewRecord.details[e.key + '_details'] === ''))`, context), true);
  assert.equal(vm.runInContext(`interviewRecord.details.extra`, context), 'keep');
  assert.equal(vm.runInContext(`interviewRecord.details.meds[0].prn_use + interviewRecord.details.other_meds[0].kind + interviewRecord.details.home_bp + interviewRecord.details.home_bgl + interviewRecord.details.smoking_details`, context), '');
  assert.match(vm.runInContext(`interviewEntry(interviewEntryChoices.find(e => e.key === 'sx_falls'))`, context), /data-entry-detail="sx_falls" hidden/);
  vm.runInContext(`interviewRecord.details.sx_falls = 'yes'`, context);
  assert.doesNotMatch(vm.runInContext(`interviewEntry(interviewEntryChoices.find(e => e.key === 'sx_falls'))`, context), /data-entry-detail="sx_falls" hidden/);
  vm.runInContext(`interviewRecord.details.sx_falls = 'no'; interviewRecord.details.sx_falls_details = 'kept'; interviewRecord.details.sx_pain = 'not_asked'; interviewMarkRemainingNo(interviewRecord.details)`, context);
  assert.equal(vm.runInContext(`interviewRecord.details.sx_pain`, context), 'not_asked');
  assert.equal(vm.runInContext(`interviewRecord.details.sx_falls_details`, context), 'kept');
  assert.doesNotMatch(vm.runInContext(`interviewEntry(interviewEntryChoices.find(e => e.key === 'sx_falls'))`, context), /data-entry-detail="sx_falls" hidden/);
  assert.equal(vm.runInContext(`interviewRecord.details.sx_sleep`, context), 'no');
  assert.equal(vm.runInContext(`interviewPrnVisible('when required for pain') && interviewPrnVisible('Take PRN') && !interviewPrnVisible('daily')`, context), true);
  assert.deepEqual(Array.from(vm.runInContext(`interviewSections.map(s => s[0])`, context)), ['notes','concerns','social','manages_meds','meds','other_meds','not_using_meds','allergies','health_check','alcohol_smoking','obs','conditions','pathology','clarify','consent']);
});

test('found medicine kind is stored using its contract code', () => {
  const events = {};
  const context = vm.createContext({ H: { ...H, autosaver: () => ({ changed() {} }) }, page: 'interview',
    document: { addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, querySelector: () => null } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewRecord = normalizeInterviewDetails({meds: [], other_meds: [[]]})`, context);
  events.input.forEach(fn => fn({ target: { dataset: { useField: 'kind', useTable: 'other_meds', row: '0' }, value: 'otc' } }));
  assert.equal(vm.runInContext('interviewRecord.details.other_meds[0].kind', context), 'otc');
});

test('record visit date defaults to a booked date only when it is not future', () => {
  assert.equal(H.visitDefaultDate({ visit_date: '2026-11-01' }, '2026-11-16'), '2026-11-01');
  assert.equal(H.visitDefaultDate({ visit_date: '2026-11-16' }, '2026-11-16'), '2026-11-16');
  assert.equal(H.visitDefaultDate({ visit_date: '2026-11-17' }, '2026-11-16'), '2026-11-16');
  assert.equal(H.visitDefaultDate({}, '2026-11-16'), '2026-11-16');
});
