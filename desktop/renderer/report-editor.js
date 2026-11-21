const reportTables = {
  meds: ['Medicine', 'Directions', 'Comment', 'Action'],
  otc: ['Product', 'Dose', 'Notes'],
  ceased: ['Medicine', 'Dose', 'Reason'],
  path: ['Test', 'Result', 'Units', 'Range', 'Interpretation'],
};
const letterFields = ['dear', 'thanks', 'reason', 'intro', 'followup'];
let reportId = '',
  reportRecord = null,
  reportDetail,
  reportDraft,
  reportAgent, reportAi = false,
  reportSearchTimer,
  reportResults = [],
  reportUndo,
  reportUndoTimer,
  reportOutput = '',
  reportBuildStatus = '',
  reportBuildRunning = false,
  lastBuildResult = null,
  reportSaveStatus = 'All changes saved',
  reportSuggestions = [],
  reportGaps = [],
  reportSuggestionSnapshot = '',
  reportSuggestionRun = 0,
  reportSuggestionAdding = false,
  reportSuggestionMessage = '',
  reportAdded = new Set(),
  reportDismissed = new Set(),
  reportLetterOpen = false,
  reportDetailsOpen = true;
const reportSaver = H.autosaver({
  getRecord: () => reportRecord,
  getId: () => reportId,
  draftKey: () => `report:${reportId}`,
  endpoint: (id, record) => hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report`, typeof record.revision === 'string' ? { ...record, expected_revision: record.revision } : record), // conditional save: a stale window cannot overwrite a newer report
  status: (message) => {
    reportSaveStatus = message.startsWith('Saved ') ? 'All changes saved' : message === 'Not saved' ? 'Unsaved changes' : message;
    if ($('report-status')) $('report-status').textContent = reportSaveStatus;
    if (message.startsWith('Saved ') && page === 'report_editor' && $('report-currency-status')) loadReportStatus();
  },
  errorText: (...args) => errorText(...args), // defined in renderer.js, which loads after this file
});
async function leaveReport() {
  if (!(await reportSaver.leave())) return false;
  clearTimeout(reportSearchTimer);
  clearTimeout(reportUndoTimer);
  reportRecord = null;
  reportId = '';
  return true;
}
async function openReport(id) {
  const target = String(id), previous = reportId;
  if (page === 'report_editor' && reportId !== target && !(await leaveReport())) return { cancelled: true };
  reportId = target;
  if (page !== 'report_editor') await navigate('report_editor');
  else await reportScreen();
  if (page !== 'report_editor' || reportId !== target) {
    if (page !== 'report_editor' && reportId === target) reportId = previous;
    return { cancelled: true };
  }
  return reportRecord ? { ok: true } : { ok: false, error: 'Report could not be opened' };
}
async function reportScreen() {
  if (reportRecord) return;
  const requestedId = reportId, id = encodeURIComponent(requestedId);
  const [record, detail, agents, draft, settingsData] = await Promise.all([
    hmr.api('GET', `/api/patients/${id}/report`),
    hmr.api('GET', `/api/patients/${id}`),
    hmr.api('GET', '/api/agents'),
    hmr.api('GET', `/api/patients/${id}/report?ai=1`),
    hmr.api('GET', '/api/settings').catch(() => ({ settings: [] })),
  ]);
  if (page !== 'report_editor' || reportId !== requestedId) return;
  if (record.saved === false) {
    $('screen').innerHTML =
      '<p>Start the report before editing.</p><button data-page="reports">Back to reports</button>';
    return;
  }
  reportAi = settingsData.settings?.find(x => x.key === 'ai_report_assist')?.value === true;
  reportRecord = record;
  reportDetail = detail;
  reportDraft = draft.saved === false ? null : draft;
  const name = agents.per_step?.report_assist || agents.default || 'No agent selected';
  reportAgent = `${name} - ${agents.agents?.find((a) => a.name === name)?.route || 'route not set'}`;
  reportRecord.issues ||= [];
  reportResults = [];
  reportQuery = '';
  reportUndo = null;
  reportOutput = '';
  reportBuildStatus = '';
  ((reportSaveStatus = 'All changes saved'),
    (reportSuggestions = []),
    (reportGaps = []),
    (reportSuggestionMessage = ''),
    (reportAdded = new Set()),
    (reportDismissed = new Set()),
    (reportLetterOpen = false),
    (reportDetailsOpen = true));
  reportAdded = new Set();
  reportDismissed = new Set();
  reportSuggestions = [];
  reportGaps = [];
  reportSuggestionMessage = 'Loading suggestions...';
  reportLetterOpen = letterFields.some((key) => record.needs_review?.includes(key));
  reportDetailsOpen = true;
  reportSaver.reset(record);
  renderReport();
  loadSuggestions();
}
let reportStatusRun = 0;
async function loadReportStatus() {
  const id = reportId, run = ++reportStatusRun;
  try {
    const status = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report-status`);
    if (id !== reportId || page !== 'report_editor' || run !== reportStatusRun || !$('report-currency-status')) return;
    $('report-currency-status').innerHTML = H.reportStatusHtml(status);
  } catch (error) {
    if (id !== reportId || page !== 'report_editor' || run !== reportStatusRun || !$('report-currency-status')) return;
    $('report-currency-status').innerHTML = '<p class="muted">Report status could not be checked.</p>';
  }
}
async function loadSuggestions() {
  const id = reportId, run = ++reportSuggestionRun;
  reportSuggestionSnapshot = '';
  reportSuggestions = [];
  reportSuggestionMessage = 'Loading suggestions...';
  if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
  try {
    const data = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/suggestions`);
    if (id !== reportId || page !== 'report_editor' || run !== reportSuggestionRun) return;
    reportSuggestions = data.suggestions || [];
    reportSuggestionSnapshot = data.context_snapshot_sha256 || '';
    reportAdded = new Set();
    reportDismissed = new Set();
    reportGaps = data.context_gaps || [];
    reportSuggestionMessage = reportSuggestions.length ? '' : 'No suggestions for this patient yet.';
  } catch (error) {
    if (id !== reportId || page !== 'report_editor' || run !== reportSuggestionRun) return;
    reportSuggestions = [];
    reportGaps = [];
    reportSuggestionMessage =
      error.status === 404 || /404|not found/i.test(String(error.message))
        ? 'Suggestions are not available yet (engine needs updating)'
        : errorText(error);
  }
  if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
}
const heldReasons = { duplicate: 'More than one identical medicine row, so the text cannot be assigned safely.', changed_or_removed: 'The medicine, its use or its source note changed, or the row is gone.' };
function heldActionsHtml() {
  const held = reportRecord?.held_medicine_actions || [];
  if (!held.length) return '';
  return `<div class="report-refresh" role="alert" data-held-actions><div style="width:100%"><strong>${held.length} medicine recommendation${held.length === 1 ? '' : 's'} not carried forward by refresh</strong><p class="muted">Your typed text is kept here. It was not applied to any row. Re-enter it in the Action column only where it still applies, then mark it handled.</p>${held.map((h, i) => `<section data-held-action="${esc(h.id)}"><strong>${esc(h.name)}</strong><div class="muted">${esc(h.directions)}${h.comment ? ' | ' + esc(h.comment) : ''}</div><div class="muted">${esc(heldReasons[h.reason] || 'Not carried forward.')}</div><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(h.action)}</pre><div class="actions"><button data-held-copy="${i}">Copy text</button><button data-held-resolve="${esc(h.id)}">Mark handled</button></div></section>`).join('')}</div></div>`;
}
function suggestionEvidenceHtml(item) {
  if (!item.evidence?.length) return '<p>No source-addressed evidence supplied. Reload suggestions.</p>';
  return `<details open><summary>Matched source evidence (not clinical interpretation)</summary>${item.evidence.map(e => `<section class="suggestion-evidence" style="overflow-wrap:anywhere"><strong>${esc(e.kind)} - ${esc(e.id)}</strong><p style="white-space:pre-wrap">${esc(e.text)}</p><p>${esc(e.verification || '')}${e.verified_by ? ` | ${esc(e.verified_by)} at ${esc(e.verified_at || 'time not recorded')}` : ''}${e.use_status ? ` | Use: ${esc(e.use_status)}` : ''}</p><p>Source: ${esc(e.source || 'not established')} | Date: ${esc(e.date || 'not established')}${e.age_days !== null && e.age_days !== undefined ? ` (${esc(e.age_days)} days before context check)` : ''}</p>${e.unit !== undefined ? `<p>Units: ${esc(e.unit || 'missing')} | Reference interval: ${esc(e.reference_interval || 'not recorded')}</p>` : ''}${e.comment ? `<p>Original comment: ${esc(e.comment)}</p>` : ''}${e.flags?.length ? `<p>Check: ${esc(e.flags.join('; '))}</p>` : ''}</section>`).join('')}</details>`;
}
function suggestionsHtml() {
  return `${reportGaps.length ? (reportGaps.every(gap => typeof gap === 'string' && gap.trim()) ? `<ul class="muted">${reportGaps.map(gap => `<li>${esc(gap.replaceAll('_', ' '))}</li>`).join('')}</ul>` : '<p class="muted">Add interview notes or confirm the medicines to get suggestions.</p>') : ''}${reportSuggestionMessage ? `<p class="muted">${esc(reportSuggestionMessage)}</p>` : ''}${reportSuggestions.map((item, i) => (reportDismissed.has(i) ? '' : `<article class="card helper-card"><span class="source-chip">${esc(H.sourceLabel(item.source))}</span><h3>${esc(item.title)}</h3>${item.why?.length ? `<ul>${item.why.map((why) => `<li>${esc(why)}</li>`).join('')}</ul>` : ''}<p class="muted">Past-case template only, not a patient finding. Review and edit before inclusion.</p><h4>Proposed recommendation</h4><p>${esc(item.rec || '')}</p><h4>Template rationale</h4><p>${esc(item.rationale || '')}</p>${suggestionEvidenceHtml(item)}${item.missing?.length ? `<p>Check first:</p><ul data-suggestion-check-first>${item.missing.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}${item.brainstorm ? `<details><summary>Brainstorm V2 - ${esc(item.brainstorm.title)} (p.${esc(item.brainstorm.page)})</summary><p>${esc(item.brainstorm.snippet)}</p><button data-suggestion-copy="${i}">Copy</button></details>` : ''}<div class="actions"><button data-suggestion-add="${i}" ${reportAdded.has(i) || !reportSuggestionSnapshot ? 'disabled' : ''}>${reportAdded.has(i) ? 'Added' : 'Add to findings'}</button><button data-suggestion-dismiss="${i}">Dismiss</button></div></article>`)).join('')}`;
}
function reportField(key, label, multiline = true) {
  const review = reportRecord.needs_review?.includes(key)
    ? `<small data-report-review="${esc(key)}">Template text &#8212; rewrite before building</small>`
    : '';
  const input = multiline
    ? `<textarea data-field="${esc(key)}">${esc(reportRecord[key] || '')}</textarea>`
    : `<input data-field="${esc(key)}" value="${esc(H.date(reportRecord[key] || ''))}">`;
  const unrecorded = (key === 'allergies' || key === 'conditions') && !String(reportRecord[key] || '').trim()
    ? `<small data-report-unrecorded="${esc(key)}">Nothing is recorded here. This means unknown, not "none". Check the interview before building.</small>`
    : '';
  return `<label>${esc(label)} ${review}${unrecorded}${input}</label>`;
}
function reportDateNoteHtml() {
  const r = H.reportDateReview(reportRecord?.report_date);
  if (r.state === 'ok') return '';
  const button = r.state === 'old' || r.state === 'future' || r.state === 'missing' || r.state === 'malformed'
    ? ` <button type="button" data-report-date-today>Set to today (${esc(r.today)})</button>` : '';
  return `<small role="status" data-report-date-review="${esc(r.state)}">${esc(r.text)}${button}</small>`;
}
function followupDecisionHtml() {
  if (reportRecord.followup_decision === undefined) {
    return reportRecord.followup
      ? `<label><input type="checkbox" data-followup-reviewed ${reportRecord.followup_text_reviewed ? 'checked' : ''}> I have reviewed this follow-up wording (kept from an earlier draft)</label>` : '';
  }
  const d = reportRecord.followup_decision;
  const opts = [['', 'Choose...'], ['required', 'Follow-up required (enter the plan and timing above)'], ['not_required', 'No follow-up planned (proposed wording above)']]
    .map(([v, t]) => `<option value="${v}" ${d === v ? 'selected' : ''}>${t}</option>`).join('');
  const confirm = `<label><input type="checkbox" data-followup-reviewed ${reportRecord.followup_text_reviewed ? 'checked' : ''}> I have reviewed this follow-up wording</label>`;
  return `<label>Follow-up decision<select data-followup-decision>${opts}</select></label>${confirm}`;
}
function renderReport() {
  if ($('report-letter')) reportLetterOpen = $('report-letter').open;
  if ($('report-details')) reportDetailsOpen = $('report-details').open;
  const letter = [
    ['dear', 'Dear'],
    ['thanks', 'Thanks'],
    ['reason', 'Reason'],
    ['intro', 'Introduction'],
    ['followup', 'Follow-up'],
  ]
    .map(([key, label]) => reportField(key, label, key !== 'dear'))
    .join('') + followupDecisionHtml();
  const details =
    [
      ['patient', 'Patient'],
      ['doctor', 'Doctor'],
      ['conditions', 'Conditions'],
      ['allergies', 'Allergies'],
      ['obs', 'Observations'],
    ]
      .map(([key, label]) => reportField(key, label))
      .join('') +
    Object.entries(reportTables)
      .map(
        ([key, columns]) =>
          `<div class="report-table"><h3>${esc({ meds: 'Medicines', otc: 'OTC', ceased: 'Ceased medicines', path: 'Pathology' }[key])}</h3>${key === 'path' ? reportField('path_date', 'Pathology date', false) : ''}${H.tableInput(key, key, columns, reportRecord[key], 'report')}${key === 'meds' ? `<div id="held-actions">${heldActionsHtml()}</div>` : ''}</div>`,
      )
      .join('');
  const findings = reportRecord.issues
    .map(
      (issue, i) =>
        `<article class="card finding"><div class="finding-heading"><h3><span class="finding-number">${i + 1}</span> Finding</h3><div class="actions"><button data-finding-move="${i}" data-direction="-1" ${i === 0 ? 'disabled' : ''}>Move up</button><button data-finding-move="${i}" data-direction="1" ${i === reportRecord.issues.length - 1 ? 'disabled' : ''}>Move down</button><button data-finding-delete="${i}">Delete</button></div></div>${[
          ['title', 'Title'],
          ['rec', 'Recommendation'],
          ['rationale', 'Rationale'],
        ]
          .map(
            ([key, label]) =>
              `<label>${label}${key === 'title' ? `<input data-issue="${i}" data-prop="${key}" value="${esc(issue[key] || '')}">` : `<textarea data-issue="${i}" data-prop="${key}">${esc(issue[key] || '')}</textarea>`}</label>`,
          )
          .join('')}${issue.suggestion_source ? `<div class="template-review" data-template-review-state="${issue.template_reviewed ? 'reviewed' : 'pending'}"><p data-template-review-note="${i}">${templateReviewNote(issue.template_reviewed)}</p><label><input type="checkbox" data-template-reviewed="${i}" ${issue.template_reviewed ? 'checked' : ''}> I have reviewed this imported wording for this patient</label></div><details><summary>Evidence retained when selected (not automatically refreshed)</summary><p>Re-review if the interview, pathology or medicines change. Editing the finding does not update this retained evidence.</p>${suggestionEvidenceHtml(issue.suggestion_source)}</details>` : ''}</article>`,
    )
    .join('');
  const file = (reportDetail.files?.folder || []).find((f) => /^mims interactions.*\.txt$/i.test(f));
  const outputName = String(reportRecord.out || '')
    .split(/[\\/]/)
    .pop();
  $('screen').innerHTML =
    `<div class="report-top"><button data-page="reports">Back to reports</button><div><strong>${esc(reportDetail.name || reportRecord.name)}</strong><span class="muted"> &middot; ${esc(reportDetail.gp || String(reportRecord.doctor || '').split('\n')[0] || 'GP not set')}</span><br><small class="muted">${esc(outputName)}</small></div><div class="report-dates">${reportField('assess_date', 'Assessment date (DD/MM/YYYY)', false)}${reportField('report_date', 'Report date (DD/MM/YYYY)', false)}<div data-report-date-note>${reportDateNoteHtml()}</div></div><span id="report-status" role="status">${esc(reportSaveStatus)}</span><span id="report-build-status" role="status" aria-live="polite">${esc(reportBuildStatus || H.buildDisabledReason(reportRecord.issues.length))}</span><div class="actions"><button data-report-save>Save</button><button data-report-build="word" ${!reportRecord.issues.length ? `disabled title="${esc(H.buildDisabledReason(0))}"` : ''}>Build Word</button><button class="primary" data-report-build="pdf" ${!reportRecord.issues.length ? `disabled title="${esc(H.buildDisabledReason(0))}"` : ''}>Build Word + PDF</button></div></div>${demographicsHtml()}${H.showInterviewRefresh(reportRecord, reportDetail) || reportRecord.pathology_newer ? `<div class="report-refresh" role="status"><span>${esc(reportRecord.pathology_newer ? 'Verified pathology has changed since this report was prepared. Refresh and re-review the report before building.' : 'The interview was changed after this report was started.')}</span><button data-report-refresh>Refresh report from current interview and pathology</button></div>` : ''}<div id="report-currency-status" role="status"></div><div class="report-layout"><div class="report-main"><section class="report-findings"><h2>Findings</h2><p class="muted">${reportRecord.issues.length} findings &middot; about 4-8</p>${findings}<div class="actions"><button data-finding-add>Add finding</button>${reportUndo ? '<button data-finding-undo>Undo deletion</button>' : ''}</div></section><details class="interview-section report-disclosure" id="report-letter" ${reportLetterOpen ? 'open' : ''}><summary>Letter wording</summary><div class="report-fields">${letter}</div></details><details class="interview-section report-disclosure" id="report-details" ${reportDetailsOpen ? 'open' : ''}><summary>Patient details in the report</summary><div class="report-fields">${details}</div></details></div><aside class="report-sidebar">${typeof evidenceReferencePanel==='function' ? evidenceReferencePanel() : ''}${localReferencePanel()}<section><div class="helper-heading"><h2>Suggestions for this patient</h2><button data-suggestions-reload>Reload</button></div><div id="suggestions" role="status">${suggestionsHtml()}</div></section><section><h2>Find in library</h2><label>Search<input id="library-search" type="search" value="${esc(reportQuery)}"></label><div id="library-results" role="status">${libraryResultsHtml()}</div></section>${reportAi ? `<section><h2>AI assist (optional)</h2><p>${esc(reportAgent)}</p><button data-report-assist>Draft with AI</button>${reportDraft ? '<div class="actions"><button data-report-load="all">Load AI draft</button><button data-report-load="findings">Take findings only</button></div>' : ''}${file ? `<p>${esc(file)} <button data-open-interactions="${esc(file)}">Open</button></p>` : ''}<pre id="report-output" role="status">${esc(reportOutput)}</pre></section>` : ''}</aside></div>`;
  document.querySelectorAll('.report-layout textarea').forEach(H.growTextarea);
  refreshLocalReferenceStatus();
  loadReportStatus();
  if(typeof refreshEvidenceReferences==='function')refreshEvidenceReferences();
  $('report-letter').addEventListener('toggle', (event) => {
    reportLetterOpen = event.target.open;
  });
  $('report-details').addEventListener('toggle', (event) => {
    reportDetailsOpen = event.target.open;
  });
}
function demographicsHtml() {
  const rows = (reportRecord.demographic_mismatches || []).map((m) => `<div class="report-demographic" data-demographic="${esc(m.key)}"><strong>${esc(m.label)} differs from the patient record${m.acknowledged ? ' (kept as written)' : ''}</strong>
    <div>In the report:<pre>${esc(m.report)}</pre></div><div>In the patient record:<pre>${esc(m.record)}</pre></div>
    ${m.acknowledged ? '<small class="muted">You chose to keep the report text. This asks again if the text or the record changes.</small>' : ''}
    <div class="actions"><button data-demo-action="replace" data-demo-key="${esc(m.key)}">Use patient record</button>${m.acknowledged ? '' : `<button data-demo-action="keep" data-demo-key="${esc(m.key)}">Keep report text</button>`}</div></div>`);
  return rows.length ? `<div class="report-refresh" role="alert">${rows.join('')}</div>` : '';
}
async function resolveDemographic(action, key) {
  const label = (reportRecord.demographic_mismatches || []).find((m) => m.key === key)?.label || 'block';
  const question = action === 'replace'
    ? `Replace the report's ${label} with the patient record's text? The text now in the report is removed (the previous report is backed up).`
    : `Keep the report's ${label} as written? The report will print and be signed with this text, which differs from the patient record. This is recorded, and it asks again if the text or the record changes.`;
  if (!confirm(question)) return true;
  const id = reportId, screen = $('screen');
  screen.inert = true;
  try {
    if (!(await reportSaver.save())) return true;
    const updated = await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report/demographics`, { action, keys: [key] });
    if (page === 'report_editor' && reportId === id) { reportRecord = updated; reportSaver.reset(updated); renderReport(); }
  } catch (error) { alert(errorText(error)); }
  finally { screen.inert = false; }
  return true;
}
let reportQuery = '';
function libraryResultsHtml() {
  if (!reportQuery.trim()) return '<p class="muted">Search the library for findings.</p>';
  if (!reportResults.length) return '<p class="muted">No results found.</p>';
  return reportResults
    .map(
      (r, i) => {
        const brainstorm = /^Brainstorm V2 p\./i.test(r.source || '');
        return `<article class="card helper-card"><span class="source-chip">${esc(brainstorm ? r.source : H.sourceLabel(r.source))}</span><h3>${esc(r.title)}</h3><p class="library-excerpt">${esc(brainstorm ? r.snippet : H.firstLines(r.rec))}</p>${brainstorm ? `<button data-library-copy="${i}">Copy</button>` : `<button data-library-insert="${i}">Insert</button>`}</article>`;
      },
    )
    .join('');
}
document.addEventListener('input', (event) => {
  if (page !== 'report_editor' || !reportRecord) return;
  const el = event.target;
  if (el.id === 'library-search') {
    reportQuery = el.value;
    clearTimeout(reportSearchTimer);
    const id = reportId,
      query = reportQuery;
    reportSearchTimer = setTimeout(async () => {
      try {
        const data = await hmr.api('GET', `/api/library?q=${encodeURIComponent(query)}`);
        if (page === 'report_editor' && id === reportId && query === reportQuery) {
          reportResults = data.results || [];
          $('library-results').innerHTML = libraryResultsHtml();
        }
      } catch (error) {
        if ($('library-results')) $('library-results').textContent = errorText(error);
      }
    }, 300);
    return;
  }
  if (el.dataset.templateReviewed !== undefined) {
    const index = Number(el.dataset.templateReviewed), issue = reportRecord.issues[index], id = reportId;
    if (!issue) return;
    const refresh = async () => {
      const fresh = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report`);
      if (reportId === id && page === 'report_editor') {
        reportSaver.adopt({ issues: fresh.issues, suggestion_context_sha256: fresh.suggestion_context_sha256 });
        renderReport();
      }
      return fresh;
    };
    if (!el.checked) {
      issue.template_reviewed = false;
      showTemplateReviewState(index, false);
      reportSaver.changed();
      (async () => { if (await reportSaver.save(true)) await refresh(); })().catch((e) => alert(errorText(e)));
      return;
    }
    el.checked = false; // becomes checked only when the engine confirms the review
    (async () => {
      if (!(await reportSaver.save(true))) return; // the wording on screen is stored first; the review covers exactly that text
      const seen = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report`);
      if (reportId !== id || page !== 'report_editor' || reportRecord.issues[index] !== issue) return;
      issue.template_reviewed = true;
      issue.template_review_for = seen.suggestion_context_sha256 || '';
      reportSaver.changed();
      if (!(await reportSaver.save(true))) return;
      const fresh = await refresh();
      if (!fresh.issues?.[index]?.template_reviewed) alert('Review not recorded: the wording or the patient sources changed. Check the finding and tick again.');
    })().catch((e) => alert(errorText(e)));
    return;
  }
  if (el.dataset.followupReviewed !== undefined) { reportRecord.followup_text_reviewed = !!el.checked; reportSaver.changed(); return; }
  if (el.dataset.followupDecision !== undefined) {
    reportRecord.followup_decision = el.value;
    reportRecord.followup_text_reviewed = false;
    reportSaver.changed();
    (async () => {  // the engine fills only blank or unedited generated wording, so re-read it
      if (!(await reportSaver.save(true))) return;
      const fresh = await hmr.api('GET', `/api/patients/${encodeURIComponent(reportId)}/report`);
      // Keep edits made while this ran (a later tick or typing). reset() would mark them saved.
      reportSaver.adopt({ followup: fresh.followup });
      renderReport();
    })().catch((e) => alert(errorText(e)));
    return;
  }
  if (el.tagName === 'TEXTAREA') H.growTextarea(el);
  if (el.dataset.issue !== undefined) {
    const issue = reportRecord.issues[Number(el.dataset.issue)];
    issue[el.dataset.prop] = el.value;
    if (issue.suggestion_source) {  // editing is never a review
      issue.template_reviewed = false;
      showTemplateReviewState(Number(el.dataset.issue), false);  // checkbox, wording and state agree immediately
    }
  }
  else if (el.dataset.field) {
    const key = el.dataset.field;
    if (el.dataset.row !== undefined) reportRecord[key][Number(el.dataset.row)][Number(el.dataset.col)] = el.value;
    else reportRecord[key] = el.value;
    if (key === 'followup') { reportRecord.followup_text_reviewed = false; document.querySelector('[data-followup-reviewed]') && (document.querySelector('[data-followup-reviewed]').checked = false); }
    if (reportRecord.needs_review) reportRecord.needs_review = H.reviewed(reportRecord.needs_review, key);
    document.querySelector(`[data-report-review="${key}"]`)?.remove();
    if (key === 'report_date') { const note = document.querySelector('[data-report-date-note]'); if (note) note.innerHTML = reportDateNoteHtml(); }
  } else return;
  reportSaver.changed();
});
async function reportJob(job, extra = {}) {
  const id = reportId;
  reportOutput = 'Starting...';
  if ($('report-output')) $('report-output').textContent = reportOutput;
  try {
    const task = await hmr.api('POST', '/api/jobs', { job, patient_id: Number(id), ...extra });
    let result;
    do {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      result = await hmr.api('GET', `/api/jobs/${encodeURIComponent(task.id)}`);
      reportOutput = `${result.state}: ${result.output || ''}`;
      if (page === 'report_editor' && reportId === id && $('report-output')) $('report-output').textContent = reportOutput;
    } while (['running', 'queued'].includes(result.state));
    if (job === 'report_build') lastBuildResult = result;
    if (job === 'report_build' && result.state !== 'done') showBuildError(result.output || 'Report build failed');
    return result.state === 'done';
  } catch (error) {
    reportOutput = errorText(error);
    if (job === 'report_build') showBuildError(reportOutput);
    if ($('report-output')) $('report-output').textContent = reportOutput;
    return false;
  }
}
function templateReviewNote(reviewed) {
  return reviewed ? 'Imported past-case wording reviewed for this patient.' : 'Imported from a past-case template and not yet reviewed for this patient. The report cannot be built until you review it. Editing the wording does not count as review.';
}
function showTemplateReviewState(index, reviewed) {
  const box = document.querySelector(`[data-template-reviewed="${index}"]`);
  if (box) box.checked = !!reviewed;
  const note = document.querySelector(`[data-template-review-note="${index}"]`);
  if (note) note.textContent = templateReviewNote(reviewed);
  const holder = note?.closest?.('[data-template-review-state]');
  if (holder) holder.dataset.templateReviewState = reviewed ? 'reviewed' : 'pending';
}
function showBuildError(message) {
  const template = String(message).match(/Review imported template findings:\s*([0-9, ]+)/i);
  if (template) {
    const numbers = template[1].split(',').map((n) => Number(n.trim())).filter(Boolean);
    alert(`Review imported template wording before building (finding ${numbers.join(', ')}). Tick "I have reviewed this imported wording for this patient" on each.`);
    document.querySelector(`[data-template-reviewed="${(numbers[0] || 1) - 1}"]`)?.focus();
    return;
  }
  const match = String(message).match(/Review placeholder fields:\s*([^\r\n]+)/i);
  if (!match) { alert(message); return; }
  const labels = { reason: 'Reason for referral', intro: 'Introduction', thanks: 'Thanks', followup: 'Follow-up', followup_decision: 'Follow-up decision', followup_plan: 'Follow-up plan and timing', followup_review: 'Follow-up wording review' };
  const fields = match[1].split(',').map(field => field.trim()).filter(field => labels[field]);
  alert(`Review placeholder fields: ${fields.map(field => labels[field]).join(', ') || match[1]}`);
  if (fields.length) {
    $('report-letter').open = true;
    document.querySelector(`[data-field="${fields[0]}"]`)?.focus();
  }
}
async function buildReport(pdf) {
  if (!reportRecord.issues.length) {
    alert('add at least one finding');
    return;
  }
  // Every early return says why. A refused or skipped build must never look like a dead button.
  const say = (text) => { reportBuildStatus = text; const el = $('report-build-status'); if (el) el.textContent = text; };
  if (reportBuildRunning) { say('A build is already running. Wait for it to finish before starting another.'); return; }  // a second click must not start a second job
  reportBuildRunning = true;
  try {
    if (!await reportSaver.save(true)) {
      // A failed or conflicting save never proceeds to a build. Show the reason beside the button, not only in the save line.
      say(`Build not started. The report could not be saved (${reportSaveStatus}). Nothing was built.`);
      return;
    }
    await runBuild(pdf);
  } finally { reportBuildRunning = false; }
}
async function runBuild(pdf) {
  const setStatus = (text) => { reportBuildStatus = text; const el = $('report-build-status'); if (el) el.textContent = text; };
  const buttons = () => [...document.querySelectorAll('[data-report-build]')];
  buttons().forEach((b) => { b.disabled = true; });
  lastBuildResult = null;
  setStatus(pdf ? 'Building Word and PDF. This can take up to a minute...' : 'Building Word...');
  let ok = false;
  try { ok = await reportJob('report_build', { pdf }); } finally { buttons().forEach((b) => { b.disabled = false; }); }
  loadReportStatus();
  setStatus(ok ? H.buildOutcomeText(lastBuildResult, pdf) : H.buildOutcomeText(lastBuildResult || { state: 'failed', output: reportOutput }, pdf));
}
async function reportEditorClick(b) {
  if (page !== 'report_editor' || !reportRecord) return false;
  const d = b.dataset;
  if (d.demoAction !== undefined) return resolveDemographic(d.demoAction, d.demoKey);
  if (d.heldCopy !== undefined) {
    const text = (reportRecord?.held_medicine_actions || [])[Number(d.heldCopy)]?.action;
    if (text) navigator.clipboard?.writeText(text).catch(() => alert('Copy failed. Select the text and copy it manually.'));
    return true;
  }
  if (d.heldResolve !== undefined) {
    const id = reportId;
    hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report/held-actions`, { id: d.heldResolve, action: 'resolve' })
      .then((updated) => { if (reportId === id && reportRecord) { reportRecord.held_medicine_actions = updated.held_medicine_actions || []; if ($('held-actions')) $('held-actions').innerHTML = heldActionsHtml(); loadReportStatus(); } })
      .catch((error) => alert(errorText(error)));
    return true;
  }
  if (d.reportRefresh !== undefined) {
    if (!confirm("Refreshes the report from the latest interview and pathology. Medicine recommendations are kept ONLY when medicine, actual use and source notes are exactly unchanged and unique; otherwise the typed text is listed under the Medicines table for you to re-enter, and building is blocked until you mark each one handled. Other table edits may be replaced. Your findings and letter text are kept, and the previous report is backed up. Continue?")) return true;
    const id = reportId, screen = $('screen');
    screen.inert = true;
    try {
      if (!(await reportSaver.save())) return true;
      let result = await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report/refresh`);
      const medicineNotes = result?.medication_recommendations;
      if (medicineNotes?.needs_reentry) {
        alert(`${medicineNotes.needs_reentry} previous medication recommendation(s) could not be safely carried forward because the medicine, directions, notes or duplicate identity changed. They are listed under the Medicines table. Re-enter any that still apply, then mark each handled, before building.`);
      }
      // Blocks the pharmacist edited are kept; each difference from the patient record is offered, never replaced silently.
      const replace = (result?.demographic_conflicts || []).filter((c) => confirm(`The ${c.label} in this report was edited and differs from the current patient record.\n\nIn the report:\n${c.report}\n\nIn the patient record:\n${c.record}\n\nOK replaces the report text with the patient record. Cancel keeps your edited text.`)).map((c) => c.key);
      if (replace.length) await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report/refresh`, { replace_demographics: replace });
      if (page === 'report_editor' && reportId === id) {
        const updated = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report`);
        if (page === 'report_editor' && reportId === id) { reportRecord = updated; reportSaver.reset(updated); renderReport(); loadSuggestions(); }
      }
    } catch (error) { alert(errorText(error)); }
    finally { screen.inert = false; }
    return true;
  }
  if (d.suggestionCopy !== undefined || d.libraryCopy !== undefined) {
    const snippet = d.suggestionCopy !== undefined
      ? reportSuggestions[Number(d.suggestionCopy)]?.brainstorm?.snippet
      : reportResults[Number(d.libraryCopy)]?.snippet;
    try {
      await navigator.clipboard.writeText(snippet || '');
    } catch (error) {
      alert(`Could not copy: ${errorText(error)}`);
    }
    return true;
  }
  if (d.suggestionsReload !== undefined) {
    await loadSuggestions();
    return true;
  }
  if (d.suggestionDismiss !== undefined) {
    reportDismissed.add(Number(d.suggestionDismiss));
    $('suggestions').innerHTML = suggestionsHtml();
    return true;
  }
  if (d.suggestionAdd !== undefined) {
    const index = Number(d.suggestionAdd), item = reportSuggestions[index];
    if (reportSuggestionAdding || reportAdded.has(index) || !item || !reportSuggestionSnapshot) return true;
    const id = reportId, record = reportRecord, snapshot = reportSuggestionSnapshot;
    reportSuggestionAdding = true;
    try {
      const current = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/suggestions/context`);
      if (reportId !== id || page !== 'report_editor' || reportRecord !== record || reportSuggestions[index] !== item || reportSuggestionSnapshot !== snapshot) return true;
      if (current.context_snapshot_sha256 !== snapshot || item.context_snapshot_sha256 !== snapshot) {
        reportSuggestionSnapshot = '';
        reportSuggestionMessage = 'Source context changed. Reload suggestions and re-review the evidence before adding.';
        if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
        return true;
      }
      const finding = H.findingFromResult(item);
      finding.suggestion_source = {version:1, context_snapshot_sha256:snapshot, evidence:item.evidence || []};
      reportRecord.issues.push(finding);
      reportAdded.add(index);
      reportSaver.changed();
      renderReport();
    } catch (error) {
      if (reportId === id && page === 'report_editor' && reportRecord === record) {
        reportSuggestionMessage = 'Could not verify source context: ' + errorText(error) + '. Nothing added.';
        if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
      }
    } finally { reportSuggestionAdding = false; }
    return true;
  }
  if (d.reportDateToday !== undefined) {
    reportRecord.report_date = H.reportDateReview('', new Date()).today;  // explicit button only; never automatic
    reportSaver.changed();
    await reportSaver.save(true);
    if (page === 'report_editor') renderReport();
    return true;
  }
  if (d.reportSave !== undefined) {
    await reportSaver.save(true);
    return true;
  }
  if (d.reportBuild) {
    await buildReport(d.reportBuild === 'pdf');
    return true;
  }
  if (d.openInteractions) {
    await hmr.openPatientFolder(Number(reportId), d.openInteractions);
    return true;
  }
  if (d.reportAdd || d.reportRemove) {
    const key = d.reportAdd || d.reportRemove;
    reportRecord[key] = d.reportAdd
      ? H.addRow(reportRecord[key] || [], reportTables[key].length)
      : H.removeRow(reportRecord[key], Number(d.row));
  } else if (d.findingAdd !== undefined) reportRecord.issues.push({ title: '', rec: '', rationale: '' });
  else if (d.findingMove !== undefined)
    reportRecord.issues = H.moveFinding(reportRecord.issues, Number(d.findingMove), Number(d.direction));
  else if (d.findingDelete !== undefined) {
    const index = Number(d.findingDelete);
    reportUndo = { index, item: reportRecord.issues[index] };
    reportRecord.issues = H.removeRow(reportRecord.issues, index);
    clearTimeout(reportUndoTimer);
    reportUndoTimer = setTimeout(() => {
      reportUndo = null;
      document.querySelector('[data-finding-undo]')?.remove();
    }, 10000);
  } else if (d.findingUndo !== undefined && reportUndo) {
    reportRecord.issues = H.undoFinding(reportRecord.issues, reportUndo);
    reportUndo = null;
    clearTimeout(reportUndoTimer);
  } else if (d.libraryInsert !== undefined)
    reportRecord.issues.push(H.findingFromResult(reportResults[Number(d.libraryInsert)]));
  else if (d.reportLoad) {
    if (
      d.reportLoad === 'all' &&
      !confirm(
        'This replaces the findings and letter wording in the editor but not the saved file until you save. Continue?',
      )
    )
      return true;
    reportRecord.issues = JSON.parse(JSON.stringify(reportDraft.issues || []));
    if (d.reportLoad === 'all') {
      for (const key of letterFields) reportRecord[key] = reportDraft[key] || '';
      reportRecord.needs_review = [
        ...new Set([
          ...(reportRecord.needs_review || []).filter((k) => !letterFields.includes(k)),
          ...(reportDraft.needs_review || []).filter((k) => letterFields.includes(k)),
        ]),
      ];
    }
  } else if (d.reportAssist !== undefined) {
    b.disabled = true;
    const id = reportId;
    const extract = (reportDetail.steps || []).find((step) => step.name === 'report_extract');
    const ok =
      extract?.done ||
      (reportDetail.files?.folder || []).some((file) => file.toLowerCase() === 'case.txt') ||
      (await reportJob('report_extract'));
    if (ok && (await reportJob('report_assist')) && page === 'report_editor' && reportId === id) {
      const draft = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report?ai=1`);
      reportDraft = draft.saved === false ? null : draft;
    }
    if (page === 'report_editor' && reportId === id) renderReport();
    return true;
  } else return false;
  reportSaver.changed();
  renderReport();
  return true;
}

function localReferencePanel() {
  return `<section><h2>Private local reference</h2><p class="muted">Separate text matches from your own PDF, not patient-specific advice.</p><label>Edition shown on original<input id="local-ref-edition" maxlength="100" placeholder="e.g. V2.0 NOV2025"></label><button data-local-ref-pick>Choose local PDF</button><label>Search reference<input id="local-ref-query" type="search" maxlength="200"></label><button data-local-ref-search>Search</button><div id="local-ref-results" aria-live="polite"></div></section>`;
}
async function refreshLocalReferenceStatus() {
  const target=$('local-ref-results'),edition=$('local-ref-edition');
  if (!target) return;
  localReferenceHits=[];
  try {
    const ref=await hmr.api('GET','/api/reference/local');
    if (!target.isConnected) return;
    edition.value=ref.edition;
    target.textContent='Registered local edition: '+ref.edition+'. Search to review source passages.';
  } catch (error) {
    if (!target.isConnected) return;
    try {
      const packaged = await hmr.api('GET', '/api/reference/search?q=');
      if (!target.isConnected) return;
      if (packaged && packaged.reference && packaged.reference.packaged) {
        const lost = packaged.registered_original && packaged.registered_original.state === 'registered_unavailable' ? 'Your registered original PDF is unavailable: ' + (packaged.registered_original.reason || error.message) + ' ' : '';
        target.textContent = lost + 'Packaged Brainstorm tables are searchable. Excerpts are extraction text, not re-verified against the original page. Register your original PDF to verify and open source pages.';
        return;
      }
    } catch (_) { /* fall through to the original unavailable message */ }
    target.textContent = error.message;
  }
}
let localReferenceHits = [];
function localReferenceHtml(response) {
  function registeredOriginalNotice(original) {
    return original && original.state === 'registered_unavailable'
      ? `<p class="warning-banner" role="alert"><strong>Your registered original PDF is unavailable.</strong> ${esc(original.reason || 'It is missing, changed or cannot be read.')} Showing packaged extraction only. Register the original again to verify and open source pages.</p>`
      : '';
  }
  const ref=response.reference;
  const packagedNote = ref.packaged ? '<p class="muted">Packaged tables: excerpts are extraction text, not re-verified against the original page. Open-original is available only after you register your own matching PDF.</p>' : '';
  return registeredOriginalNotice(response.registered_original) + `<p>Brainstorm | ${esc(ref.edition)} | ${esc(ref.page_count)} physical PDF pages</p><p class="muted" style="overflow-wrap:anywhere">SHA-256: ${esc(ref.pdf_sha256)}</p><p>All search words must occur in the heading plus one physical page. Text matches only. Writing guide, not clinical advice. Cross-check current sources. Pharmacist review required.</p>${packagedNote}` + (response.results.length ? response.results.map((hit,i)=>`<article class="card helper-card"><h3>${esc(hit.title)}</h3><p>${hit.page_verified === false ? '<strong>Packaged extraction, NOT verified against the original page.</strong> ' : ''}${esc(hit.edition)} | ${hit.page_verified === false ? 'Extracted from page' : 'Physical PDF page'} ${esc(hit.page)} | Section pages ${esc(hit.section_page)}-${esc(hit.section_page_end)}</p><blockquote style="white-space:pre-wrap;overflow-wrap:anywhere">${hit.omitted_before ? '[...] ' : ''}${esc(hit.snippet)}${hit.omitted_after ? ' [...]' : ''}</blockquote><p class="muted">Extracted text excerpt, spacing normalized. Not a clinical recommendation.</p>${hit.openable === false ? '' : `<button data-local-ref-open="${i}">Open original physical page ${esc(hit.page)}</button>`}</article>`).join('') : '<p>No matching passages. No clinical conclusion can be drawn from this.</p>');
}
document.addEventListener('click', async event => {
  const el=event.target.closest('[data-local-ref-pick],[data-local-ref-search],[data-local-ref-open]');
  if (!el || !['report_editor','settings'].includes(page)) return;
  const status=$('local-ref-results');
  try {
    if (el.hasAttribute('data-local-ref-pick')) {
      const result=await window.hmr.pickLocalReference($('local-ref-edition').value);
      if (!result.cancelled) {localReferenceHits=[];if(typeof invalidateEvidenceReferences==='function')invalidateEvidenceReferences('Local reference changed. Refresh saved-evidence matches.');status.textContent='Registered private local PDF: '+result.edition+'. Search to find source passages.';}
    } else if (el.hasAttribute('data-local-ref-search')) {
      const query=$('local-ref-query').value.trim();
      if (!query) {status.textContent='Enter reference search words.';return;}
      const result=await window.hmr.api('GET','/api/reference/search?q='+encodeURIComponent(query));
      localReferenceHits=result.results;status.innerHTML=localReferenceHtml(result);
    } else {
      const hit=localReferenceHits[Number(el.dataset.localRefOpen)];
      if (!hit) throw Error('Search again to recover the citation');
      await window.hmr.openLocalReference(hit.pdf_sha256,hit.page);
    }
  } catch(error) {status.textContent=error.message;}
});
