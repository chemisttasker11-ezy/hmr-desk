const interviewSections = [
  ['notes', 'Interview notes'],
  ['concerns', 'Concerns and goals'],
  ['social', 'Visit and living'],
  ['manages_meds', 'Managing medicines'],
  ['meds', 'Referral medicines being used or still to confirm'],
  ['other_meds', 'Medicines found during interview'],
  ['not_using_meds', 'Referral medicines not using'],
  ['allergies', 'Allergies / adverse reactions'],
  ['health_check', 'Health check'],
  ['alcohol_smoking', 'Alcohol / smoking'],
  ['obs', 'Observations'],
  ['conditions', 'Current conditions'],
  ['pathology', 'Pathology'],
  ['clarify', 'To clarify'],
  ['consent', 'PPA consent'],
];
const interviewHealthKeys = ['falls', 'dizziness', 'drowsiness', 'pain', 'sleep', 'bowel', 'bladder', 'mood', 'memory', 'appetite'].map(name => `sx_${name}`);
const interviewYesNo = [['no','No'], ['yes','Yes'], ['not_asked','Not asked']];
const interviewEntryChoices = [
  { key: 'present', label: 'Present at the visit', options: [['alone','Patient alone'],['with_other','With carer or family']], detailWhen: ['with_other'], detailLabel: 'Who was present (name / relationship)' },
  { key: 'lives', label: 'Lives', options: [['alone','Alone'],['partner','With partner'],['family','With family'],['other','Other']] },
  { key: 'missed_doses', label: 'Missed doses', options: [['none','None'],['sometimes','Sometimes'],['often','Often'],['not_asked','Not asked']], detailWhen: ['sometimes','often'] },
  { key: 'device_technique', label: 'Inhaler / device technique', options: [['ok','OK'],['issues','Issues'],['none','No devices'],['not_checked','Not checked']], detailWhen: ['issues'] },
  { key: 'swallowing', label: 'Swallowing problems', options: interviewYesNo, detailWhen: ['yes'] },
  { key: 'recent_change', label: 'Recent hospital or specialist change', options: interviewYesNo, detailWhen: ['yes'] },
  ...['Falls in the last 12 months','Dizziness on standing','Drowsiness','Pain','Sleep problems','Bowel problems','Bladder problems','Low mood or anxiety','Memory problems','Appetite or weight change'].map((label, i) => ({ key: interviewHealthKeys[i], label, options: interviewYesNo, detailWhen: ['yes'] })),
];
const interviewTables = {
  obs: ['Measure', 'Referral', 'At interview'],
  meds: ['Medicine', 'Referral directions', 'Actually taking', 'Points to check', 'Notes'],
  other_meds: ['Medicine', 'Directions', 'Why or who', 'Notes'],
  pathology: ['Test', 'Result', 'Date', 'Comment'],
};
let interviewId = '',
  interviewRecord = null;
let interviewSaveStatus = 'Ready', interviewConflict = false, interviewProgressFilter = 'all';
let interviewReconciliation = null;
let interviewPathology = null, interviewPathologyDirty = false, interviewPathologyError = '';
let pathologySourceIndex = {sources: []};
let interviewRequest = 0;
const interviewExpanded = new WeakSet();
function interviewEquivalent(a, b) {
  const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
  const withoutTechnicalIds = text => { const record = normalizeInterviewDetails(JSON.parse(text), true, false); for (const key of ['meds', 'other_meds']) for (const meta of record.details[key]) delete meta.item_id; return record; };
  try { return JSON.stringify(stable(withoutTechnicalIds(a))) === JSON.stringify(stable(withoutTechnicalIds(b))); } catch { return false; }
}
let interviewEdited = new Set(),
  interviewAgent = 'No agent selected', interviewAi = false,
  interviewOutput = '';
function interviewStatus(message) {
  interviewSaveStatus = message;
  if ($('interview-status')) $('interview-status').textContent = message;
}
const interviewSaver = H.autosaver({
  getRecord: () => interviewRecord,
  getId: () => interviewId,
  draftKey: () => `interview:${interviewId}`,
  equivalent: interviewEquivalent,
  loadCurrent: async (id) => { const current = normalizeInterviewDetails(await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/interview`)); current.consent = { signed: false, date: '', by: 'patient', relationship: 0, authorised_name: '', ...current.consent }; return current; },
  onReconcile: () => { interviewConflict = interviewSaver.hasConflict(); renderInterview(); },
  endpoint: (id, record) => hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/interview`, record),
  status: interviewStatus,
  errorText: (...args) => errorText(...args), // defined in renderer.js, which loads after this file
});
const interviewDirty = () => interviewSaver.dirty();
const saveInterview = (force = false) => interviewSaver.save(force);
const growInterview = H.growTextarea;
function interviewChanged(field) {
  interviewEdited.add(field);
  document.querySelector(`[data-source="${field}"]`)?.remove();
  interviewSaver.changed();
  if (['meds', 'other_meds', 'details'].includes(field)) interviewReconciliation = null;
  const summary = document.querySelector('#interview-outstanding');
  if (summary) summary.innerHTML = interviewOutstanding();
}
async function leaveInterview() {
  if (interviewPathologyDirty && !(await savePathologyRecords())) return false;
  if (!(await interviewSaver.leave())) return false;
  interviewRequest++;
  interviewRecord = null;
  interviewId = '';
  return true;
}
async function openInterview(id) {
  const target = String(id), previous = interviewId;
  if (page === 'interview' && interviewId !== target && !(await leaveInterview())) return { cancelled: true };
  interviewId = target;
  if (page !== 'interview') await navigate('interview');
  else await interviewScreen();
  if (page !== 'interview' || interviewId !== target) {
    if (page !== 'interview' && interviewId === target) interviewId = previous;
    return { cancelled: true };
  }
  return interviewRecord ? { ok: true } : { ok: false, error: 'Interview could not be opened' };
}
async function switchInterview(id) {
  if (id === interviewId) return;
  const old = interviewId;
  if (!(await leaveInterview())) {
    $('interview-patient').value = old;
    return;
  }
  interviewId = id;
  await interviewScreen();
}
function interviewPicker() {
  return `<div class="interview-picker"><label>Search patients<input id="interview-search" type="search"></label><label>Patient<select id="interview-patient"><option value="" ${interviewId ? '' : 'selected'} disabled>Choose a patient</option>${patients.map((p) => `<option value="${esc(p.id)}" ${String(p.id) === interviewId ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>${interviewRecord ? '' : `<button type="button" data-interview-save>Save</button><span id="interview-status" role="status">${esc(interviewSaveStatus)}</span>`}${interviewConflict ? '<span role="alert">A local draft differs from the saved form. <button type="button" data-interview-resolve="restore">Restore draft</button><button type="button" data-interview-resolve="discard">Keep saved form</button></span>' : ''}</div>`;
}
async function interviewScreen() {
  if (interviewRecord) return;
  const request = ++interviewRequest;
  $('screen').innerHTML = interviewPicker() + '<p>Loading patients...</p>';
  const [list, todayData, agents, settingsData] = await Promise.allSettled([
    hmr.api('GET', '/api/patients'), hmr.api('GET', '/api/today'), hmr.api('GET', '/api/agents'), hmr.api('GET', '/api/settings'),
  ]);
  if (page !== 'interview' || request !== interviewRequest) return;
  if (list.status === 'fulfilled') patients = list.value.patients || [];
  else patients = H.interviewDrafts().map(({ id, name }) => ({ id, name: name || `Patient ${id}` }));
  interviewAi = settingsData.status === 'fulfilled' && settingsData.value.settings?.find(x => x.key === 'ai_interview_assist')?.value === true;
  const agentData = agents.status === 'fulfilled' ? agents.value : {};
  interviewAgent = agentData.per_step?.interview_assist || agentData.default || 'No agent selected';
  interviewId ||= H.defaultInterviewId(todayData.status === 'fulfilled' ? todayData.value.visits : [], new Date());
  $('screen').innerHTML = interviewPicker();
  if (list.status === 'rejected') {
    $('screen').innerHTML += `<p class="error">Could not load patients: ${esc(errorText(list.reason))}. Local drafts are available in the patient list.</p>`;
  }
  if (!interviewId) {
    $('screen').innerHTML += '<p>Pick a patient to open their interview form.</p>';
    return;
  }
  let offline = false;
  try {
    const record = await hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/interview`);
    if (page !== 'interview' || request !== interviewRequest) return;
    interviewRecord = record;
  } catch (error) {
    if (page !== 'interview' || request !== interviewRequest) return;
    const draft = interviewSaver.offlineDraft();
    if (draft) { interviewRecord = draft; offline = true; }
    else {
    const message = String(error.message || error);
    const reason = /patient folder (?:is not a directory within BASE|missing)/i.test(message)
      ? 'This patient has no folder yet, so there is no interview form to open.' : errorText(error);
    $('screen').innerHTML = interviewPicker() + `<p class="error" role="alert">${esc(reason)}</p><button data-patient="${esc(interviewId)}">Open patient</button>`;
    return;
    }
  }
  interviewRecord.consent = {
    signed: false,
    date: '',
    by: 'patient',
    relationship: 0,
    authorised_name: '',
    ...interviewRecord.consent,
  };
  normalizeInterviewDetails(interviewRecord, false);
  const recovery = offline ? interviewSaver.resetOffline(interviewRecord) : interviewSaver.reset(interviewRecord);
  normalizeInterviewDetails(interviewRecord);
  interviewConflict = offline ? interviewSaver.hasConflict() : recovery.conflict;
  interviewEdited = new Set();
  interviewOutput = '';
  interviewReconciliation = null;
  interviewPathology = null; interviewPathologyDirty = false; interviewPathologyError = '';
  if (!offline) {
    try {
      [interviewPathology, pathologySourceIndex] = await Promise.all([
        hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/pathology-records`),
        hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/pathology/sources`),
      ]);
    } catch(e) { interviewPathologyError = errorText(e); }
    if (page !== 'interview' || request !== interviewRequest) return;
  }
  if (!offline && !recovery.recovered && !recovery.conflict && !recovery.storageError) interviewSaveStatus = interviewRecord.saved ? 'Saved' : 'Ready';
  renderInterview();
  $('interview-notes')?.focus();
}
function normalizeInterviewDetails(record, newEntries = true, assignIds = true) {
  if (!record.details) record.details = { version: 1, manager: '', manager_details: '', daa: '', daa_type: '', daa_pharmacy: '', smoking: '', alcohol: '', alcohol_details: '', height_referral: '', height_actual: '', weight_referral: '', weight_actual: '', bmi_referral: '', bmi_actual: '', height_as_listed: false, weight_as_listed: false, bmi_as_listed: false, meds: (record.meds || []).map(() => ({ packed: '', as_instructed: false })) };
  if (!record.details.meds) record.details.meds = (record.meds || []).map(() => ({ packed: '', as_instructed: false }));
  if (!record.details.other_meds) record.details.other_meds = (record.other_meds || []).map(() => ({ checked: false, priority: 0 }));
  for (const meta of record.details.meds) { if (meta.checked === undefined) meta.checked = false; if (meta.priority === undefined) meta.priority = 0; }
  for (const meta of [...record.details.meds, ...record.details.other_meds]) { meta.use_status ??= ''; meta.use_reason ??= ''; meta.use_details ??= ''; }
  if (assignIds) for (const meta of [...record.details.meds, ...record.details.other_meds]) meta.item_id ??= H.medicineItemId();
  if (!newEntries) return record;
  for (const entry of interviewEntryChoices) { record.details[entry.key] ??= ''; if (entry.detailWhen) record.details[entry.key + '_details'] ??= ''; }
  for (const key of ['smoking_details', 'home_bp', 'home_bgl']) record.details[key] ??= '';
  for (const meta of record.details.meds) meta.prn_use ??= '';
  for (const meta of record.details.other_meds) meta.kind ??= '';
  return record;
}
function interviewEntry(entry) {
  const { key, label, options, detailWhen, detailLabel } = entry;
  const detail = key + '_details';
  const visible = detailWhen && (detailWhen.includes(interviewRecord.details[key]) || !!interviewRecord.details[detail]);
  return `<div class="interview-entry"><span>${esc(label)}</span>${interviewChoices(key, label, options).replace('interview-choices', 'interview-choices interview-chips')}${detailWhen ? `<div data-entry-detail="${key}" ${visible ? '' : 'hidden'}>${interviewDetailText(detail, detailLabel || 'Details')}</div>` : ''}</div>`;
}
const interviewPrnVisible = value => /^when required/i.test(value || '') || /prn/i.test(value || '');
function interviewMarkRemainingNo(details) { for (const key of interviewHealthKeys) if (!details[key]) details[key] = 'no'; }
function interviewChoices(prop, title, choices) {
  const value = interviewRecord.details[prop];
  return `<fieldset class="interview-choices"><legend>${esc(title)}</legend>${choices.map(([v, label]) => `<label><input type="radio" name="detail-${prop}" data-detail="${prop}" value="${v}" ${value === v ? 'checked' : ''}> ${esc(label)}</label>`).join('')}</fieldset>`;
}
function interviewDetailText(prop, label) {
  return `<label>${esc(label)}<input data-detail="${prop}" value="${esc(interviewRecord.details[prop])}"></label>`;
}
const interviewUsagePresets = [['1m', '1 in the morning'], ['1 noon', '1 at noon'], ['1 evening', '1 in the evening'], ['1 night', '1 at night'], ['1bd', '1 twice daily'], ['2bd', '2 twice daily'], ['1tds', '1 three times daily'], ['1qid', '1 four times daily'], ['PRN', 'When required']];
const interviewPresetMatch = value => interviewUsagePresets.find(([code, text]) => [code, text].some(item => item.toLowerCase() === value.trim().toLowerCase()));
function interviewUpdatePreset(input) {
  const select = input.closest?.('.interview-actual')?.querySelector('[data-usage-preset]');
  if (!select) return;
  const value = input.value.trim().toLowerCase(), match = interviewPresetMatch(input.value);
  const matches = value ? interviewUsagePresets.filter(([code, text]) => code.toLowerCase().startsWith(value) || text.toLowerCase().startsWith(value)) : [];
  const options = matches.length ? matches : interviewUsagePresets;
  select.innerHTML = `<option value="">${matches.length && !match ? `${matches.length} matching presets` : 'Usage preset'}</option>` + options.map(([code, text]) => `<option value="${esc(code)}">${esc(code)} — ${esc(text)}</option>`).join('');
  select.value = match?.[0] || '';
}
function interviewSetUsage(i, value) {
  const row = interviewRecord.meds[i];
  if (row[2] && row[2] !== value) row[4] = [row[4], 'Previous actual use: ' + row[2]].filter(Boolean).join('\n');
  row[2] = value;
  const badge = document.querySelector(`[data-interview-badge=meds][data-row="${i}"][data-badge-kind=note]`); if (badge) badge.hidden = !row[4].trim();
  for (const col of [2, 4]) { const input = document.querySelector(`[data-field="meds"][data-row="${i}"][data-col="${col}"]`); if (input) { input.value = row[col]; growInterview(input); } }
}
function interviewSetMedicineDetail(i, prop, value) {
  interviewRecord.details.meds[i][prop] = value;
  if (prop === 'as_instructed' && value) interviewSetUsage(i, interviewRecord.meds[i][1]);
}
const interviewUseReasons = [['finished_course','Finished course'], ['stopped_gp','Stopped by GP'], ['stopped_specialist','Stopped by specialist'], ['self_ceased','Self ceased'], ['ran_out_of_scripts','Ran out of scripts'], ['side_effects','Side effects'], ['other','Other'], ['unknown','Unknown']];
function interviewUseControls(key, i, meta) {
  return `<fieldset class="interview-choices interview-chips"><legend>Medicine use</legend>${[['taking','Taking'],['not_using','Not using'],['unknown','Not yet confirmed']].map(([v,l]) => `<label><input type="radio" name="use-${key}-${i}" data-use-field="use_status" data-use-table="${key}" data-row="${i}" value="${v}" ${meta.use_status === v ? 'checked' : ''}> ${l}</label>`).join('')}</fieldset>${meta.use_status === 'not_using' ? `<label>Reason<select data-use-field="use_reason" data-use-table="${key}" data-row="${i}"><option value="">Choose reason</option>${interviewUseReasons.map(([v,l]) => `<option value="${v}" ${meta.use_reason === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label>Details (optional)<input data-use-field="use_details" data-use-table="${key}" data-row="${i}" value="${esc(meta.use_details)}"></label>` : ''}`;
}
function interviewMedicineRow(key, row, meta, i, notUsing = false) {
  const other = key === 'other_meds', expanded = interviewExpanded.has(meta);
  const field = (j, hidden = false) => `<textarea rows="1" ${hidden ? 'hidden' : ''} data-field="${key}" data-row="${i}" data-col="${j}" placeholder="${esc(interviewTables[key][j])}" aria-label="${esc(interviewTables[key][j])} row ${i + 1}">${esc(row[j] || '')}</textarea>`;
  const labelled = (text, control) => `<label class="med-field"><span class="med-field-label">${text}</span>${control}</label>`;
  const badge = (label, show, kind) => `<button type="button" class="interview-badge" data-interview-badge="${key}" data-row="${i}" data-badge-kind="${kind}" ${show ? '' : 'hidden'}>${esc(label)}</button>`;
  return `<tr class="${meta.checked ? 'interview-medicine-checked' : ''}"><td><div class="interview-medicine-main">
    <label class="interview-check"><input type="checkbox" ${other ? 'data-other-checked' : 'data-med-detail="checked"'} data-row="${i}" aria-label="Checked in interview for progress only; does not confirm use" ${meta.checked ? 'checked' : ''}> Checked</label>
    ${labelled('Medicine', field(0))}${typeof interviewLookupControls === 'function' ? interviewLookupControls(key, meta, i) : ''}${other ? '' : labelled('Directions on referral', field(1))}<div class="interview-actual">${notUsing ? '' : '<span class="med-field-label">' + (other ? 'Directions' : 'Actually taking') + '</span>'}${field(other ? 1 : 2, notUsing)}<span ${notUsing ? 'hidden' : ''}><select data-usage-preset="${key}" data-row="${i}" aria-label="Usage preset row ${i + 1}"><option value="">Usage preset</option>${interviewUsagePresets.map(([code, text]) => `<option value="${esc(code)}" ${interviewPresetMatch(row[other ? 1 : 2] || '')?.[0] === code ? 'selected' : ''}>${esc(code)} — ${esc(text)}</option>`).join('')}</select></span></div>
    ${other ? `<fieldset class="interview-choices interview-chips"><legend>Medicine kind</legend>${[['prescribed','Prescribed elsewhere'],['otc','Over the counter'],['complementary','Complementary or vitamin']].map(([v,l]) => `<label><input type="radio" name="kind-${i}" data-use-field="kind" data-use-table="other_meds" data-row="${i}" value="${v}" ${meta.kind === v ? 'checked' : ''}> ${l}</label>`).join('')}</fieldset>` : `<label data-prn-row="${i}" ${(meta.prn_use || (interviewPrnVisible(row[2]) && !notUsing)) ? '' : 'hidden'}>How often used<input data-med-detail="prn_use" data-row="${i}" value="${esc(meta.prn_use)}"></label>`}
    <div class="interview-medicine-actions">${interviewUseControls(key, i, meta)}${!other && !notUsing ? `<button type="button" class="${meta.as_instructed ? 'primary' : ''}" data-interview-as-instructed="${i}" ${row[1]?.trim() ? '' : 'disabled title="No referral directions to copy"'}>${meta.as_instructed ? '✓ ' : ''}As instructed</button>` : ''}
    <button type="button" data-interview-details="${key}" data-row="${i}" aria-expanded="${expanded}">Details</button></div>
    <div class="interview-badges">${badge('Note', !!row[other ? 3 : 4]?.trim(), 'note')}${other ? badge('Why or who', !!row[2]?.trim(), 'why') : badge('To check', !!row[3]?.trim(), 'check') + badge(`DAA: ${meta.packed}`, !!meta.packed, 'packed')}</div>
  </div><div class="interview-medicine-detail" ${expanded ? '' : 'hidden'}>
    ${other ? `<label>Why or who${field(2)}</label><label>Notes${field(3)}</label>` : `<label>Points to check (AI)${field(3)}</label><label>Notes${field(4)}</label>${interviewRecord.details.daa === 'yes' ? `<div>DAA packing<fieldset class="interview-choices interview-chips"><legend>DAA packing</legend>${[['packed','Packed'],['not packed','Not packed'],['unknown','Unknown']].map(([v,l]) => `<label><input type="radio" name="packed-${i}" data-med-detail="packed" data-row="${i}" value="${v}" ${meta.packed === v ? 'checked' : ''}> ${l}</label>`).join('')}</fieldset></div>` : ''}`}
    <button type="button" ${other ? `data-interview-top-other="${i}"` : `data-interview-top="${i}"`}>Move to top</button><button type="button" data-amh-row aria-label="Search AMH for medicine row ${i + 1}">AMH</button><button type="button" data-interview-remove="${key}" data-row="${i}">Remove</button>
  </div></td></tr>`;
}
function interviewMedicineTable(rows, notUsing = false) {
  rows ||= [];
  normalizeInterviewDetails(interviewRecord);
  const meta = interviewRecord.details.meds;
  const group = rows.map((row, i) => i).filter(i => (meta[i].use_status === 'not_using') === notUsing);
  const checked = group.filter(i => meta[i].checked).length;
  const order = group.filter(i => interviewProgressFilter === 'all' || (interviewProgressFilter === 'checked') === meta[i].checked).sort((a, b) => Number(meta[a].checked) - Number(meta[b].checked) || meta[b].priority - meta[a].priority || Number(!!rows[b][4].trim()) - Number(!!rows[a][4].trim()));
  return `<div class="interview-progress"><span>${group.length - checked} remaining · ${checked} checked</span><label>Show <select data-interview-progress-filter aria-label="Filter medicine progress">${[['all','All'],['remaining','Remaining'],['checked','Checked']].map(([v,l]) => `<option value="${v}" ${interviewProgressFilter === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div><div class="interview-table interview-medicines"><table><tbody>${order.map(i => interviewMedicineRow('meds', rows[i], meta[i], i, notUsing)).join('')}</tbody></table></div>${notUsing ? '' : '<button type="button" data-interview-add="meds">Add row</button>'}`;
}
function interviewOtherMedicineTable(rows) {
  rows ||= [];
  const meta = interviewRecord.details.other_meds, checked = meta.filter(m => m.checked).length;
  const order = rows.map((row, i) => i).filter(i => interviewProgressFilter === 'all' || (interviewProgressFilter === 'checked') === meta[i].checked).sort((a, b) => Number(meta[a].checked) - Number(meta[b].checked) || Number(meta[a].use_status === 'not_using') - Number(meta[b].use_status === 'not_using') || meta[b].priority - meta[a].priority || Number(!!rows[b][3].trim()) - Number(!!rows[a][3].trim()));
  return `<div class="interview-progress"><span>Other medicines found: ${rows.length - checked} remaining · ${checked} checked</span></div><div class="interview-table interview-medicines"><table><tbody>${order.map(i => interviewMedicineRow('other_meds', rows[i], meta[i], i)).join('')}</tbody></table></div><button type="button" data-interview-add="other_meds">Add row</button>`;
}
function interviewMoveFocus(el, key, change) {
  const row = el.closest?.('tr'), sectionId = row?.closest('section')?.id, col = key === 'meds' ? 2 : 1;
  const findUnchecked = direction => {
    for (let candidate = row?.[direction]; candidate; candidate = candidate[direction]) {
      const input = candidate.querySelector(`[data-field="${key}"][data-col="${col}"]`);
      const meta = input && interviewRecord.details[key][Number(input.dataset.row)];
      if (meta && !meta.checked && (key !== 'other_meds' || meta.use_status !== 'not_using')) return [candidate, input];
    }
    return [];
  };
  const forward = findUnchecked('nextElementSibling');
  const [next, nextInput] = forward.length ? forward : findUnchecked('previousElementSibling');
  const nextId = nextInput?.dataset.row, beforeControl = nextInput?.hidden ? next.querySelector('[data-med-detail="checked"], [data-other-checked]') : nextInput;
  const before = beforeControl?.getBoundingClientRect(), scrolls = [];
  for (let node = row?.parentElement; node; node = node.parentElement) if (node.scrollHeight > node.clientHeight && /(auto|scroll)/.test(getComputedStyle(node).overflowY)) scrolls.push([node, node.scrollTop]);
  const y = typeof window === 'undefined' ? 0 : window.scrollY;
  change(); renderInterview();
  for (const [node, position] of scrolls) if (node.isConnected) node.scrollTop = position;
  if (typeof window !== 'undefined') window.scrollTo(window.scrollX, y);
  let target = nextId === undefined ? null : document.querySelector(`[data-field="${key}"][data-row="${nextId}"][data-col="${col}"]`);
  if (target?.hidden) target = target.closest('tr')?.querySelector('[data-med-detail="checked"], [data-other-checked]');
  if (!target) target = sectionId && document.getElementById(sectionId)?.querySelector('h2');
  target?.focus({ preventScroll: true });
  if (nextId !== undefined && target && before) {
    const after = target.getBoundingClientRect(), scroller = scrolls.find(([node]) => node.isConnected)?.[0];
    const bounds = scroller?.getBoundingClientRect(), lower = Math.min(window.innerHeight, bounds?.bottom ?? window.innerHeight);
    let upper = Math.max(0, bounds?.top || 0);
    const main = document.querySelector('main'), mainTop = main?.getBoundingClientRect().top || 0;
    for (const overlay of document.querySelectorAll?.('main > header, .interview-context') || []) {
      const style = getComputedStyle(overlay), rect = overlay.getBoundingClientRect();
      if (style.position === 'fixed' || (style.position === 'sticky' && Math.abs(rect.top - mainTop - (parseFloat(style.top) || 0)) <= 1)) upper = Math.max(upper, rect.bottom);
    }
    const delta = before.top >= upper && before.bottom <= lower ? after.top - before.top : after.top < upper ? after.top - upper : after.bottom > lower ? after.bottom - lower : 0;
    if (scroller) scroller.scrollTop += delta; else if (typeof window !== 'undefined') window.scrollBy(0, delta);
  }
}
function interviewApplyPreset(key, i, preset) {
  if (key === 'meds') { interviewSetUsage(i, preset[1]); interviewRecord.details.meds[i].as_instructed = false; }
  else interviewRecord.other_meds[i][1] = preset[1];
  interviewChanged(key); renderInterview();
  document.querySelector(`[data-usage-preset="${key}"][data-row="${i}"]`)?.focus({ preventScroll: true });
}
function interviewOutstanding() {
  const { checked, total, withoutStatus, clarify, consentMissing, healthUnanswered } = H.interviewOutstanding(interviewRecord);
  const items = [
    [total > checked, `${checked}/${total} checked`, 'meds', `${checked} of ${total} medicines checked`],
    [withoutStatus, `${withoutStatus} no status`, 'meds', `${withoutStatus} medicines without a status`],
    [clarify, `${clarify} to clarify`, 'clarify', `${clarify} to clarify`],
    [healthUnanswered, `${healthUnanswered} health check`, 'health_check', `${healthUnanswered} health-check questions unanswered`],
    [consentMissing, 'Consent', 'consent', 'Consent not signed'],
  ].filter(([show]) => show);
  return `<strong>Still to do:</strong> ${items.length ? items.map(([, label, section, title]) => `<button type="button" data-interview-jump="${section}" title="${esc(title)}" aria-label="${esc(title)}">${esc(label)}</button>`).join('') : '<span>Nothing outstanding</span>'}`;
}
function renderInterview() {
  const active = document.activeElement, focusedDetail = active?.closest?.('.interview-medicine-detail');
  const focus = focusedDetail && active.dataset.field && active.dataset.row !== undefined ? { key: active.dataset.field, row: active.dataset.row, col: active.dataset.col, start: active.selectionStart, end: active.selectionEnd } : null;
  const record = normalizeInterviewDetails(interviewRecord);
  const header = H.interviewHeader(record.header);
  const section = ([key, title]) => {
    const value = record[key];
    const sources = record.sources || [];
    const fromReferral = sources.some((item) => item.toLowerCase().startsWith(`${key} from referral`));
    const fromSpec = sources.some((item) => item.toLowerCase().startsWith('from previous interview spec'));
    const hasContent = Array.isArray(value)
      ? value.some((row) => (Array.isArray(row) ? row.some(Boolean) : !!row))
      : typeof value === 'string' && value.trim();
    const source =
      !interviewEdited.has(key) && hasContent && (fromReferral || fromSpec)
        ? `<small data-source="${key}">${fromReferral ? 'from referral - check' : 'from previous interview spec - check'}</small>`
        : '';
    let input;
    if (key === 'not_using_meds') {
      input = interviewMedicineTable(record.meds, true);
    } else if (interviewTables[key]) {
      const columns = interviewTables[key];
      input = key === 'meds' ? interviewMedicineTable(value) : key === 'other_meds' ? interviewOtherMedicineTable(value) : H.tableInput(key, title, columns, value, 'interview');
      if (key === 'obs') input += ['height', 'weight', 'bmi'].map(name => `<div class="interview-measure"><strong>${esc(name.toUpperCase())}</strong> Referral: ${esc(record.details[name + '_referral'] || 'Not separately listed')} <label><input type="checkbox" data-detail="${name}_as_listed" ${record.details[name + '_as_listed'] ? 'checked' : ''} ${record.details[name + '_referral'] ? '' : 'disabled'}> As listed</label> ${interviewDetailText(name + '_actual', 'At interview')}</div>`).join('') + interviewDetailText('home_bp', 'Home BP readings') + interviewDetailText('home_bgl', 'Home blood glucose readings');
    } else if (key === 'health_check') {
      input = `<button type="button" data-health-no>Mark all remaining as No</button><div class="interview-health">${interviewEntryChoices.filter(entry => entry.key.startsWith('sx_')).map(interviewEntry).join('')}</div>` + [['mobility','Mobility (aids, falls, driving)'],['exercise','Exercise']].map(([field, label]) => `<label id="section-${field}">${label}<textarea id="interview-${field}" data-field="${field}">${esc(record[field] || '')}</textarea></label>`).join('');
    } else if (key === 'consent') {
      const relationships = [
        'Parent or guardian of child',
        'Enduring guardian',
        'Enduring power of attorney',
        'Nominated in writing by the patient',
        'Recognised by a state or territory law',
      ];
      input = `<fieldset class="consent-who" ${record.consent_file ? 'disabled' : ''}><legend>Who signs</legend>${[
        ['patient', 'Patient'],
        ['authorised', 'Authorised person'],
      ]
        .map(
          ([id, label]) =>
            `<label><input type="radio" name="consent-by" data-field="consent" data-prop="by" value="${id}" ${(value?.by || 'patient') === id ? 'checked' : ''}> ${label}</label>`,
        )
        .join('')}</fieldset>
        <fieldset ${record.consent_file ? 'disabled' : ''}><div id="authorised-details" ${value?.by === 'authorised' ? '' : 'hidden'}><fieldset><legend>Relationship</legend>${relationships.map((label, i) => `<label><input type="radio" name="consent-relationship" data-field="consent" data-prop="relationship" value="${i + 1}" ${Number(value?.relationship) === i + 1 ? 'checked' : ''} ${value?.by === 'authorised' ? 'required' : ''}> ${esc(label)}</label>`).join('')}</fieldset><label>Authorised person's name<input data-field="consent" data-prop="authorised_name" value="${esc(value?.authorised_name || '')}" ${value?.by === 'authorised' ? 'required' : ''}></label></div>
        <p>The app fills in the pharmacist, date of service, patient name and consent date, and for an authorised person their name and relationship. Only the signature is left.</p><label class="consent-check"><input type="checkbox" data-field="consent" data-prop="signed" ${value?.signed || record.consent_signed_draft ? 'checked' : ''}> Consent form signed</label><label>Date<input type="date" data-field="consent" data-prop="date" value="${esc(value?.date || '')}"></label></fieldset>${record.consent_file ? `<p>Signed: ${esc(record.consent_file)} <button type="button" data-consent-view>View signed consent</button></p>` : '<button type="button" data-consent-sign>Sign consent form</button>'}`;
    } else {
      const text = Array.isArray(value) ? value.join('\n') : value || '';
      input = (key === 'manages_meds' ? interviewChoices('manager', 'Who manages medicines?', [['self','Self'],['other','Someone else'],['unknown','Unknown']]) + `<div data-detail-visible="manager" ${record.details.manager === 'other' ? '' : 'hidden'}>${interviewDetailText('manager_details', 'Name and relationship')}</div>` + interviewChoices('daa', 'Dose administration aid', [['yes','Yes'],['no','No'],['unknown','Unknown']]) + `<div data-detail-visible="daa" ${record.details.daa === 'yes' ? '' : 'hidden'}>${interviewChoices('daa_type', 'Pack type', [['sachets','Sachets'],['webster','Webster pack'],['other','Other']])}${interviewDetailText('daa_pharmacy', 'Pharmacy / other details')}</div>` : key === 'alcohol_smoking' ? interviewChoices('smoking', 'Smoking', [['never','Never'],['current','Current'],['ex','Ex'],['unknown','Unknown']]) + interviewChoices('alcohol', 'Alcohol', [['yes','Yes'],['no','No'],['unknown','Unknown']]) + `<div data-detail-visible="alcohol" ${record.details.alcohol === 'yes' ? '' : 'hidden'}>${interviewDetailText('alcohol_details', 'Alcohol details')}</div>` : '') + `<label><span ${['manages_meds', 'alcohol_smoking'].includes(key) ? '' : 'class="sr-only"'}>${esc(key === 'manages_meds' ? 'Other notes about managing medicines' : key === 'alcohol_smoking' ? 'Other notes about alcohol / smoking' : title)}</span><textarea ${['manages_meds', 'alcohol_smoking'].includes(key) ? 'rows="3"' : ''} id="interview-${key}" data-field="${key}" ${key === 'notes' ? 'class="interview-notes"' : ''}>${esc(text)}</textarea></label>${key === 'clarify' ? '<small>One item per line</small>' : ''}`;
    }
    const entries = keys => interviewEntryChoices.filter(entry => keys.includes(entry.key)).map(interviewEntry).join('');
    if (key === 'social') input = entries(['present', 'lives']) + input.replace('class="sr-only"', '').replace('Visit and living</span>', 'Social status</span>');
    if (key === 'manages_meds') input = input.replace('<label><span >Other notes', entries(['missed_doses', 'device_technique', 'swallowing']) + '<label><span >Other notes');
    if (key === 'conditions') input += entries(['recent_change']);
    if (key === 'alcohol_smoking') input = input.replace(interviewChoices('alcohol', 'Alcohol', [['yes','Yes'],['no','No'],['unknown','Unknown']]), `<div data-entry-detail="smoking" ${['current','ex'].includes(record.details.smoking) || record.details.smoking_details ? '' : 'hidden'}>${interviewDetailText('smoking_details', 'Smoking details (amount, quit date, vaping)')}</div>` + interviewChoices('alcohol', 'Alcohol', [['yes','Yes'],['no','No'],['unknown','Unknown']]));
    return `<section id="section-${key}" class="interview-section"><h2 tabindex="-1">${esc(title)} ${source}</h2>${input}</section>`;
  };
  const sections = interviewSections.map(section);
  const reconciliationRows = interviewReconciliation?.flags || [];
  const reconciliationView = `<section id="section-reconciliation" class="interview-section">
    <h2>Medicine reconciliation</h2>
    <p>Compare prescribed and actual medicine use. Flags require pharmacist judgement; they are not treatment recommendations.</p>
    ${interviewReconciliation
      ? `<p role="status">${esc(interviewReconciliation.reviewed ? 'Reviewed and acknowledged for the saved medicines' : interviewReconciliation.stale ? 'Review is stale: medicines changed' : reconciliationRows.length + ' discrepancies require review')}</p>
         <ul>${reconciliationRows.map(f => `<li><strong>${esc(f.medicine_id)}</strong>: ${esc(f.message)} <button type="button" data-interview-jump="meds">Go to medicines</button></li>`).join('')}</ul>`
      : '<p>Save changes, then load the current reconciliation checklist.</p>'}
    <div class="actions"><button type="button" data-reconciliation-load>Save and refresh checklist</button>
    ${interviewReconciliation && !interviewReconciliation.reviewed && !interviewReconciliation.stale
      ? '<button type="button" data-reconciliation-ack>Acknowledge reviewed discrepancies</button>' : ''}</div>
    </section>`;

  const pathologyCols = [['test','Test'],['value','Result'],['unit','Unit'],['reference_interval','Range'],
    ['sample_date','Sample date'],['source','Source document/page'],['comment','Notes']];
  const pathologyView = `<section class="interview-section" id="section-pathology-verified">
    <h2>Pathology provenance and verification</h2><p>Units, sample dates and source are entered explicitly. A result cannot be marked verified without all required details.</p>
    <div class="actions"><button type="button" data-pathology-import>Import a local pathology PDF (unconfirmed)</button><button type="button" data-pathology-reload-sources>Reload sources</button></div>
    ${(pathologySourceIndex?.sources || []).map(source => `<details class="card"><summary>${esc(source.name)} — ${source.page_count} page(s), unconfirmed</summary>
      <button type="button" data-pathology-open-source="${esc(source.id)}">Open original PDF</button>
      ${source.pages.map(page => `<section><h4>Page ${page.page} — ${esc(page.method)}</h4>
      <pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(page.unconfirmed_excerpt || 'No machine-readable text; review original image')}</pre>
      <button type="button" data-pathology-use-source="${esc(source.id)}" data-source-page="${page.page}">Add blank unverified result linked to this page</button></section>`).join('')}
      </details>`).join('')}
    ${interviewPathologyError ? `<p class="error" role="alert">${esc(interviewPathologyError)}</p>` : ''}
    ${interviewPathology ? `<div class="table-scroll"><table><thead><tr>${pathologyCols.map(([,label])=>`<th>${esc(label)}</th>`).join('')}<th>Verified</th><th>Remove</th></tr></thead><tbody>${interviewPathology.records.map((r,i)=>`<tr>${pathologyCols.map(([key,label])=>`<td><input aria-label="${esc(label)} row ${i+1}" type="${key==='sample_date'?'date':'text'}" data-pathology-entry="${i}" data-pathology-field="${key}" value="${esc(r[key])}"></td>`).join('')}<td><input aria-label="Verify row ${i+1}" type="checkbox" data-pathology-entry="${i}" data-pathology-field="verified" ${r.verified?'checked':''}></td><td><button type="button" data-pathology-remove="${i}">Remove</button></td></tr>`).join('')}</tbody></table></div>
    <div class="actions"><button type="button" data-pathology-add>Add pathology result</button><button type="button" data-pathology-save>Save pathology</button><span>${interviewPathologyDirty?'Unsaved changes':'Saved'}</span></div>` : '<p>Pathology records unavailable until engine reconnects.</p>'}
    </section>`;
  const formSections = sections.join('') + pathologyView + reconciliationView;
  $('screen').innerHTML =
    interviewPicker() + `<div class="interview-context"><span class="interview-context-patient" title="${esc(header[0])}">${esc(header[0])}</span><span id="interview-status" role="status">${esc(interviewSaveStatus)}</span><button type="button" data-interview-save>Save</button><div id="interview-outstanding">${interviewOutstanding()}</div></div>${record.details.reason?.trim() ? `<p>Reason for referral: ${esc(record.details.reason)}</p>` : ''}${header[1] ? `<p class="interview-header">${esc(header[1])}</p>` : ''}<div class="interview-layout"><div>${formSections}<div class="actions interview-actions"><button type="button" class="primary" data-interview-record-visit>Record visit</button><button type="button" data-interview-save>Save</button><details class="more-actions"><summary>More actions</summary><div class="actions"><button data-interview-export="docx">Export Word</button><button data-interview-export="pdf">Export PDF</button><button data-interview-export="both">Interview pack</button>${interviewAi ? `<button data-interview-assist title="${esc(interviewAgent)}">Suggest points (AI)</button>` : ''}<button data-interview-folder>Open folder</button></div></details></div><pre id="interview-output" role="status">${esc(interviewOutput)}</pre></div><nav class="interview-index" aria-label="Interview sections"><a href="#section-notes">Back to notes</a>${interviewSections
      .slice(1)
      .map(([key, title]) => `<a href="#section-${key}">${esc(({meds: 'Referral medicines', other_meds: 'Found medicines', not_using_meds: 'Not using', allergies: 'Allergies', manages_meds: 'Managing medicines'})[key] || title)}</a>`)
      .join('')}</nav></div>`;
  document.querySelectorAll('.interview-section textarea').forEach(growInterview);
  if (focus) { const el = document.querySelector(`[data-field="${focus.key}"][data-row="${focus.row}"][data-col="${focus.col}"]`); if (el) { el.focus(); el.setSelectionRange(focus.start, focus.end); } }
}
async function openConsentDialog() {
  const patientId = interviewId;
  const dialog = document.createElement('dialog');
  dialog.className = 'consent-dialog';
  dialog.setAttribute('aria-labelledby', 'consent-dialog-title');
  dialog.innerHTML = `<h2 id="consent-dialog-title">${interviewRecord.consent.by === 'authorised' ? 'Authorised person signs' : 'Patient signs'}</h2>
    <div class="consent-preview"><p>Loading form...</p><img alt="PPA consent form page 2" hidden></div>
    <label for="consent-signature">Signature</label><div class="consent-canvas-wrap"><div class="consent-canvas-area"><canvas id="consent-signature" aria-label="Signature drawing area"></canvas><span class="consent-pen" hidden></span></div></div><p class="consent-hint" hidden>Move your finger on the touchpad to sign. Pause to lift the pen. Press Esc when finished.</p>
    <p class="error" role="alert"></p><div class="actions"><button type="button" data-clear>Clear</button><button type="button" data-touchpad>Touchpad signing (no click needed)</button><button type="button" class="primary" data-save disabled>Save signature</button><button type="button" data-cancel>Cancel</button></div>`;
  document.body.appendChild(dialog);
  dialog.showModal();
  const canvas = dialog.querySelector('canvas'), ctx = canvas.getContext('2d');
  const save = dialog.querySelector('[data-save]'), cancel = dialog.querySelector('[data-cancel]');
  const clear = dialog.querySelector('[data-clear]'), error = dialog.querySelector('.error');
  const touchpad = dialog.querySelector('[data-touchpad]'), marker = dialog.querySelector('.consent-pen'), hint = dialog.querySelector('.consent-hint');
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
  ctx.scale(ratio, ratio); ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  let drawing = false, ready = false, saving = false;
  let x = 0, y = rect.height / 2, stroke = false, penDown = true, timer;
  const locked = () => document.pointerLockElement === canvas;
  const lockChange = () => {
    marker.hidden = hint.hidden = !locked();
    if (!locked()) { clearTimeout(timer); stroke = false; }
  };
  const lockError = () => { error.textContent = 'Touchpad mode is not available here'; };
  const lockMove = (event) => {
    if (!locked() || !ready || saving || (!event.movementX && !event.movementY)) return;
    const nextX = Math.max(0, Math.min(rect.width, x + event.movementX * 1.5));
    const nextY = Math.max(0, Math.min(rect.height, y + event.movementY * 1.5));
    if (penDown && (nextX !== x || nextY !== y)) {
      if (!stroke) { ctx.beginPath(); ctx.moveTo(x, y); stroke = true; }
      ctx.lineTo(nextX, nextY); ctx.stroke(); save.disabled = false;
    }
    x = nextX; y = nextY; marker.style.left = `${x}px`; marker.style.top = `${y}px`;
    clearTimeout(timer); timer = setTimeout(() => { stroke = false; }, 700);
  };
  const lockKey = (event) => {
    if (!locked()) return;
    if (event.key === 'Escape') { event.preventDefault(); document.exitPointerLock(); }
    if (event.key === ' ' && !event.repeat) { event.preventDefault(); penDown = !penDown; stroke = false; }
  };
  const lockClick = () => { if (locked()) document.exitPointerLock(); };
  document.addEventListener('pointerlockchange', lockChange);
  document.addEventListener('pointerlockerror', lockError);
  document.addEventListener('mousemove', lockMove);
  document.addEventListener('keydown', lockKey);
  document.addEventListener('click', lockClick);
  dialog.addEventListener('close', () => {
    if (locked()) document.exitPointerLock();
    clearTimeout(timer);
    document.removeEventListener('pointerlockchange', lockChange);
    document.removeEventListener('pointerlockerror', lockError);
    document.removeEventListener('mousemove', lockMove);
    document.removeEventListener('keydown', lockKey);
    document.removeEventListener('click', lockClick);
    dialog.remove();
  });
  touchpad.onclick = async (event) => {
    event.stopPropagation();
    if (!ready || saving) return;
    error.textContent = '';
    if (!canvas.requestPointerLock) { lockError(); return; }
    x = 0; y = rect.height / 2; stroke = false; penDown = true;
    marker.style.left = `${x}px`; marker.style.top = `${y}px`;
    try { await canvas.requestPointerLock(); } catch { lockError(); }
  };
  const point = (event) => { const r = canvas.getBoundingClientRect(); return [(event.clientX - r.left) * rect.width / r.width, (event.clientY - r.top) * rect.height / r.height]; };
  canvas.addEventListener('pointerdown', (event) => {
    if (!ready || saving || drawing || locked()) return;
    drawing = true; canvas.setPointerCapture(event.pointerId);
    const [x, y] = point(event); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 0.01, y); ctx.stroke(); save.disabled = false;
  });
  canvas.addEventListener('pointermove', (event) => { if (drawing && canvas.hasPointerCapture(event.pointerId)) { ctx.lineTo(...point(event)); ctx.stroke(); } });
  canvas.addEventListener('pointerup', () => { drawing = false; });
  canvas.addEventListener('pointercancel', () => { drawing = false; });
  clear.onclick = () => { ctx.clearRect(0, 0, rect.width, rect.height); save.disabled = true; };
  cancel.onclick = () => dialog.close();
  dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
  let previewRevision;
  save.onclick = async () => {
    saving = true; save.disabled = true; clear.disabled = true; cancel.disabled = true; error.textContent = '';
    try {
      const result = await hmr.api('POST', `/api/patients/${encodeURIComponent(patientId)}/consent/sign`, { png: canvas.toDataURL('image/png').split(',')[1], revision: previewRevision });
      if (result.error) throw new Error(result.error);
      // Keep the signed state visible even if refreshing the record fails.
      interviewRecord.consent_file = result.file;
      interviewRecord.consent.signed = true;
      try {
        interviewRecord = normalizeInterviewDetails(await hmr.api('GET', `/api/patients/${encodeURIComponent(patientId)}/interview`));
        const recovery = interviewSaver.reset(interviewRecord);
        normalizeInterviewDetails(interviewRecord);
        interviewConflict = recovery.conflict;
      } catch (e) { interviewSaveStatus = `Signed; could not refresh - ${errorText(e)}`; }
      dialog.close(); renderInterview();
    } catch (e) { error.textContent = errorText(e); save.disabled = false; }
    finally { saving = false; clear.disabled = false; cancel.disabled = false; }
  };
  try {
    if (!(await saveInterview(true))) throw new Error(interviewSaveStatus);
    const preview = await hmr.api('GET', `/api/patients/${encodeURIComponent(patientId)}/consent/preview`);
    if (preview.error) throw new Error(preview.error);
    previewRevision = preview.revision;
    if (!dialog.open) return;
    dialog.querySelector('h2').textContent = preview.by === 'authorised' ? 'Authorised person signs' : 'Patient signs';
    const img = dialog.querySelector('img'); img.src = `data:image/png;base64,${preview.png}`; img.hidden = false;
    dialog.querySelector('.consent-preview p').remove(); ready = true;
  } catch (e) { if (dialog.open) error.textContent = errorText(e); }
}
async function viewSignedConsent() {
  const patientId = interviewId, file = interviewRecord.consent_file;
  const dialog = document.createElement('dialog');
  dialog.className = 'consent-dialog';
  dialog.setAttribute('aria-label', 'Signed consent');
  dialog.innerHTML = `<h2>Signed consent</h2><div class="consent-preview"><p>Loading form...</p><img alt="Signed PPA consent form" hidden></div><p class="error" role="alert"></p><div class="actions"><button type="button" data-open>Open PDF</button><button type="button" data-close>Close</button></div>`;
  document.body.appendChild(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.querySelector('[data-open]').onclick = async () => {
    try { await hmr.openPatientFolder(Number(patientId), file); }
    catch (e) { dialog.querySelector('.error').textContent = errorText(e); }
  };
  dialog.showModal();
  try {
    const preview = await hmr.api('GET', `/api/patients/${encodeURIComponent(patientId)}/consent/preview`);
    if (preview.error) throw new Error(preview.error);
    if (!dialog.open) return;
    const img = dialog.querySelector('img'); img.src = `data:image/png;base64,${preview.png}`; img.hidden = false;
    dialog.querySelector('.consent-preview p').remove();
  } catch (e) { if (dialog.open) dialog.querySelector('.error').textContent = errorText(e); }
}
document.addEventListener('input', (event) => {
  if (page !== 'interview') return;
  const el = event.target;
  if (el.id === 'interview-search') {
    const q = el.value.toLowerCase();
    for (const option of $('interview-patient').options) option.hidden = !option.textContent.toLowerCase().includes(q);
    return;
  }
  if (el.dataset.detail) {
    const prop = el.dataset.detail;
    interviewRecord.details[prop] = el.type === 'checkbox' ? el.checked : el.value;
    if (prop.endsWith('_as_listed') && el.checked) interviewRecord.details[prop.replace('_as_listed', '_actual')] = interviewRecord.details[prop.replace('_as_listed', '_referral')];
    if (prop.endsWith('_actual')) { interviewRecord.details[prop.replace('_actual', '_as_listed')] = false; const box = document.querySelector(`[data-detail="${prop.replace('_actual', '_as_listed')}"]`); if (box) box.checked = false; }
    const visible = document.querySelector(`[data-detail-visible="${prop}"]`);
    if (visible) visible.hidden = el.value !== (prop === 'manager' ? 'other' : 'yes');
    const entry = interviewEntryChoices.find(item => item.key === prop);
    const detail = document.querySelector(`[data-entry-detail="${prop}"]`);
    if (detail) detail.hidden = !(entry?.detailWhen?.includes(el.value) || (prop === 'smoking' && ['current','ex'].includes(el.value)) || interviewRecord.details[prop + '_details']);
    if (prop.endsWith('_details')) { const choice = prop.slice(0, -8), config = interviewEntryChoices.find(item => item.key === choice), container = document.querySelector(`[data-entry-detail="${choice}"]`); if (container) container.hidden = !(el.value || config?.detailWhen?.includes(interviewRecord.details[choice]) || (choice === 'smoking' && ['current','ex'].includes(interviewRecord.details.smoking))); }
    interviewChanged('details');
    if (prop === 'daa' || prop.endsWith('_as_listed')) renderInterview();
    return;
  }
  if (el.dataset.useField) { const key = el.dataset.useTable, i = Number(el.dataset.row), prop = el.dataset.useField; const change = () => { interviewRecord.details[key][i][prop] = el.value; interviewChanged(key); }; if (prop === 'use_status' && el.value === 'not_using') interviewMoveFocus(el, key, change); else { change(); if (prop === 'use_status') { renderInterview(); document.querySelector(`[data-use-field="use_status"][data-use-table="${key}"][data-row="${i}"][value="${el.value}"]`)?.focus(); } } return; }
  if (el.dataset.otherChecked !== undefined) { const i = Number(el.dataset.row); interviewMoveFocus(el, 'other_meds', () => { interviewRecord.details.other_meds[i].checked = el.checked; interviewChanged('other_meds'); }); return; }
  if (el.dataset.interviewProgressFilter !== undefined) { interviewProgressFilter = el.value; renderInterview(); return; }
  if (el.dataset.usagePreset !== undefined) {
    const i = Number(el.dataset.row), preset = interviewUsagePresets.find(([code]) => code === el.value);
    if (preset) interviewApplyPreset(el.dataset.usagePreset || 'meds', i, preset);
    return;
  }
  if (el.dataset.medDetail) {
    const i = Number(el.dataset.row), prop = el.dataset.medDetail;
    if (prop === 'checked') { interviewMoveFocus(el, 'meds', () => { interviewSetMedicineDetail(i, prop, el.checked); interviewChanged('meds'); }); return; }
    interviewSetMedicineDetail(i, prop, el.type === 'checkbox' ? el.checked : el.value);
    if (prop === 'packed') { const badge = el.closest?.('tr')?.querySelector('[data-badge-kind=packed]'); if (badge) { badge.hidden = !el.value; badge.textContent = `DAA: ${el.value}`; } }
    interviewChanged('meds');
    return;
  }
  const key = el.dataset.field;
  if (!key || !interviewRecord) return;
  if (el.tagName === 'TEXTAREA') growInterview(el);
  if (el.dataset.row !== undefined) interviewRecord[key][Number(el.dataset.row)][Number(el.dataset.col)] = el.value;
  else if (el.dataset.prop)
    interviewRecord[key][el.dataset.prop] =
      el.type === 'checkbox' ? el.checked : el.dataset.prop === 'relationship' ? Number(el.value) : el.value;
  else interviewRecord[key] = key === 'clarify' ? el.value.split('\n') : el.value;
  if ((key === 'meds' || key === 'other_meds') && el.dataset.col === '0' && typeof medicineNameEdited === 'function') medicineNameEdited(key, Number(el.dataset.row), el);
  if (key === 'consent') {
    const consent = interviewRecord.consent;
    const incomplete = consent.by === 'authorised' && (!consent.relationship || !consent.authorised_name.trim());
    if (consent.signed && incomplete) {
      consent.signed = false; interviewRecord.consent_signed_draft = true;
    } else if (el.dataset.prop === 'signed' && !el.checked) interviewRecord.consent_signed_draft = false;
    else if (interviewRecord.consent_signed_draft && !incomplete) {
      consent.signed = true; interviewRecord.consent_signed_draft = false;
    }
  }
  if ((key === 'meds' && el.dataset.col === '2') || (key === 'other_meds' && el.dataset.col === '1')) interviewUpdatePreset(el);
  if (key === 'meds' && el.dataset.col === '2') { interviewRecord.details.meds[Number(el.dataset.row)].as_instructed = false; const button = document.querySelector(`[data-interview-as-instructed="${el.dataset.row}"]`); if (button) { button.textContent = 'As instructed'; button.className = ''; } const prn = document.querySelector(`[data-prn-row="${el.dataset.row}"]`); if (prn) prn.hidden = !(interviewPrnVisible(el.value) || interviewRecord.details.meds[Number(el.dataset.row)].prn_use); }
  if (key === 'meds' && el.dataset.col === '1') { const button = document.querySelector(`[data-interview-as-instructed="${el.dataset.row}"]`); if (button) { button.disabled = !el.value.trim(); button.title = button.disabled ? 'No referral directions to copy' : ''; } }
  if (key === 'meds' && el.dataset.col === '1' && interviewRecord.details.meds[Number(el.dataset.row)].as_instructed) { interviewRecord.meds[Number(el.dataset.row)][2] = el.value; const actual = document.querySelector(`[data-field="meds"][data-row="${el.dataset.row}"][data-col="2"]`); if (actual) { actual.value = el.value; interviewUpdatePreset(actual); } const prn = document.querySelector(`[data-prn-row="${el.dataset.row}"]`); if (prn) prn.hidden = !(interviewPrnVisible(el.value) || interviewRecord.details.meds[Number(el.dataset.row)].prn_use); }
  if ((key === 'meds' || key === 'other_meds') && el.dataset.row !== undefined) {
    const kind = el.dataset.col === (key === 'meds' ? '4' : '3') ? 'note' : el.dataset.col === (key === 'meds' ? '3' : '2') ? (key === 'meds' ? 'check' : 'why') : '';
    const badge = kind && el.closest?.('tr')?.querySelector(`[data-badge-kind="${kind}"]`); if (badge) badge.hidden = !el.value.trim();
  }
  interviewChanged(key);
  if (key === 'consent' && el.dataset.prop === 'by') {
    const details = $('authorised-details');
    details.hidden = el.value !== 'authorised';
    details.querySelectorAll('input').forEach((input) => {
      input.required = !details.hidden;
    });
  }
});
document.addEventListener('focusout', (event) => {
  const el = event.target;
  if (page !== 'interview') return;
  const other = (el.dataset.field === 'other_meds' && el.dataset.col === '3') || el.dataset.usagePreset === 'other_meds';
  if (!(other || (el.dataset.field === 'meds' && el.dataset.col === '4') || el.dataset.usagePreset !== undefined || el.dataset.medDetail === 'as_instructed')) return;
  const key = other ? 'other_meds' : 'meds', notesCol = other ? 3 : 4;
  const row = el.closest('tr'), tbody = row?.parentElement;
  if (!tbody || row.contains(event.relatedTarget)) return;
  const i = Number(el.dataset.row);
  if (!interviewRecord[key][i][notesCol].trim() || interviewRecord.details[key][i].checked) return;
  const firstPlain = [...tbody.children].find(tr => {
    const index = Number(tr.querySelector(`[data-field="${key}"]`).dataset.row);
    const meta = interviewRecord.details[key][index];
    return meta.checked || (meta.priority <= interviewRecord.details[key][i].priority && !interviewRecord[key][index][notesCol].trim());
  });
  if (firstPlain && row !== firstPlain) tbody.insertBefore(row, firstPlain);
});

async function savePathologyRecords() {
  if (!interviewPathology || !interviewPathologyDirty) return true;
  try {
    interviewPathology = await hmr.api('POST', `/api/patients/${encodeURIComponent(interviewId)}/pathology-records`,
      {revision: interviewPathology.revision, records: interviewPathology.records});
    interviewPathologyDirty = false; interviewPathologyError = '';
    return true;
  } catch (e) { interviewPathologyError = errorText(e); return false; }
}

document.addEventListener('input', event => {
  const input = event.target.closest?.('[data-pathology-entry]');
  if (!input || page !== 'interview' || !interviewPathology) return;
  const row = interviewPathology.records[Number(input.dataset.pathologyEntry)];
  if (!row || !Object.hasOwn(row, input.dataset.pathologyField)) return;
  row[input.dataset.pathologyField] = input.dataset.pathologyField === 'verified' ? input.checked : input.value;
  interviewPathologyDirty = true;
});

async function interviewClick(b) {
  if (b.dataset.pathologyImport !== undefined) {
    try {
      const result = await hmr.pickPathologySource(Number(interviewId));
      if (!result.cancelled) {
        pathologySourceIndex = await hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/pathology/sources`);
        interviewPathologyError = '';
      }
    } catch (error) { interviewPathologyError = errorText(error); }
    renderInterview(); return true;
  }
  if (b.dataset.pathologyReloadSources !== undefined) {
    try { pathologySourceIndex = await hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/pathology/sources`); }
    catch (error) { interviewPathologyError = errorText(error); }
    renderInterview(); return true;
  }
  if (b.dataset.pathologyOpenSource !== undefined) {
    try { await hmr.openPathologySource(Number(interviewId), b.dataset.pathologyOpenSource); }
    catch (error) { interviewPathologyError = errorText(error); renderInterview(); }
    return true;
  }
  if (b.dataset.pathologyUseSource !== undefined && interviewPathology) {
    const source = pathologySourceIndex.sources.find(item => item.id === b.dataset.pathologyUseSource);
    const page = Number(b.dataset.sourcePage);
    if (!source || !Number.isInteger(page) || page < 1 || page > source.page_count) return true;
    interviewPathology.records.push({id:crypto.randomUUID().replace(/-/g,''),test:'',value:'',
      unit:'',reference_interval:'',sample_date:'',source:source.name + ' page ' + page +
      ' sha256:' + source.sha256,verified:false,comment:'UNVERIFIED — compare source PDF before confirming'});
    interviewPathologyDirty = true;
    renderInterview(); return true;
  }
  if (b.dataset.pathologyAdd !== undefined && interviewPathology) {
    interviewPathology.records.push({id: crypto.randomUUID().replace(/-/g,''),test:'',value:'',unit:'',
      reference_interval:'',sample_date:'',source:'',verified:false,comment:''});
    interviewPathologyDirty = true; renderInterview(); return true;
  }
  if (b.dataset.pathologyRemove !== undefined && interviewPathology) {
    interviewPathology.records.splice(Number(b.dataset.pathologyRemove),1);
    interviewPathologyDirty = true; renderInterview(); return true;
  }
  if (b.dataset.pathologySave !== undefined) {
    await savePathologyRecords(); renderInterview(); return true;
  }
  if (page !== 'interview' || !interviewRecord) return false;
  if (b.dataset.reconciliationLoad !== undefined) {
    if (!(await saveInterview(true))) return true;
    try { interviewReconciliation = await hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/reconciliation`); }
    catch (error) { interviewOutput = errorText(error); }
    renderInterview();
    document.getElementById('section-reconciliation')?.scrollIntoView();
    return true;
  }
  if (b.dataset.reconciliationAck !== undefined) {
    if (!interviewReconciliation || !(await saveInterview(true))) return true;
    try {
      const reviewer = interviewRecord.header.pharmacist;
      const result = await hmr.api('POST', `/api/patients/${encodeURIComponent(interviewId)}/reconciliation`,
        { source_hash: interviewReconciliation.source_hash, reviewed_by: reviewer });
      interviewReconciliation = { ...interviewReconciliation, ...result };
      interviewOutput = 'Medicine reconciliation acknowledgement saved';
    } catch (error) {
      interviewReconciliation = null;
      interviewOutput = errorText(error);
    }
    renderInterview();
    document.getElementById('section-reconciliation')?.scrollIntoView();
    return true;
  }
  if (b.dataset.healthNo !== undefined) { interviewMarkRemainingNo(interviewRecord.details); interviewChanged('details'); renderInterview(); document.querySelector('[data-health-no]')?.focus(); return true; }
  if (b.dataset.interviewDetails || b.dataset.interviewBadge) {
    const key = b.dataset.interviewDetails || b.dataset.interviewBadge, meta = interviewRecord.details[key][Number(b.dataset.row)];
    if (b.dataset.interviewBadge || !interviewExpanded.has(meta)) interviewExpanded.add(meta); else interviewExpanded.delete(meta);
    renderInterview(); document.querySelector(`[data-interview-details="${key}"][data-row="${b.dataset.row}"]`)?.focus(); return true;
  }
  if (b.dataset.interviewAsInstructed !== undefined) {
    const i = Number(b.dataset.interviewAsInstructed), meta = interviewRecord.details.meds[i];
    if (!interviewRecord.meds[i][1]?.trim()) return true;
    if (meta.use_status === 'taking' && meta.as_instructed && meta.checked && interviewRecord.meds[i][2] === interviewRecord.meds[i][1]) return true;
    interviewMoveFocus(b, 'meds', () => { meta.use_status = 'taking'; interviewSetMedicineDetail(i, 'as_instructed', true); interviewSetMedicineDetail(i, 'checked', true); interviewChanged('meds'); }); return true;
  }
  if (b.dataset.interviewJump) { document.getElementById(`section-${b.dataset.interviewJump}`)?.scrollIntoView(); return true; }
  if (b.dataset.interviewRecordVisit !== undefined) { const id = interviewId; if (!(await saveInterview(true)) || page !== 'interview' || interviewId !== id) return true; await navigate('patients', { selected: String(id), detailTab: 'Overview', scroll: 0 }); if (page === 'patients') await showPatient(id, 'visited'); return true; }
  if (b.dataset.interviewSave !== undefined) { await saveInterview(true); return true; }
  if (b.dataset.interviewResolve) { interviewSaver.resolveConflict(b.dataset.interviewResolve); interviewConflict = interviewSaver.hasConflict(); renderInterview(); return true; }
  if (b.dataset.interviewTop !== undefined || b.dataset.interviewTopOther !== undefined) {
    const other = b.dataset.interviewTopOther !== undefined, i = Number(other ? b.dataset.interviewTopOther : b.dataset.interviewTop), list = interviewRecord.details[other ? 'other_meds' : 'meds'];
    const max = Math.max(0, ...list.map(m => m.priority));
    if (max >= 1000000) list.forEach(m => { m.priority = 0; });
    list[i].priority = max >= 1000000 ? 1 : max + 1;
    interviewChanged(other ? 'other_meds' : 'meds'); renderInterview();
    document.querySelector(`[${other ? 'data-interview-top-other' : 'data-interview-top'}="${i}"]`)?.focus();
    return true;
  }
  if (b.dataset.consentSign !== undefined) { await openConsentDialog(); return true; }
  if (b.dataset.consentView !== undefined) { await viewSignedConsent(); return true; }
  if (b.dataset.interviewAdd || b.dataset.interviewRemove) {
    const key = b.dataset.interviewAdd || b.dataset.interviewRemove;
    interviewRecord[key] = b.dataset.interviewAdd
      ? H.addRow(interviewRecord[key] || [], interviewTables[key].length)
      : H.removeRow(interviewRecord[key], Number(b.dataset.row));
    if (key === 'meds') {
      if (b.dataset.interviewAdd) interviewRecord.details.meds.push({ item_id: H.medicineItemId(), packed: '', as_instructed: false, checked: false, priority: 0, use_status: '', use_reason: '', use_details: '' });
      else interviewRecord.details.meds.splice(Number(b.dataset.row), 1);
    }
    if (key === 'other_meds') {
      if (b.dataset.interviewAdd) interviewRecord.details.other_meds.push({ item_id: H.medicineItemId(), checked: false, priority: 0, use_status: '', use_reason: '', use_details: '' });
      else interviewRecord.details.other_meds.splice(Number(b.dataset.row), 1);
    }
    if (b.dataset.interviewAdd && (key === 'meds' || key === 'other_meds')) interviewExpanded.add(interviewRecord.details[key].at(-1));
    interviewChanged(key);
    renderInterview();
    return true;
  }
  if (b.dataset.interviewFolder !== undefined) {
    await hmr.openPatientFolder(Number(interviewId));
    return true;
  }
  if (b.dataset.interviewExport || b.dataset.interviewAssist !== undefined) {
    const consentError = H.consentValidation(interviewRecord.consent);
    if (!b.dataset.interviewAssist && consentError) {
      interviewStatus(consentError);
      return true;
    }
    if (!(await saveInterview(true))) return true;
    const patientId = interviewId;
    const assist = b.dataset.interviewAssist !== undefined;
    const body = { job: assist ? 'interview_assist' : 'interview_pack', patient_id: Number(interviewId) };
    if (!assist) body.format = b.dataset.interviewExport;
    const output = $('interview-output');
    output.textContent = 'Starting...';
    try {
      const { id } = await hmr.api('POST', '/api/jobs', body);
      let result;
      do {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        result = await hmr.api('GET', `/api/jobs/${encodeURIComponent(id)}`);
        output.textContent = result.state === 'running' ? 'Working...' : `${result.state}: ${result.output || ''}`;
      } while (result.state === 'running' || result.state === 'queued');
      if (page !== 'interview' || interviewId !== patientId) return true;
      interviewOutput = output.textContent;
      if (assist && result.state === 'done') {
        const fresh = await hmr.api('GET', `/api/patients/${encodeURIComponent(interviewId)}/interview`);
        if (page !== 'interview' || interviewId !== patientId) return true;
        for (let i = 0; i < (interviewRecord.meds || []).length; i++)
          if (!interviewRecord.meds[i][3] && fresh.meds?.[i]?.[3]) interviewRecord.meds[i][3] = fresh.meds[i][3];
        if (!(interviewRecord.clarify || []).some((x) => x.trim())) interviewRecord.clarify = fresh.clarify || [];
        if (interviewDirty()) await saveInterview();
        renderInterview();
      }
    } catch (error) {
      interviewOutput = errorText(error);
      output.textContent = interviewOutput;
    }
    return true;
  }
  return false;
}

let followupId = '', followupNumber = '', followupRecord = null;
const followupStatus = (text) => { if ($('followup-status')) $('followup-status').textContent = text; };
const followupSaver = H.autosaver({
  getRecord: () => followupRecord, getId: () => followupId,
  draftKey: () => `followup:${followupId}-${followupNumber}`,
  endpoint: (id, record) => hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/followup/${followupNumber}`, record),
  status: followupStatus, errorText: (...args) => errorText(...args),
});
async function leaveFollowup() {
  if (!(await followupSaver.leave())) return false;
  followupRecord = null;
  return true;
}
async function openFollowup(id, number) {
  const target = String(id), requestedNumber = String(number), previousId = followupId, previousNumber = followupNumber;
  if (page === 'followup_editor' && followupId === target && String(followupNumber) === requestedNumber && followupRecord) return { ok: true };
  if (page === 'followup_editor' && !(await leaveFollowup())) return { cancelled: true };
  followupId = target; followupNumber = number;
  await navigate('followup_editor');
  if (page !== 'followup_editor' || followupId !== target || String(followupNumber) !== requestedNumber) {
    if (page !== 'followup_editor' && followupId === target && String(followupNumber) === requestedNumber) { followupId = previousId; followupNumber = previousNumber; }
    return { cancelled: true };
  }
  return followupRecord ? { ok: true } : { ok: false, error: 'Follow-up could not be opened' };
}
async function followupScreen() {
  if (followupRecord) return;
  const id = followupId, number = followupNumber;
  const [record, medicineContext] = await Promise.all([
    hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/followup/${number}`),
    hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/medicine-context`).catch(() => ({error: true})),
  ]);
  if (page !== 'followup_editor' || id !== followupId || number !== followupNumber) return;
  followupRecord = { date: '', method: 'phone', spoke_with: '', med_changes: '', recommendations: [], issues: '', outcome: '', notes: '', ...record };
  followupRecord.recommendations ||= [];
  followupSaver.reset(followupRecord);
  const fields = [['spoke_with', 'Spoke with'], ['med_changes', 'Medicine changes'], ['issues', 'Issues'], ['outcome', 'Outcome'], ['notes', 'Notes']];
  $('screen').innerHTML = `<div class="actions"><button data-followup-back>Back to patient</button><button class="primary" data-followup-save>Save</button><button data-followup-export>Export Word</button><span id="followup-status" role="status">Ready</span></div>
    <section class="interview-section"><h2>Follow-up ${esc(number)}</h2><div class="form"><label>Date<input type="date" data-followup-field="date" value="${esc(followupRecord.date || '')}"></label><label>Method<select data-followup-field="method">${['phone', 'in person'].map(v => `<option value="${v}" ${followupRecord.method === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label></div></section>
    ${followupMedicineContextMarkup(medicineContext)}
    ${fields.slice(0, 2).map(([key, label]) => `<section class="interview-section"><label>${label}<textarea data-followup-field="${key}">${esc(followupRecord[key] || '')}</textarea></label></section>`).join('')}
    <section class="interview-section"><h2>Recommendations</h2><div class="interview-table"><table><thead><tr><th>Recommendation</th><th>Implemented</th><th>Comment</th></tr></thead><tbody>${followupRecord.recommendations.map((row, i) => `<tr><td>${esc(row[0] || '')}</td><td><select data-followup-row="${i}" data-col="1" aria-label="Implemented for recommendation ${i + 1}">${[['', 'Choose'], ['yes', 'Yes'], ['partly', 'Partly'], ['no', 'No']].map(([v, label]) => `<option value="${v}" ${row[1] === v ? 'selected' : ''}>${label}</option>`).join('')}</select></td><td><textarea data-followup-row="${i}" data-col="2" aria-label="Comment for recommendation ${i + 1}">${esc(row[2] || '')}</textarea></td></tr>`).join('')}</tbody></table></div></section>
    ${fields.slice(2).map(([key, label]) => `<section class="interview-section"><label>${label}<textarea data-followup-field="${key}">${esc(followupRecord[key] || '')}</textarea></label></section>`).join('')}`;
}
document.addEventListener('input', (event) => {
  if (page !== 'followup_editor' || !followupRecord) return;
  const el = event.target;
  if (el.dataset.followupField) followupRecord[el.dataset.followupField] = el.value;
  else if (el.dataset.followupRow !== undefined) followupRecord.recommendations[Number(el.dataset.followupRow)][Number(el.dataset.col)] = el.value;
  else return;
  followupSaver.changed();
});
async function followupClick(b) {
  if (page !== 'followup_editor') return false;
  if (b.dataset.followupBack !== undefined) { await navigate('patients'); return true; }
  if (b.dataset.followupSave !== undefined) { await followupSaver.save(true); return true; }
  if (b.dataset.followupExport !== undefined) {
    if (await followupSaver.save(true)) {
      try { const result = await hmr.api('POST', `/api/patients/${encodeURIComponent(followupId)}/followup/${followupNumber}/export`, {}); followupStatus(`Exported: ${result.file}`); }
      catch (e) { followupStatus(`Export failed - ${errorText(e)}`); }
    }
    return true;
  }
  return false;
    }
