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
  reportSaveStatus = 'All changes saved',
  reportSuggestions = [],
  reportGaps = [],
  reportSuggestionMessage = '',
  reportAdded = new Set(),
  reportDismissed = new Set(),
  reportLetterOpen = false,
  reportDetailsOpen = true;
const reportSaver = H.autosaver({
  getRecord: () => reportRecord,
  getId: () => reportId,
  draftKey: () => `report:${reportId}`,
  endpoint: (id, record) => hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report`, record),
  status: (message) => {
    reportSaveStatus = message.startsWith('Saved ') ? 'All changes saved' : message === 'Not saved' ? 'Unsaved changes' : message;
    if ($('report-status')) $('report-status').textContent = reportSaveStatus;
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
async function loadSuggestions() {
  const id = reportId;
  reportSuggestionMessage = 'Loading suggestions...';
  if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
  try {
    const data = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/suggestions`);
    if (id !== reportId || page !== 'report_editor') return;
    reportSuggestions = data.suggestions || [];
    reportGaps = data.context_gaps || [];
    reportSuggestionMessage = reportSuggestions.length ? '' : 'No suggestions for this patient yet.';
  } catch (error) {
    if (id !== reportId || page !== 'report_editor') return;
    reportSuggestions = [];
    reportGaps = [];
    reportSuggestionMessage =
      error.status === 404 || /404|not found/i.test(String(error.message))
        ? 'Suggestions are not available yet (engine needs updating)'
        : errorText(error);
  }
  if ($('suggestions')) $('suggestions').innerHTML = suggestionsHtml();
}
function suggestionsHtml() {
  return `${reportGaps.length ? (reportGaps.every(gap => typeof gap === 'string' && gap.trim()) ? `<ul class="muted">${reportGaps.map(gap => `<li>${esc(gap.replaceAll('_', ' '))}</li>`).join('')}</ul>` : '<p class="muted">Add interview notes or confirm the medicines to get suggestions.</p>') : ''}${reportSuggestionMessage ? `<p class="muted">${esc(reportSuggestionMessage)}</p>` : ''}${reportSuggestions.map((item, i) => (reportDismissed.has(i) ? '' : `<article class="card helper-card"><span class="source-chip">${esc(H.sourceLabel(item.source))}</span><h3>${esc(item.title)}</h3>${item.why?.length ? `<ul>${item.why.map((why) => `<li>${esc(why)}</li>`).join('')}</ul>` : ''}${item.missing?.length ? `<p>Check first: ${esc(item.missing.join(', '))}</p>` : ''}${item.brainstorm ? `<details><summary>Brainstorm V2 - ${esc(item.brainstorm.title)} (p.${esc(item.brainstorm.page)})</summary><p>${esc(item.brainstorm.snippet)}</p><button data-suggestion-copy="${i}">Copy</button></details>` : ''}<div class="actions"><button data-suggestion-add="${i}" ${reportAdded.has(i) ? 'disabled' : ''}>${reportAdded.has(i) ? 'Added' : 'Add to findings'}</button><button data-suggestion-dismiss="${i}">Dismiss</button></div></article>`)).join('')}`;
}
function reportField(key, label, multiline = true) {
  const review = reportRecord.needs_review?.includes(key)
    ? `<small data-report-review="${esc(key)}">Template text &#8212; rewrite before building</small>`
    : '';
  const input = multiline
    ? `<textarea data-field="${esc(key)}">${esc(reportRecord[key] || '')}</textarea>`
    : `<input data-field="${esc(key)}" value="${esc(H.date(reportRecord[key] || ''))}">`;
  return `<label>${esc(label)} ${review}${input}</label>`;
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
    .join('');
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
          `<div class="report-table"><h3>${esc({ meds: 'Medicines', otc: 'OTC', ceased: 'Ceased medicines', path: 'Pathology' }[key])}</h3>${key === 'path' ? reportField('path_date', 'Pathology date', false) : ''}${H.tableInput(key, key, columns, reportRecord[key], 'report')}</div>`,
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
          .join('')}</article>`,
    )
    .join('');
  const file = (reportDetail.files?.folder || []).find((f) => /^mims interactions.*\.txt$/i.test(f));
  const outputName = String(reportRecord.out || '')
    .split(/[\\/]/)
    .pop();
  $('screen').innerHTML =
    `<div class="report-top"><button data-page="reports">Back to reports</button><div><strong>${esc(reportDetail.name || reportRecord.name)}</strong><span class="muted"> &middot; ${esc(reportDetail.gp || String(reportRecord.doctor || '').split('\n')[0] || 'GP not set')}</span><br><small class="muted">${esc(outputName)}</small></div><div class="report-dates">${reportField('assess_date', 'Assessment date (DD/MM/YYYY)', false)}${reportField('report_date', 'Report date (DD/MM/YYYY)', false)}</div><span id="report-status" role="status">${esc(reportSaveStatus)}</span><div class="actions"><button data-report-save>Save</button><button data-report-build="word" ${!reportRecord.issues.length ? 'disabled' : ''}>Build Word</button><button class="primary" data-report-build="pdf" ${!reportRecord.issues.length ? 'disabled' : ''}>Build Word + PDF</button></div></div>${H.showInterviewRefresh(reportRecord, reportDetail) || reportRecord.pathology_newer ? `<div class="report-refresh" role="status"><span>${esc(reportRecord.pathology_newer ? 'Verified pathology has changed since this report was prepared. Refresh and re-review the report before building.' : 'The interview was changed after this report was started.')}</span><button data-report-refresh>Refresh report from current interview and pathology</button></div>` : ''}<div class="report-layout"><div class="report-main"><section class="report-findings"><h2>Findings</h2><p class="muted">${reportRecord.issues.length} findings &middot; about 4-8</p>${findings}<div class="actions"><button data-finding-add>Add finding</button>${reportUndo ? '<button data-finding-undo>Undo deletion</button>' : ''}</div></section><details class="interview-section report-disclosure" id="report-letter" ${reportLetterOpen ? 'open' : ''}><summary>Letter wording</summary><div class="report-fields">${letter}</div></details><details class="interview-section report-disclosure" id="report-details" ${reportDetailsOpen ? 'open' : ''}><summary>Patient details in the report</summary><div class="report-fields">${details}</div></details></div><aside class="report-sidebar"><section><div class="helper-heading"><h2>Suggestions for this patient</h2><button data-suggestions-reload>Reload</button></div><div id="suggestions" role="status">${suggestionsHtml()}</div></section><section><h2>Find in library</h2><label>Search<input id="library-search" type="search" value="${esc(reportQuery)}"></label><div id="library-results" role="status">${libraryResultsHtml()}</div></section>${reportAi ? `<section><h2>AI assist (optional)</h2><p>${esc(reportAgent)}</p><button data-report-assist>Draft with AI</button>${reportDraft ? '<div class="actions"><button data-report-load="all">Load AI draft</button><button data-report-load="findings">Take findings only</button></div>' : ''}${file ? `<p>${esc(file)} <button data-open-interactions="${esc(file)}">Open</button></p>` : ''}<pre id="report-output" role="status">${esc(reportOutput)}</pre></section>` : ''}</aside></div>`;
  document.querySelectorAll('.report-layout textarea').forEach(H.growTextarea);
  $('report-letter').addEventListener('toggle', (event) => {
    reportLetterOpen = event.target.open;
  });
  $('report-details').addEventListener('toggle', (event) => {
    reportDetailsOpen = event.target.open;
  });
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
  if (el.tagName === 'TEXTAREA') H.growTextarea(el);
  if (el.dataset.issue !== undefined) reportRecord.issues[Number(el.dataset.issue)][el.dataset.prop] = el.value;
  else if (el.dataset.field) {
    const key = el.dataset.field;
    if (el.dataset.row !== undefined) reportRecord[key][Number(el.dataset.row)][Number(el.dataset.col)] = el.value;
    else reportRecord[key] = el.value;
    if (reportRecord.needs_review) reportRecord.needs_review = H.reviewed(reportRecord.needs_review, key);
    document.querySelector(`[data-report-review="${key}"]`)?.remove();
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
    if (job === 'report_build' && result.state !== 'done') showBuildError(result.output || 'Report build failed');
    return result.state === 'done';
  } catch (error) {
    reportOutput = errorText(error);
    if (job === 'report_build') showBuildError(reportOutput);
    if ($('report-output')) $('report-output').textContent = reportOutput;
    return false;
  }
}
function showBuildError(message) {
  const match = String(message).match(/Review placeholder fields:\s*([^\r\n]+)/i);
  if (!match) { alert(message); return; }
  const labels = { reason: 'Reason for referral', intro: 'Introduction', thanks: 'Thanks', followup: 'Follow-up' };
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
  if (await reportSaver.save(true)) await reportJob('report_build', { pdf });
}
async function reportEditorClick(b) {
  if (page !== 'report_editor' || !reportRecord) return false;
  const d = b.dataset;
  if (d.reportRefresh !== undefined) {
    if (!confirm("This replaces the report's conditions, allergies, observations, medicine tables and pathology with the current interview. Your findings and letter text are kept. A backup of the current report is saved.")) return true;
    const id = reportId, screen = $('screen');
    screen.inert = true;
    try {
      if (!(await reportSaver.save())) return true;
      await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/report/refresh`);
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
    const index = Number(d.suggestionAdd);
    if (!reportAdded.has(index) && reportSuggestions[index]) {
      reportRecord.issues.push(H.findingFromResult(reportSuggestions[index]));
      reportAdded.add(index);
      reportSaver.changed();
      renderReport();
    }
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
