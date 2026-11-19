const checkedPatients = new Set();
let shownPatients = [];
let bulkExpanded = false;
let offerDraft = null, offerPatient = null, offerStatus = '';
let patientSort = 'urgency', appointmentRange = 'all';
function appointmentBounds(range, today = new Date()) {
  if (range === 'all') return null;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const end = new Date(start);
  if (range === 'week') { start.setDate(start.getDate() - (start.getDay() + 6) % 7); end.setTime(start.getTime()); end.setDate(end.getDate() + 6); }
  if (range === 'month') { start.setDate(1); end.setMonth(end.getMonth() + 1, 0); }
  return [localDate(start), localDate(end)];
}
function patientSortCompare(a, b) {
  const name = p => String(p.name || '').trim().replace(/^(?:(?:mr|mrs|ms|miss|dr|prof)\.?\s+)+/i, '').split(/\s+/).filter(Boolean);
  const compare = (x, y) => String(x || '').localeCompare(String(y || ''), undefined, { sensitivity: 'base', numeric: true });
  const an = name(a), bn = name(b);
  const nameOrder = compare(an.join(' '), bn.join(' ')) || compare(a.id, b.id);
  if (patientSort === 'first') return compare(an[0], bn[0]) || nameOrder;
  if (patientSort === 'last') return compare(an.at(-1), bn.at(-1)) || nameOrder;
  if (patientSort === 'referral' || patientSort === 'appointment') {
    const field = patientSort === 'referral' ? 'referral_date' : 'visit_date';
    const ad = /^\d{4}-\d{2}-\d{2}$/.test(a[field] || '') ? a[field] : '';
    const bd = /^\d{4}-\d{2}-\d{2}$/.test(b[field] || '') ? b[field] : '';
    if (!ad || !bd) return Number(!ad) - Number(!bd) || nameOrder;
    return (patientSort === 'referral' ? bd.localeCompare(ad) : ad.localeCompare(bd)) ||
      (patientSort === 'appointment' ? String(a.visit_time || '99:99').localeCompare(String(b.visit_time || '99:99')) : 0) || nameOrder;
  }
  return H.urgencySort(a, b) || nameOrder;
}
function passedOffer(p, now = new Date()) {
  return p.state === 'offered' && !!p.visit_date && new Date(`${p.visit_date}T${p.visit_time || '00:00'}`) < now;
}
function patientInGroup(p, g) {
  const groups = { Booking: ['intake', 'booking'], Ready: ['ready'], Report: ['report'], Claim: ['claim'], 'Follow-up': ['followup', 'done'], 'On hold': ['hold'], 'Declined / expired': ['declined', 'expired'], Archived: ['archived'] };
  return g === 'All active' ? p.stage !== 'archived' : (groups[g] || []).includes(p.stage);
}
function patientShell() {
  $('screen').innerHTML =
    `<div class="patient-layout"><div class="patient-list-pane"><label class="search">Search patients<input id="search" placeholder="Name, suburb, GP or phone"></label>
    <div class="actions"><label>Sort by <select id="patient-sort"><option value="urgency">Priority</option><option value="first">First name</option><option value="last">Last name</option><option value="referral">Referral date (newest)</option><option value="appointment">Appointment date</option></select></label><label>Appointments <select id="appointment-range"><option value="all">All appointments</option><option value="today">Today</option><option value="week">This week</option><option value="month">This month</option></select></label></div>
    <div id="chips" class="chips"></div><div id="bulk"></div><div id="queue-message" role="status" aria-live="polite">${esc(H.runStatusText(runMessage, runTasks))}</div><p id="patient-selection-error" class="error" role="alert" hidden></p><div class="actions patient-layout-actions"><button data-patient-layout="list">Maximise list</button><button data-patient-layout="patient">Maximise patient</button><button data-patient-layout="split">Restore split</button></div><div id="patient-list"></div></div>
    <div id="patient-divider" role="separator" tabindex="0" aria-label="Resize patient list" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75"></div><div id="detail" class="detail" hidden></div></div>`;
  const divider = $('patient-divider');
  divider.addEventListener('keydown', e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); resizePatientPane(patientWidth + (e.key === 'ArrowLeft' ? -5 : 5)); } });
  divider.addEventListener('pointerdown', e => {
    e.preventDefault(); divider.setPointerCapture(e.pointerId);
    const move = ev => { const rect = divider.parentElement.getBoundingClientRect(); resizePatientPane((ev.clientX - rect.left) / rect.width * 100); };
    const end = () => { divider.removeEventListener('pointermove', move); divider.removeEventListener('pointerup', end); divider.removeEventListener('pointercancel', end); };
    divider.addEventListener('pointermove', move); divider.addEventListener('pointerup', end); divider.addEventListener('pointercancel', end);
  });
  setPatientLayout(patientLayout);
  $('patient-sort').value = patientSort;
  $('appointment-range').value = appointmentRange;
  $('patient-sort').addEventListener('change', e => { patientSort = e.target.value; renderPatients(); });
  $('appointment-range').addEventListener('change', e => { appointmentRange = e.target.value; renderPatients(); });
  $('search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderPatients, 250);
  });
}
function renderPatients() {
  if (!$('search')) return;
  const q = $('search').value.toLowerCase();
  const bounds = appointmentBounds(appointmentRange);
  const filtered = patients.filter((p) =>
    [p.name, p.suburb, p.gp, p.phone].some((v) =>
      String(v || '')
        .toLowerCase()
        .includes(q),
    ) && (!bounds || (/^\d{4}-\d{2}-\d{2}$/.test(p.visit_date || '') && p.visit_date >= bounds[0] && p.visit_date <= bounds[1])),
  );
  const groups = page === 'to_book' ? ['All active'] : ['All active', 'Booking', 'Ready', 'Report', 'Claim', 'Follow-up', 'On hold', 'Declined / expired', 'Archived'];
  if (page === 'to_book') filter = 'All active';
  $('chips').innerHTML = groups
    .map(
      (g) => `<button data-filter="${g}" class="${filter === g ? 'active' : ''}">
    ${g} (${filtered.filter((p) => patientInGroup(p, g)).length})</button>`,
    )
    .join('');
  const rows = filtered.filter((p) => patientInGroup(p, filter)).sort(patientSortCompare);
  shownPatients = rows.map((p) => Number(p.id));
  $('detail').hidden = !selected;
  if (typeof document !== 'undefined') document.querySelector('.patient-layout')?.classList.toggle('open', !!selected);
  setPatientLayout(patientLayout);
  const bulk = $('bulk');
  const existingDisclosure = bulk.querySelector?.('details');
  if (existingDisclosure) bulkExpanded = existingDisclosure.open;
  if (page !== 'to_book' && checkedPatients.size) {
    const count = `<strong>Patients: ${checkedPatients.size} selected</strong> <strong id="steps-count">Steps: ${selectedSteps(H.bulkSteps).length} ticked</strong>`;
    const controls = `${stepCheckboxes(H.bulkSteps)}<button data-bulk-step ${!runPending && selectedSteps(H.bulkSteps).length ? '' : 'disabled'}>Run ticked steps</button>
      <button data-bulk-flow ${runPending ? 'disabled' : ''}>Run full flow</button><button data-bulk-clear>Clear</button>`;
    bulk.innerHTML = selected ? `<details class="bulk-disclosure card" ${bulkExpanded ? 'open' : ''}><summary>${count}</summary><div class="actions bulk-actions">${controls}</div></details>`
      : `<div class="actions bulk-actions card">${count}${controls}</div>`;
  } else bulk.innerHTML = '';
  bulk.querySelector?.('details')?.addEventListener('toggle', (event) => { bulkExpanded = event.currentTarget.open; });
  $('patient-list').innerHTML =
    `<p class="muted">${rows.length} patient${rows.length === 1 ? '' : 's'}</p><table><thead><tr><th><input type="checkbox" aria-label="Select all shown" data-select-all
    ${rows.length && rows.every((p) => checkedPatients.has(Number(p.id))) ? 'checked' : ''}></th><th class="patient-name">Name</th>${selected ? '' : '<th class="patient-gp">GP</th>'}<th>Visit</th>${patientSort === 'referral' ? '<th>Referral</th>' : ''}${selected ? '' : '<th>Status</th>'}<th>Next step</th></tr></thead>
    <tbody>${rows
      .map(
        (
          p,
        ) => `<tr data-patient="${esc(p.id)}" tabindex="0"${String(p.id) === String(selected) ? ' aria-current="true"' : ''}><td><input type="checkbox" data-select-patient="${esc(p.id)}" aria-label="Select ${esc(p.name)}"
    ${checkedPatients.has(Number(p.id)) ? 'checked' : ''}></td><td class="patient-name"><strong>${esc(p.name)}</strong>
    <div class="muted">${esc(H.suburb(p.suburb))}</div>${selected ? (() => { const t = (typeof runTasks !== 'undefined' ? runTasks : []).find(x => Number(x.patient_id) === Number(p.id)); return t ? `<button data-patient-activity="${esc(p.id)}">${esc(H.stepLabel(t.step))}: ${esc(t.state)}</button>` : ''; })() : ''}</td>${selected ? '' : `<td class="patient-gp">${esc(p.gp || '')}</td>`}
    <td class="nowrap">${esc(date(p.visit_date))} ${esc(p.visit_time || '')}</td>${patientSort === 'referral' ? `<td class="nowrap">${esc(date(p.referral_date))}</td>` : ''}
    ${selected ? '' : `<td><span class="status-chip stage-${H.stageClass(p.stage)}">${H.stageText(p)}</span>${(() => {
      const t = (typeof runTasks !== 'undefined' ? runTasks : []).find((x) => Number(x.patient_id) === Number(p.id));
      return t ? ` <span class="task-chip state-${esc(t.state)}"><button data-patient-activity="${esc(p.id)}">${esc(H.stepLabel(t.step))}: ${esc(t.state)}</button></span>` : '';
    })()}</td>`}
    <td>${H.hasNextStep(p) ? `<button data-patient="${esc(p.id)}">${esc(H.stepLabel(p.next_step))}</button>` : ''}</td></tr>`,
      )
      .join('')}</tbody></table>${rows.length ? '' : '<p class="empty">No patients match these filters.</p>'}`;
}
function timelineStrip(m, today = localDate(new Date())) {
  const items = [['Referral', m.referral_date], ['First contact', m.first_contact],
    ['Confirmed', m.confirmed], ['Declined', m.declined], ['Visit', m.visit],
    ['Report sent', m.report_sent], ['Claimed', m.claimed],
    ...[1, 2].flatMap(n => ['due', 'done', 'claimed'].map(stage => [`Follow-up ${n} ${stage}`, m[`followup${n}_${stage}`], stage === 'due']))];
  return `<div class="milestones">${items.map(([label, value, due]) => `<div class="milestone ${!value ? 'empty' : due && value !== 'unknown' && String(value).slice(0, 10) < today ? 'overdue' : ''}"><strong>${esc(label)}</strong><span>${value === 'unknown' ? 'Yes, date unknown' : value ? esc(date(value)) : '&ndash;'}</span></div>`).join('')}</div>`;
}
const primaryOrder = ['book_phone', 'decline_phone', 'visited', 'move', 'report_sent', 'claimed', 'call'];
const followupActions = ['followup1', 'followup2', 'followup1_claimed', 'followup2_claimed'];
function actionButton(a, primary) {
  return `<button data-action="${a}"${primary ? ' class="primary"' : ''}>${actionLabels[a]}</button>`;
}
function followupRows(p, m, actions, today = localDate(new Date())) {
  const value = (v) => (v === 'unknown' ? 'date unknown' : v ? esc(date(v)) : '&ndash;');
  return [1, 2].map((n) => {
    const due = m[`followup${n}_due`], done = m[`followup${n}_done`];
    const overdue = due && due !== 'unknown' && !done && String(due).slice(0, 10) < today;
    return `<div class="followup-row"><div><strong>Follow-up ${n}</strong><div class="muted"><span class="${overdue ? 'overdue-text' : ''}">Due ${value(due)}${overdue ? ' (overdue)' : ''}</span> &middot; Done ${value(done)} &middot; Claimed ${value(m[`followup${n}_claimed`])}</div></div>
    <div class="actions"><button ${n === 1 && !actions.includes('archive') ? 'class="primary"' : ''} data-open-followup="${n}" data-id="${esc(p.id)}">Follow-up ${n} form</button>${actions.filter((a) => a.startsWith(`followup${n}`)).map((a) => actionButton(a)).join('')}</div></div>`;
  }).join('');
}
function availableActions(p, milestones = {}) { return H.stageActions(p, milestones); }
let fullPatientView = false;
let patientLayout = 'split';
let patientWidth = 50;
let patientRequest = 0;
function setPatientLayout(mode) {
  patientLayout = mode;
  fullPatientView = mode === 'patient';
  const layout = typeof document !== 'undefined' ? document.querySelector('.patient-layout') : null;
  if (!layout) return;
  layout.classList.toggle('full-view', mode === 'patient');
  layout.classList.toggle('list-view', mode === 'list');
  layout.style.setProperty('--patient-list-width', `${patientWidth}%`);
  const divider = $('patient-divider');
  if (divider) { divider.setAttribute('aria-valuenow', String(patientWidth)); divider.hidden = !selected || mode !== 'split'; }
  document.querySelectorAll('[data-patient-layout]').forEach(b => { b.hidden = !selected || b.dataset.patientLayout === mode; });
}
function resizePatientPane(value) {
  patientWidth = Math.max(25, Math.min(75, value));
  setPatientLayout(patientLayout);
}
function selectPatientTab(tab) {
  detailTab = tab;
  const nextAction = $('patient-next-action'); if (nextAction) nextAction.hidden = tab !== 'Overview';
  const offer = $('offer-section'); if (offer) offer.hidden = tab !== 'Conversation' || offer.dataset.available !== 'true';
  const detail = $('detail');
  if (!detail) return;
  detail.querySelectorAll('[data-tab]').forEach(b => { b.classList.toggle('active', b.dataset.tab === tab); b.setAttribute('aria-selected', String(b.dataset.tab === tab)); });
  for (const name of ['Overview', 'Conversation', 'Activity', 'Files']) {
    const section = detail.querySelector(`.${name.toLowerCase()}-view`);
    if (section) section.hidden = name !== tab;
  }
}

async function reselectActivePatient(id, background = true) {
  const status = $('patient-selection-error');
  if (status) { status.hidden = true; status.textContent = ''; }
  try {
    return await showPatient(id, undefined, background);
  } catch (error) {
    selected = null;
    renderPatients();
    if (status) {
      status.textContent = 'Previously selected patient could not be opened (' + errorText(error) + '). Choose a patient from the list to continue.';
      status.hidden = false;
    }
    return false;
  }
}

async function openPatientWorkspace(id, tab = 'Overview', layout = 'patient') {
  if (!['patients', 'to_book'].includes(page)) {
    await navigate('patients');
    if (page !== 'patients') return { cancelled: true };
  }
  if (['patients', 'to_book'].includes(page) && !$('detail')) { patientShell(); renderPatients(); }
  if (selected === String(id) && $('detail') && !$('detail').hidden) {
    selectPatientTab(tab); setPatientLayout(layout);
    return { ok: true };
  }
  if (formOpen && !confirm('Switch patient and discard unsaved changes?')) return { cancelled: true };
  formOpen = false;
  detailTab = tab;
  const shown = await showPatient(id);
  if (!shown || selected !== String(id) || !['patients', 'to_book'].includes(page)) return { cancelled: true };
  setPatientLayout(layout);
  return { ok: true };
}
async function showPatient(id, action, background = false) {
  if (formOpen && selected !== String(id)) { if (!confirm('Switch patient and discard unsaved changes?')) return false; formOpen = false; }
  if (action && action !== 'offer_new') detailTab = 'Overview';
  const request = ++patientRequest, startedPage = typeof page === 'undefined' ? null : page;
  const startedNav = typeof navToken === 'undefined' ? null : navToken;
  const changedPatient = selected !== String(id);
  selected = String(id);
  renderPatients();
  if (changedPatient && $('detail')) $('detail').innerHTML = '<p role="status">Loading patient...</p>';
  const p = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}`);
  if (!$('detail') || selected !== String(id) || request !== patientRequest || (typeof page !== 'undefined' && page !== startedPage) || (typeof navToken !== 'undefined' && navToken !== startedNav)) return false;
  const timeline = await hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/timeline`);
  if (!$('detail') || selected !== String(id) || request !== patientRequest || (typeof page !== 'undefined' && page !== startedPage) || (typeof navToken !== 'undefined' && navToken !== startedNav)) return false;
  if (offerPatient !== String(id)) { offerPatient = String(id); offerDraft = null; offerStatus = ''; }
  const [board, agents, reportCurrency] = await Promise.all([
    hmr.api('GET', '/api/messages/board').catch(() => ({})),
    hmr.api('GET', '/api/agents').catch(() => ({})),
    ['visited', 'report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state)
      ? hmr.api('GET', `/api/patients/${encodeURIComponent(id)}/report-status`).catch(() => null)
      : Promise.resolve(null),
  ]);
  if (!$('detail') || selected !== String(id) || request !== patientRequest || (typeof page !== 'undefined' && page !== startedPage) || (typeof navToken !== 'undefined' && navToken !== startedNav) || formOpen || (background && $('detail').querySelector?.('details[open]'))) return false;
  const milestones = timeline.milestones || {};
  const canChange = action !== 'offer_new' && !!p.change_kinds?.length;
  const phone = String(p.phone || '').replace(/[^\d+]/g, '');
  const reportWorkflow = H.reportWorkflowStatus(p.state, (p.steps || []).find((step) => step.name === 'report_build'), reportCurrency);
  const visibleSteps = (p.steps || []).map((step) => step.name === 'report_build' ? { ...step, ...reportWorkflow.build } : step);
  const pathway = H.patientPathway ? H.patientPathway(p, milestones, visibleSteps) : [];
  const files = (list) => (list?.length ? list.map((x) => `<li>${esc(x)}</li>`).join('') : '<li>None</li>');

  const actions = availableActions(p, milestones);
  const more = ['note', 'update', ...(p.can_undo ? ['undo_stage'] : [])];
  const shownActions = actions.filter(a => !followupActions.includes(a));
  const listPatient = typeof patients !== 'undefined' ? patients.find(item => String(item.id) === String(p.id)) : null;
  const proposedNext = String(p.next_step || listPatient?.next_step || p.stage_step || '').toLowerCase().replaceAll('_', ' ');
  const followupNext = p.followups?.next_action;
  const next = proposedNext === 'sign off' && !reportWorkflow.canSign && ['visited', 'report_drafted'].includes(p.state)
    ? 'build report' : proposedNext;
  const aliases = {
    'collect pathology': 'pathology',
    'read reply': 'conversation',
    'offer a new time': 'offer',
    'wait for reply': 'waiting',
    'visit': 'visited',
    'record the visit': 'visited',
    'add findings': 'edit_report',
    'sign off': 'signed_off',
    'send report': 'report_sent',
    'follow-up due': followupNext || 'followups',
    'make interview sheet': 'interview',
    'prepare interview sheet': 'interview',
    'confirm medicines': 'medicines',
    'check interactions': 'interactions',
    'start report': 'report_start',
    'edit report': 'edit_report',
    'build report': 'build_report',
    'signed off': 'signed_off',
    'open claim': 'claim',
    'claim': 'claim',
    'mark claimed': 'claimed',
    'mark visited': 'visited',
    'record visit': 'visited',
    'open interview': 'interview',
    'offer a time': 'offer',
    'change the time': 'offer',
    'report sent': 'report_sent',
  };
  let primaryAction = aliases[next] || null;
  if (primaryAction && !['pathology', 'conversation', 'waiting', 'followups', ...followupActions].includes(primaryAction) && !shownActions.includes(primaryAction)
    && !(primaryAction === 'build_report' && ['visited', 'report_drafted'].includes(p.state))) primaryAction = null;
  if (!primaryAction && !next) {
    if (p.visit_date && shownActions.includes('visited')) primaryAction = 'visited';
    else if (shownActions.includes('medicines')) primaryAction = 'medicines';
    else if (shownActions.includes('interview')) primaryAction = 'interview';
    else if (shownActions.includes('report_start')) primaryAction = 'report_start';
    else primaryAction = (canChange ? shownActions.find((a) => a !== 'offer') : null) || shownActions[0];
  }
  const status = H.stageText(p);
  const steps = Object.fromEntries((p.steps || []).map((step) => [step.name, step]));
  const aiInfo = (name) => {
    const agentName = agents.per_step?.[name] || agents.default;
    const agent = (agents.agents || []).find(a => a.name === agentName && a.enabled);
    const step = steps[name];
    return { enabled: !!agent && !!step && !step.ai_off && (step.ready || step.done), label: agent ? `Agent: ${agent.name}` : 'No enabled agent selected', reason: step?.ai_off ? 'AI is off in settings' : !agent ? 'No enabled agent selected' : step?.reason || 'Not ready' };
  };
  const interviewAI = aiInfo('interview_assist'), reportAI = aiInfo('report_draft');
  const buildDone = reportWorkflow.build.done;
  const isSigned = ['signed_off', 'sent', 'claimed'].includes(p.state);
  const stageButton = (a) => {
    if (a === 'pathology') return `<button data-run-task="pathology" data-patient-id="${esc(p.id)}">Collect pathology</button>`;
    if (a === 'conversation') return '<button data-tab="Conversation">Read reply</button>';
    if (a === 'waiting') return '<button data-tab="Conversation">Waiting for reply - open conversation</button>';
    if (a === 'followups') return '<button data-tab="Activity">Open follow-ups</button>';
    if (followupActions.includes(a)) return actionButton(a);
    if (a === 'offer') return `<button data-show-offer>${canChange ? 'Change the time' : 'Offer a time'}</button>`;
    if (a === 'interview') return `<button data-open-interview="${esc(p.id)}">Open interview</button>`;
    if (a === 'medicines') return `<button data-medicines="${esc(p.id)}">Check medicines for interaction check</button>`;
    if (a === 'interactions') return `<button data-report-step="interactions" data-id="${esc(p.id)}">Check interactions</button>`;
    if (a === 'report_start') {
      const ready = !!steps.report_start?.ready || !!steps.report_start?.done;
      return `<button data-report-step="report_start" data-id="${esc(p.id)}" ${ready ? '' : `disabled title="${esc(steps.report_start?.reason || 'Prerequisites not met')}"`}>Start report</button>`;
    }
    if (a === 'edit_report') return `<button data-report-open="${esc(p.id)}">Edit report</button>`;
    if (a === 'build_report') {
      const ready = reportWorkflow.build.ready;
      const why = reportWorkflow.build.reason || 'Prerequisites not met';
      return `<span class="action-with-reason"><button data-report-open="${esc(p.id)}" data-build="build" ${ready ? '' : `disabled title="${esc(why)}"`}>Build</button>${ready ? '' : `<small class="action-reason">${esc(why)}</small>`}</span>`;
    }
    if (a === 'signed_off') {
      const ready = reportWorkflow.canSign;
      const why = reportWorkflow.signReason || 'Word report must be built first';
      const blocked = !ready && !isSigned;
      return `<span class="action-with-reason"><button data-sign-off="${esc(p.id)}" ${ready && !isSigned ? '' : 'disabled'}${blocked ? ` title="${esc(why)}"` : ''}>${isSigned ? 'Signed off &#10003; Done' : 'Signed off'}</button>${blocked ? `<small class="action-reason">${esc(why)}</small>` : ''}</span>`;
    }
    if (a === 'report_sent') {
      return `<span class="action-with-reason"><button data-action="report_sent" ${isSigned ? '' : 'disabled title="Report must be signed off first"'}>${actionLabels.report_sent}</button>${isSigned ? '' : '<small class="action-reason">Report must be signed off first</small>'}</span>`;
    }
    if (a === 'claim') return `<button data-claim-run="${esc(p.id)}">Open claim</button>`;
    return actionButton(a);
  };

  const isConversationTab = ['Conversation', 'Messages'].includes(detailTab);
  const isActivityTab = ['Activity', 'Timeline'].includes(detailTab);
  const isFilesTab = detailTab === 'Files';
  const isOverviewTab = !isConversationTab && !isActivityTab && !isFilesTab;

  const convCount = (p.messages || []).length;
  const actCount = (timeline.entries || []).length;
  const filesCount = (p.files?.folder?.length || 0) + (p.files?.pathology?.length || 0);

  // Build Chronological Conversation thread
  const msgs = (p.messages || []).map((m) => {
    const isIncoming = ['in', 'incoming'].includes(m.direction);
    const isDraft = m.state === 'draft';
    const time = m.created_at || m.sent_at || m.time;
    return {
      id: m.id,
      time: time || '',
      direction: isIncoming ? 'inbound' : isDraft ? 'draft' : 'outbound',
      state: m.state || (isIncoming ? 'received' : 'sent'),
      kind: m.kind,
      body: m.body || '',
      warning: m.warning || (m.state === 'draft' && p.referral_expiry && p.referral_expiry < localDate(new Date()) ? 'Referral has expired.' : ''),
      patient_id: m.patient_id || p.id,
      raw: m,
    };
  });
  const timelineDecisions = (timeline.entries || [])
    .filter((e) => {
      const text = `${e.label || ''} ${e.detail || ''}`.toLowerCase();
      return e.kind !== 'message' && ['confirmed', 'declined', 'offer', 'sms', 'call', 'reply', 'visit booked'].some((k) => text.includes(k));
    })
    .map((e, idx) => ({
      id: `timeline-${idx}`,
      time: e.at || '',
      direction: 'decision',
      label: e.label || 'Decision',
      detail: e.detail || '',
      body: `${e.label || 'Decision'}: ${e.detail || ''}`,
      state: 'logged',
    }));
  const needsReply = new Set((board.needs_you || []).filter(m => ['in', 'incoming'].includes(m.direction)).map(m => String(m.id)));
  const sendBlocked = board.outbox_mode !== 'live' && !p.is_test;
  const thread = [...msgs, ...timelineDecisions];
  thread.sort((a, b) => String(a.time || '').localeCompare(String(b.time || '')));
  const days = {};
  for (const item of thread) {
    const day = item.time ? date(item.time) : 'Recent';
    (days[day] ||= []).push(item);
  }

  $('detail').innerHTML =
    `<div class="detail-head"><div>${fullPatientView ? `<button data-back-to-patients class="btn-back">&larr; Back to patients</button>` : ''}<h2>${esc(p.name)}</h2><span class="status-chip stage-${H.stageClass(p.stage)}">${status}</span><div class="chips">${H.flagWords(p).map(word => `<span class="status-chip">${esc(word)}</span>`).join('')}</div></div><div class="head-actions"><button data-patient-layout="patient">Maximise patient</button><button data-patient-layout="list">Maximise list</button><button data-patient-layout="split">Restore split</button><button class="detail-close" data-close-patient>Close</button></div></div>
    <dl class="detail-facts"><dt>Visit</dt><dd>${p.visit_date ? `${esc(date(p.visit_date))} ${esc(p.visit_time || '')}` : 'Not booked'}</dd>
    <dt>Address</dt><dd>${esc(H.displayAddress(p.address, p.suburb)) || '&ndash;'}</dd><dt>Phone</dt><dd>${phone ? `<a href="tel:${esc(phone)}">${esc(p.phone)}</a>` : '&ndash;'}</dd></dl>
    <section id="patient-next-action" class="panel-section" ${isOverviewTab ? '' : 'hidden'}><h3>Next action</h3>${next ? `<p>${esc(next)}</p>` : ''}<div class="actions">${primaryAction ? stageButton(primaryAction).replace('<button ', '<button class="primary" ') : `<span class="muted">${esc(H.nextActionHint(primaryAction, shownActions.length).text)}</span>`}${shownActions.filter(a => a !== primaryAction).length ? `<details${H.nextActionHint(primaryAction, shownActions.length).openOthers ? ' open' : ''}><summary>Other actions</summary><div class="actions">${shownActions.filter(a => a !== primaryAction).map(stageButton).join('')}</div></details>` : ''}</div>
    ${more.length ? `<details class="more-actions"><summary>More actions (${more.length})</summary><div class="actions">${more.map((a) => a === 'undo_stage' ? `<button data-action="undo_stage">Undo: ${esc(p.undo_label || 'last stage')}</button>` : actionButton(a)).join('')}</div></details>` : ''}
    <div id="action-area"></div><div id="medicines-${esc(p.id)}"></div><p id="report-message" role="status"></p></section>
    <div class="tabs" role="tablist">
      <button data-tab="Overview" class="${isOverviewTab ? 'active' : ''}">Overview</button>
      <button data-tab="Conversation" class="${isConversationTab ? 'active' : ''}">Conversation${convCount ? ` (${convCount})` : ''}</button>
      <button data-tab="Activity" class="${isActivityTab ? 'active' : ''}">Activity${actCount ? ` (${actCount})` : ''}</button>
      <button data-tab="Files" class="${isFilesTab ? 'active' : ''}">Files (${filesCount})</button>
    </div>
    <div class="overview-view" ${isOverviewTab ? '' : 'hidden'}>
      ${pathway.length ? `<div class="patient-pathway card"><h4>HMR Pathway</h4><div class="pathway-steps">${pathway.map((s) => `<div class="pathway-step ${s.completed ? 'is-completed' : s.current ? 'is-current' : ''}"><strong>${esc(s.title)}</strong><br><small>${s.completed ? '&#10003; Done' : esc(s.detail)}</small></div>`).join('')}</div></div>` : ''}
      ${reportCurrency ? H.reportStatusHtml(reportCurrency) : ['visited', 'report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state) ? '<p class="muted" role="status">Report currency could not be verified. Do not sign off until checked.</p>' : ''}
      <section class="panel-section"><h3>Automation & manual steps</h3>
        <div class="path-options">
          ${['ready', 'booking', 'intake'].includes(p.stage) ? `
            <div class="path-card"><strong>Pathology helper</strong><p class="muted">Runs browser script in My Health Record (script, not AI).</p><div class="actions"><button data-run-task="pathology" data-patient-id="${esc(p.id)}">Collect pathology (MHR script)</button><button data-action="pathology_outcome">Pathology by hand (Manual)</button></div></div>
            <div class="path-card"><strong>Interview sheet</strong><p class="muted">Prepare visit notes. Sheet is manual; AI assist is optional.</p><div class="actions"><button data-run-task="interview_sheet" data-patient-id="${esc(p.id)}">Make interview sheet (Manual)</button><button data-run-task="interview_assist" data-patient-id="${esc(p.id)}" ${interviewAI.enabled ? '' : `disabled title="${esc(interviewAI.reason)}"`}>Draft with AI (Optional)</button><small>${esc(interviewAI.enabled ? interviewAI.label : interviewAI.reason)}</small></div></div>
          ` : ''}
          ${['report', 'claim', 'followup', 'done'].includes(p.stage) ? `
            <div class="path-card"><strong>Interactions helper</strong><p class="muted">Runs browser script in eMIMS (script, not AI).</p><div class="actions"><button data-report-step="interactions" data-id="${esc(p.id)}">Check interactions (eMIMS script)</button><button data-action="interactions_manual">Interactions note (Manual)</button></div></div>
            <div class="path-card"><strong>Report draft</strong><p class="muted">Start report structure manually or draft findings with AI.</p><div class="actions"><button data-report-step="report_start" data-id="${esc(p.id)}" ${steps.report_start?.ready || steps.report_start?.done ? '' : 'disabled'}>Start report (Manual)</button><button data-run-task="report_draft" data-patient-id="${esc(p.id)}" ${reportAI.enabled ? '' : `disabled title="${esc(reportAI.reason)}"`}>Draft with AI (Optional)</button><small>${esc(reportAI.enabled ? reportAI.label : reportAI.reason)}</small></div></div>
          ` : ''}
        </div>
        ${(() => {
          const pTasks = ((p.tasks && p.tasks.length) ? p.tasks : (typeof runTasks !== 'undefined' ? runTasks.filter(t => Number(t.patient_id) === Number(p.id)) : [])).slice(0, 5);
          if (!pTasks.length) return '<p class="muted">No recent automation tasks for this patient.</p>';
          return `<h4>Recent tasks</h4><ul class="step-list">${pTasks.map(t => {
            const waitReason = t.waiting_for ? `Waiting for ${siteNames[t.waiting_for] || t.waiting_for}` : (t.reason || '');
            return `<li><span>${esc(H.stepLabel(t.step))}</span><span class="status-chip task-state state-${esc(t.state)}">${esc(t.state)}</span>${waitReason ? ` <small class="muted">(${esc(waitReason)})</small>` : ''}${t.state === 'failed' ? ` <button data-task-retry="${esc(t.id)}">Retry</button>` : ''}${['queued', 'waiting'].includes(t.state) ? ` <button data-task-cancel="${esc(t.id)}">Cancel</button>` : ''}</li>`;
          }).join('')}</ul>`;
        })()}
      </section>
      ${['report', 'claim', 'followup', 'done'].includes(p.stage) ? `<section class="panel-section"><h3>Report steps</h3><ul class="step-list">${
        visibleSteps
          .map(
            (step) =>
              `<li><span>${esc(H.steps[step.name] || step.name.replaceAll('_', ' '))}</span><span class="step-state ${step.done ? 'is-done' : step.ready ? 'is-ready' : ''}">${step.done ? 'Done' : step.ready ? 'Ready' : 'Not ready'}</span>${step.name === 'report_build' && !step.done && reportWorkflow.build.reason ? `<small>${esc(reportWorkflow.build.reason)}</small>` : (!step.done && !step.ready && step.reason ? `<small>${esc(step.reason)}</small>` : '')}</li>`,
          )
          .join('') || '<li class="muted">No steps from the engine.</li>'
      }</ul></section>` : ''}
    </div>
    <div class="conversation-view" ${isConversationTab ? '' : 'hidden'}>
      <div class="conversation-thread" role="log" aria-label="Conversation history">
        ${Object.entries(days).map(([day, items]) => `
          <div class="day-divider"><span>${esc(day)}</span></div>
          ${items.map((item) => {
            const timeStr = item.time ? String(item.time).slice(11, 16) : '';
            if (item.direction === 'decision') {
              return `<div class="msg-bubble is-decision"><span class="msg-meta">${esc(item.label)} &middot; ${esc(timeStr)}</span><p>${esc(item.detail)}</p></div>`;
            }
            if (item.direction === 'inbound') {
              return `<div class="msg-bubble is-inbound">
                <span class="msg-meta">From ${esc(p.name)} &middot; ${esc(timeStr)}</span>
                <p>${esc(item.body)}</p>
                ${needsReply.has(String(item.id)) ? `<div class="actions"><strong>Resolve reply</strong>${[['yes', 'Confirm'], ['new_time', 'New time'], ['decline', 'Decline'], ['call', 'Call'], ['done', 'Done']].map(([val, lbl]) => `<button data-resolve="${val}" data-id="${esc(item.id)}" data-patient-id="${esc(p.id)}">${lbl}</button>`).join('')}</div>` : ''}
                <div id="resolve-confirm-${esc(item.id)}"></div><p class="error" id="resolve-error-${esc(item.id)}" role="alert"></p>

              </div>`;
            }
            if (item.direction === 'draft') {
              return `<div class="msg-bubble is-draft">
                <span class="msg-meta">Draft ${esc(item.kind || 'message')} &middot; ${esc(timeStr)}</span>
                ${item.warning ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(item.warning)}</p><label class="confirm-expired"><input type="checkbox" id="board-confirm-expired-${esc(item.id)}"> I confirm sending despite expired referral</label>` : ''}
                <p>${esc(item.body)}</p><div id="board-edit-${esc(item.id)}" hidden><label>Message<textarea id="board-body-${esc(item.id)}">${esc(item.body)}</textarea></label></div>
                <div class="actions"><button data-message-send="${esc(item.id)}" ${sendBlocked ? 'disabled title="Test mode: this patient cannot receive messages"' : ''}>Send</button><button data-message-edit="${esc(item.id)}">Edit</button><button data-message-discard="${esc(item.id)}">Discard</button></div><p class="error" id="board-error-${esc(item.id)}" role="alert"></p>
              </div>`;
            }
            return `<div class="msg-bubble is-outbound">
              <span class="msg-meta">Outbound &middot; ${esc(timeStr)} &middot; <span class="status-chip chip-${esc(item.state)}">${esc(item.state)}</span></span>
              <p>${esc(item.body)}</p>
            </div>`;
          }).join('')}
        `).join('')}
        ${!thread.length ? '<p class="muted">No messages in conversation yet.</p>' : ''}
      </div>
      ${messageComposer()}
    </div>
    <div class="activity-view" ${isActivityTab ? '' : 'hidden'}>
      ${timelineStrip(milestones)}
      ${(() => {
        const pTasks = ((p.tasks && p.tasks.length) ? p.tasks : (typeof runTasks !== 'undefined' ? runTasks.filter(t => Number(t.patient_id) === Number(p.id)) : []));
        if (!pTasks.length) return '';
        return `<section class="panel-section"><h4>Automation task history</h4><ul class="step-list">${pTasks.map(t => {
          const waitReason = t.waiting_for ? `Waiting for ${siteNames[t.waiting_for] || t.waiting_for}` : (t.reason || '');
          return `<li><span>${esc(H.stepLabel(t.step))}</span><span class="status-chip task-state state-${esc(t.state)}">${esc(t.state)}</span>${waitReason ? ` <small class="muted">(${esc(waitReason)})</small>` : ''}${t.state === 'failed' ? ` <button data-task-retry="${esc(t.id)}">Retry</button>` : ''}${['queued', 'waiting'].includes(t.state) ? ` <button data-task-cancel="${esc(t.id)}">Cancel</button>` : ''}</li>`;
        }).join('')}</ul></section>`;
      })()}
      <section class="panel-section"><h4>Timeline & audit log</h4>
        ${(timeline.entries || []).slice().sort((a, b) => String(b.at || '').localeCompare(String(a.at || ''))).map(e => `<div class="timeline"><strong>${esc(e.at_text || '')} ${esc(e.label || '')}</strong><div>${esc(e.detail || '')}</div></div>`).join('') || '<p class="muted">No timeline entries yet.</p>'}
      </section>
      ${['followup', 'done'].includes(p.stage) ? `<section class="panel-section"><h4>Follow-ups</h4>${followupRows(p, milestones, actions)}</section>` : ''}
    </div>
    <div class="files-view" ${isFilesTab ? '' : 'hidden'}>
      <h3>Folder</h3><ul>${files(p.files?.folder)}</ul>
      <h3>Pathology</h3><ul>${files(p.files?.pathology)}</ul>
    </div>
    <section class="panel-section" id="offer-section" data-available="${['intake', 'booking', 'ready'].includes(p.stage)}" ${!isConversationTab || !['intake', 'booking', 'ready'].includes(p.stage) ? 'hidden' : ''}>
    ${canChange ? `<details class="offer-details" ${action === 'offer_new' ? 'open' : ''}><summary>Appointment: Change the time</summary><p>Ask keeps current time unless patient replies YES. Have to change moves it now.</p>` : `<h3>Offer a new time</h3>`}
    <form id="offer-form"><div class="form"><label>Date<input id="offer-date" type="date" required ${offerDraft ? 'disabled' : ''}></label><label>Time<input id="offer-time" type="time" required ${offerDraft ? 'disabled' : ''}></label>${canChange ? `<button class="primary" value="change_request" ${offerDraft ? 'hidden' : ''}>Ask to change</button><button value="change" ${offerDraft ? 'hidden' : ''}>Have to change</button>` : `<button value="offer" ${offerDraft ? 'hidden' : ''}>Preview SMS</button>`}</div></form>
    ${offerDraft ? `
      ${offerDraft.warning ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(offerDraft.warning)}</p><label class="confirm-expired"><input type="checkbox" id="offer-confirm-expired"> I confirm sending this offer despite the expired referral</label>` : ''}
      <p class="offer-preview"><strong>${{ offer: 'Offer a new time', change_request: 'Ask to change', change: 'Have to change' }[offerDraft.kind]}</strong><br>${esc(offerDraft.body)}</p><div class="actions"><button id="offer-send" class="primary">Send SMS</button><button id="offer-discard">Discard</button></div>` : ''}
    <p id="offer-status" role="status">${esc(offerStatus)}</p><p id="offer-error" class="error" role="alert"></p>${canChange ? '</details>' : ''}</section>`;
  $('detail').hidden = false;
  setPatientLayout(patientLayout);
  $('detail').querySelector('[data-show-offer]')?.addEventListener('click', () => { selectPatientTab('Conversation'); $('offer-section').scrollIntoView(); });
  $('offer-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const draft = await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/messages`, {
        kind: button.value, date: $('offer-date').value, time: $('offer-time').value,
      });
      offerDraft = { ...draft, kind: button.value }; offerStatus = ''; formOpen = false;
      if (selected === String(id)) await showPatient(id);
      formOpen = true;
    } catch (error) { if (selected === String(id) && $('offer-error')) $('offer-error').textContent = errorText(error); }
    finally { button.disabled = false; }
  });
  for (const operation of ['send', 'discard']) {
    const button = $(`offer-${operation}`);
    if (!button) continue;
    button.addEventListener('click', async () => {
      const confirmBox = $('offer-confirm-expired');
      if (operation === 'send' && offerDraft?.warning && !confirmBox?.checked) {
        if ($('offer-error')) $('offer-error').textContent = 'Please check the box to confirm sending with an expired referral, or discard.';
        return;
      }
      button.disabled = true;
      try {
        const payload = operation === 'send' && offerDraft?.warning && confirmBox?.checked ? { confirm_expired: true } : {};
        await hmr.api('POST', `/api/messages/${encodeURIComponent(offerDraft.id)}/${operation === 'send' ? 'approve' : 'discard'}`, payload);
        offerDraft = null; offerStatus = operation === 'send' ? 'Sent' : ''; formOpen = false;
        if (selected === String(id)) {
          if (operation === 'send') await refresh();
          else await showPatient(id);
        }
      } catch (error) { if (selected === String(id) && $('offer-error')) $('offer-error').textContent = errorText(error); button.disabled = false; }
    });
  }
  if (action === 'offer_new') { selectPatientTab('Conversation'); $('offer-section')?.scrollIntoView?.(); }
  if (action && (availableActions(p, milestones).includes(action) || action === 'expired' || action.endsWith('_claimed'))) openForm(action, p);
  return true;
}
function openForm(action, patient) {
  formOpen = true;
  $('action-area').innerHTML = `<form id="action-form"><h3>${actionLabels[action]}</h3><div class="form">
    ${actionFields[action]
      .map(
        (f) => action === 'pathology_outcome' && f === 'outcome' ? `<label>Outcome<select name="outcome"><option value="none">None in My Health Record</option><option value="access_code">Access code needed</option><option value="saved_by_hand">I saved it myself</option></select></label>` : action === 'interactions_manual' && f === 'text' ? `<label>Text<textarea name="text" required></textarea></label>` : action === 'call' && f === 'outcome' ? `<label>Outcome<select name="outcome" required>${[['no_answer', 'No answer'], ['left_message', 'Left message'], ['spoke', 'Spoke'], ['booked', 'Booked'], ['declined', 'Declined'], ['other', 'Other']].map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>` : `<label>${esc({ visit_date: 'Visit date', report_sent: 'Report sent date', time: 'Start', irn: 'IRN', ihi: 'IHI', dob: 'Date of birth' }[f] || f[0].toUpperCase() + f.slice(1))}<input name="${f}"
    type="${f === 'date' || action === 'claim_now' ? 'date' : ['time', 'end'].includes(f) ? 'time' : 'text'}"
    value="${esc(f === 'date' ? (action === 'visited' ? H.visitDefaultDate(patient) : localDate(new Date())) : action === 'update' ? patient[f] || '' : '')}"${action === 'claim_now' ? ' required' : ''}></label>`,
      )
      .join('')}</div><p id="action-error" class="error" role="alert"></p><button class="primary">Save</button>
    <button type="button" data-cancel>Cancel</button></form>`;
  // forms can be opened from the follow-up rows below, so bring the form into view
  $('action-form').scrollIntoView?.({ block: 'nearest' });
  $('action-form').querySelector?.('input, select')?.focus();
  $('action-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const saveButton = event.target.querySelector?.('button.primary') || event.submitter || $('action-form')?.querySelector?.('button.primary');
    if (saveButton) saveButton.disabled = true;
    const fields = Object.fromEntries(new FormData(event.target));
    const staleError = $('action-error'); if (staleError) staleError.textContent = '';
    try {
      await hmr.api(
        'POST',
        `/api/patients/${encodeURIComponent(patient.id)}/action`,
        action === 'update'
          ? { action, fields }
          : action.startsWith('followup')
            ? { action: action.endsWith('_claimed') ? 'followup_claimed' : 'followup_done', kind: action.replace('_claimed', ''), ...fields }
            : { action, ...fields },
      );
    } catch (error) {
      if (saveButton) saveButton.disabled = false;
      $('action-error').textContent = errorText(error);
      return;
    }
    formOpen = false;
    try {
      await refresh();
      // refresh() leaves the open patient alone while a field has focus, so a saved action must redraw the patient
      // itself; otherwise the old form, its old error and its disabled Save button stay on screen after the save.
      if (typeof page !== 'undefined' && page === 'patients' && selected === String(patient.id) && !formOpen) {
        if (action === 'visited') detailTab = 'Overview';
        if (!await showPatient(patient.id)) throw Error('patient view unavailable');
        if (action === 'visited') setPatientLayout('patient');
      }
    } catch (error) {
      alert(action === 'visited' ? `Visit recorded, but the patient view could not be refreshed: ${errorText(error)}` : `Saved, but the view could not be refreshed: ${errorText(error)}`);
    }
  });
               }

