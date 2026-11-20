const { esc, date, group, sentence } = H;
const $ = (id) => document.getElementById(id);
if (typeof hmr.onEngineState === 'function') hmr.onEngineState(state => {
  let notice = document.getElementById('hmr-engine-connection-state');
  if (!notice) {
    notice = document.createElement('p');
    notice.id = 'hmr-engine-connection-state';
    notice.setAttribute('role', 'status');
    notice.className = 'error';
    notice.style.cssText = 'position:sticky;top:0;z-index:10000;padding:12px;background:#f6d8d8;color:#571515;font-weight:600';
    // Inside <main>: body is a flex row, so a direct child of body becomes a pane beside the sidebar.
    (document.querySelector('main') || document.body).prepend(notice);
  }
  notice.hidden = !!state.ready;
  notice.textContent = state.ready ? '' : (state.reason || 'Clinical engine is temporarily unavailable');
});

const labels = {
  today: 'Today', book: 'Book', visit: 'Visit', claim: 'Claim', activity: 'Activity', to_book: 'To book', report_editor: 'Edit report', followup_editor: 'Follow-up form',
  calendar: 'Calendar',
  messages: 'Messages',
  run: 'Run',
  patients: 'Patients',
  interview: 'Interview',
  followup: 'Follow-up',
  intake: 'Intake',
  reports: 'Reports',
  report: 'Report',
  mhr: 'My Health Record',
  emims: 'eMIMS',
  ppa: 'PPA',
  sheet: 'Sheet',
  amh: 'AMH',
  settings: 'Settings',
};
const browsers = ['mhr', 'emims', 'ppa', 'amh', 'sheet'];
const actionFields = {
  call: ['outcome', 'note'],
  archive: [], unarchive: [], resume: [], undo_stage: [], pathology_outcome: ['outcome', 'note'], interactions_manual: ['text'],
  followup1_claimed: ['date'],
  followup2_claimed: ['date'],
  book_phone: ['date', 'time', 'end'],
  move: ['date', 'time', 'end'],
  decline_phone: ['reason'],
  move_declined: [],
  expired: ['note'],
  claim_now: ['visit_date', 'report_sent'],
  hold: ['note'],
  note: ['text'],
  visited: ['date'],
  report_sent: ['date'],
  claimed: ['date'],
  followup1: ['date'],
  followup2: ['date'],
  update: ['phone', 'address', 'suburb', 'postcode', 'medicare', 'irn', 'ihi', 'dob', 'sex'],
};
const actionLabels = {
  call: 'Log call',
  archive: 'Archive', unarchive: 'Restore', resume: 'Resume', undo_stage: 'Undo', pathology_outcome: 'Pathology by hand', interactions_manual: 'Interactions by hand',
  followup1_claimed: 'Follow-up 1 claimed',
  followup2_claimed: 'Follow-up 2 claimed',
  book_phone: 'Booked by phone',
  move: 'Move visit',
  decline_phone: 'Declined by phone (move to Declined)',
  move_declined: 'Move to Declined folder',
  expired: 'Expired (move to Expired)',
  claim_now: 'Visited outside app - claim now',
  hold: 'Put on hold',
  note: 'Add note',
  visited: 'Mark visited',
  report_sent: 'Report sent',
  claimed: 'Mark claimed',
  followup1: 'Follow-up 1 done',
  followup2: 'Follow-up 2 done',
  update: 'Edit details',
};
let page = 'today';
let selected = null;
let patients = [];
let filter = 'All active';
let formOpen = false;
let detailTab = 'Overview';
let messagesTimer;
let results = [];
let oneOffNames = [];
let oneOffFolder = '';
let searchTimer;
let navToken = 0;
const navigationHistory = [];
let returning = false;
let navigationIntent = 0;
let tabNavigation = Promise.resolve();
let pendingEditorLeave = null;
const localDate = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function clock() {
  const now = new Date();
  $('clock').textContent = `${date(localDate(now))}  ${now.toLocaleTimeString('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })}`;
}
function nav() {
  const button = (id) => `<button data-page="${id}" class="${H.sectionOf(page) === id ? 'active' : ''}">${labels[id]}</button>`;
  $('nav').innerHTML = `<div class="nav-label">Work</div>${['today', 'book', 'visit', 'report', 'claim', 'followup'].map(button).join('')}
    <div class="nav-divider"></div>${['patients', 'activity'].map(button).join('')}<div class="nav-label">Browser</div>${['mhr', 'emims', 'ppa', 'amh', 'sheet'].map(button).join('')}<div class="nav-spacer"></div>${button('settings')}`;
}
async function navigate(id, restore = null, { history = 'push' } = {}) {
  const intent = ++navigationIntent;
  navToken++;
  const current = () => intent === navigationIntent;
  id = ({ book: 'messages', visit: 'calendar', report: 'reports', activity: 'run' })[id] || id;
  if (['My calendar', 'my calendar', 'my-calendar'].includes(id)) id = 'calendar';
  const previous = { page, scroll: document.querySelector('main').scrollTop, interviewId, reportId, followupId, followupNumber, selected, detailTab };
  if (formOpen && id !== page && !['interview', 'followup_editor', 'report_editor'].includes(page) && !confirm('Leave this page and discard unsaved changes?')) return;
  const editor = { interview: [interviewId, leaveInterview], followup_editor: [`${followupId}:${followupNumber}`, leaveFollowup], report_editor: [reportId, leaveReport] }[page];
  const editorKey = editor && `${page}:${editor[0]}`;
  if (editor && (id !== page || pendingEditorLeave?.key === editorKey)) {
    if (pendingEditorLeave?.key !== editorKey) {
      pendingEditorLeave = { key: editorKey, promise: Promise.resolve().then(editor[1]) };
    }
    const pending = pendingEditorLeave;
    let allowed;
    try { allowed = await pending.promise; }
    finally { if (pendingEditorLeave === pending) pendingEditorLeave = null; }
    if (!current() || !allowed) return false;
    if (id === previous.page && !restore) restore = previous;
  }
  if (!current()) return false;
  if (id !== page && history === 'push') navigationHistory.push(previous);
  if (restore) {
    if (id === 'interview') interviewId = restore.interviewId;
    if (id === 'report_editor') reportId = restore.reportId;
    if (id === 'followup_editor') { followupId = restore.followupId; followupNumber = restore.followupNumber; }
    if ('selected' in restore) { selected = restore.selected; detailTab = restore.detailTab; }
  }
  clearInterval(messagesTimer);
  if (id === 'messages') messagesTimer = setInterval(() => { if (!formOpen) refresh(); }, 30000);
  clearTimeout(runTimer);
  if (id !== 'run') pickerOpen = false;
  page = id;
  document.querySelector('main').scrollTop = 0;
  $('screen').removeAttribute('data-loaded-page');
  formOpen = false;
  nav();
  $('title').textContent = labels[H.sectionOf(id)];
  const tabs = { book: [['messages', 'Messages'], ['intake', 'New referrals'], ['to_book', 'To book']], visit: [['calendar', 'Calendar'], ['interview', 'Interview']] }[H.sectionOf(id)] || [];
  $('section-tabs').innerHTML = tabs.map(([target, label]) => `<button data-page="${target}" class="${id === target ? 'active' : ''}">${label}</button>`).join('');
  const browser = browsers.includes(id);
  $('toolbar').hidden = !browser;
  $('save-sign-in').hidden = true;
  $('results').hidden = !browser;
  if (browser) {
    $('screen').innerHTML =
      id === 'sheet'
        ? '<button class="primary" data-job="register_xlsx">Export register (Excel)</button> ' +
          '<button data-open-sheet>Open Google Sheet</button> <button data-job="import_history">Find past patients (history)</button><p id="job-output" role="status"></p><div id="history-import"></div>'
        : '';
    $('back').hidden = id === 'sheet';
    $('reload').hidden = id === 'sheet';
    $('tab-action').hidden = id === 'sheet' || id === 'amh';
    $('one-off-add').hidden = !['mhr', 'emims'].includes(id);
    const names = ['mhr', 'emims'].includes(id) ? await hmr.oneOff('list', id) : [];
    if (!current()) return false;
    oneOffNames = names;
    $('tab-action').textContent = { mhr: 'Collect pathology', emims: 'Run interactions', ppa: 'Fill claims' }[id] || '';
  }
  // Serialize native view changes so an older request cannot leave its view on top.
  const changeTab = tabNavigation.catch(() => {}).then(() => {
    if (current()) return browser && id !== 'sheet' ? hmr.tab('open', id) : hmr.tab('hide');
  });
  tabNavigation = changeTab;
  await changeTab;
  if (!current()) return false;
  if (browser) showResults();
  else await refresh();
  if (!current() || page !== id) return false;
  if (restore) document.querySelector('main').scrollTop = restore.scroll;
  return true;
}
async function goBack() {
  if (returning) return;
  const target = navigationHistory[navigationHistory.length - 1] || (page !== 'today' ? { page: 'today', scroll: 0 } : null);
  if (!target) return;
  returning = true;
  try {
    if (await navigate(target.page, target, { history: 'back' }) && navigationHistory[navigationHistory.length - 1] === target) navigationHistory.pop();
  } catch (error) {
    alert(errorText(error));
  } finally { returning = false; }
}
function errorText(error) {
  const message = String(error?.message || error);
  return message;
}
async function health() {
  const [status, today, tabs] = await Promise.allSettled([
    hmr.api('GET', '/api/status'), hmr.api('GET', '/api/today'), hmr.tab('statuses'),
  ]);
  const s = status.status === 'fulfilled' ? status.value : null;
  const phone = s?.gateway_online == null ? 'unknown' : s.gateway_online ? 'online' : 'offline';
  const chip = (text, state) => `<span class="${state}">${esc(text)}</span>`;
  const tabStates = tabs.status === 'fulfilled' ? tabs.value : {};
  const expanded = $('health').querySelector?.('.portal-inactive')?.open;
  const focused = typeof document !== 'undefined' && $('health').contains(document.activeElement) ? document.activeElement : null;
  const focusTarget = focused?.matches('.portal-inactive > summary') ? 'summary' : ['mhr', 'emims', 'ppa', 'amh'].includes(focused?.dataset?.page) ? focused.dataset.page : '';
  const portals = ['mhr', 'emims', 'ppa', 'amh'].map((id) => {
    const state = tabs.status === 'fulfilled' ? tabStates[id] || 'not open' : 'unknown';
    const cls = state === 'ready' ? 'ok' : state === 'not open' ? 'quiet' : ['loading', 'sign-in needed', 'unknown'].includes(state) ? 'warn' : 'bad';
    return { state, html: `<button data-page="${id}" class="${cls}">${esc(labels[id])}: ${esc(state)}</button>` };
  });
  const inactive = portals.filter(portal => portal.state === 'not open');
  $('health').innerHTML = chip(`Engine ${s ? 'connected' : 'unavailable'}`, s ? 'ok' : 'bad') +
    chip(`Phone ${phone}`, phone === 'online' ? 'ok' : 'warn') +
    chip(`Outbox ${s?.outbox_mode ? String(s.outbox_mode).toUpperCase() : 'unknown'}`, s?.outbox_mode === 'live' ? 'ok' : 'warn') +
    portals.filter(portal => portal.state !== 'not open').map(portal => portal.html).join('') +
    (inactive.length ? `<details class="portal-inactive" ${expanded ? 'open' : ''}><summary>Portals: ${inactive.length} not open</summary><div>${inactive.map(portal => portal.html).join('')}</div></details>` : '');
  if (focusTarget && (document.activeElement === focused || document.activeElement === document.body)) {
    let target = $('health').querySelector(focusTarget === 'summary' ? '.portal-inactive > summary' : `[data-page="${focusTarget}"]`);
    const group = target?.closest('details');
    if (group && !group.open && focusTarget !== 'summary') target = group.querySelector('summary');
    if (!target && focusTarget === 'summary') target = $('health').querySelector('[data-page]');
    target?.focus({ preventScroll: true });
  }
  $('next-visit').innerHTML = today.status === 'fulfilled' ? H.nextVisitText(today.value.visits, new Date()) : 'Next visit unavailable';
}
async function refresh() {
  if (formOpen) return;
  const scroll = document.querySelector('main').scrollTop;
  const started = page;
  const currentToken = typeof navToken !== 'undefined' ? ++navToken : 0;
  const isCurrent = () => page === started && (typeof navToken === 'undefined' || currentToken === navToken) && !formOpen;
  try {
    await health();
    if (!isCurrent()) return;
    if (page === 'today') await dashboard();
    if (!isCurrent()) return;
    if (page === 'calendar') {
      // drawer open: refresh the day around it instead of rebuilding the screen
      if ($('calendar') && $('day-content') && /^\d{4}-\d{2}-\d{2}$/.test(selectedDay || '') && $('detail') && !$('detail').hidden) {
        await Promise.all([loadDay(selectedDay), loadCalendar(), loadSummary()]);
        if (!isCurrent()) return;
        await showPatient(selected);
      } else await today();
    }
    if (!isCurrent()) return;
    if (page === 'messages') await messagesBoard();
    if (!isCurrent()) return;
    if (page === 'run') await runScreen();
    if (!isCurrent()) return;
    if (page === 'patients') {
      const [res, queue] = await Promise.all([hmr.api('GET', filter === 'Archived' ? '/api/patients?archived=1' : '/api/patients'), hmr.api('GET', '/api/run').catch(() => null)]);
      if (queue) { runTasks = queue.tasks || []; runStepsCatalog = queue.steps || []; }
      if (!isCurrent()) return;
      const interacting = !!$('detail')?.querySelector?.('details[open]');
      patients = res.patients;
      if (!$('search')) patientShell();
      renderPatients();
      if (selected && !formOpen && !interacting && !($('detail')?.contains(document.activeElement) && document.activeElement.matches('input, textarea, select'))) {
        await reselectActivePatient(selected, true);
      }
      clearTimeout(runTimer);
      const pollPatients = () => { if (page !== 'patients') return; if (formOpen || $('detail')?.querySelector?.('details[open]')) runTimer = setTimeout(pollPatients, 5000); else refresh(); };
      runTimer = setTimeout(pollPatients, 5000);
    }
    if (!isCurrent()) return;
    if (page === 'interview') await interviewScreen();
    if (!isCurrent()) return;
    if (page === 'followup_editor') await followupScreen();
    if (!isCurrent()) return;
    if (page === 'followup') await followupList();
    if (!isCurrent()) return;
    if (page === 'claim') await claimScreen();
    if (!isCurrent()) return;
    if (page === 'to_book') {
      const res = await hmr.api('GET', '/api/patients');
      if (!isCurrent()) return;
      patients = H.toBook(res.patients);
      if (!$('search')) patientShell();
      renderPatients();
      if (selected && !formOpen && !($('detail')?.contains(document.activeElement) && document.activeElement.matches('input, textarea, select'))) {
        await reselectActivePatient(selected, false);
      }
    }
    if (!isCurrent()) return;
    if (page === 'intake') await intake();
    if (!isCurrent()) return;
    if (page === 'reports') await reports();
    if (!isCurrent()) return;
    if (page === 'report_editor') await reportScreen();
    if (!isCurrent()) return;
    if (page === 'settings') await settings();
    if (!isCurrent()) return;
    $('screen').dataset.loadedPage = page;
    document.querySelector('main').scrollTop = scroll;
  } catch (error) {
    if (!isCurrent()) return;
    $('screen').innerHTML = `<p class="error">${esc(errorText(error))}</p>`;
  }
}
async function runJob(job, patientId) {
  const output = $('job-output') || $('results');
  output.textContent = 'Starting...';
  try {
    const body = patientId ? { job, patient_id: Number(patientId) } : { job };
    const { id } = await hmr.api('POST', '/api/jobs', body);
    let result;
    do {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      result = await hmr.api('GET', `/api/jobs/${id}`);
      output.textContent = result.state === 'running' ? 'Working...' : `${result.state}: ${result.output || ''}`;
    } while (result.state === 'running');
    if (job === 'import_history' && result.state === 'done' && page === 'sheet') {
      $('history-import').innerHTML =
        '<p>Nothing is added until you press Apply</p><button data-confirm-history>Apply history import</button><div id="history-confirm"></div>';
    }
    if (job === 'import_history_apply' && result.state === 'done' && $('history-import'))
      $('history-import').innerHTML = '';
    if (job === 'intake_dry' && result.state === 'done' && page === 'intake') await intake();
  } catch (error) {
    output.textContent = errorText(error);
  }
}
function showResults() {
  const chips = oneOffNames
    .map(
      (name, i) => `<span class="one-off-chip">${esc(name)}
    <button data-remove-one-off="${i}" aria-label="Remove ${esc(name)}">Remove</button></span>`,
    )
    .join(' ');
  $('results').innerHTML =
    chips +
    results
      .filter((r) => r.site === page)
      .map((r) => `<span>${esc(r.patient || r.site)}: ${esc(r.status)} ${esc(r.filename || '')}</span>`)
      .join(' &middot; ');
}
document.addEventListener('click', async (event) => {
  if (event.target.matches('input[type=checkbox]')) return;
  const b = event.target.closest('button, tr[data-patient], [data-drawer-patient]');
  if (!b) return;
  // stop names sit inside <summary>: open the patient instead of toggling the row
  if (b.matches('summary [data-drawer-patient]')) event.preventDefault();
  try {
    if (b.dataset.page === 'interview' && H.interviewTabTarget(page, selected, highlightedStopPatient)) return await openInterview(H.interviewTabTarget(page, selected, highlightedStopPatient));
    if (b.dataset.page) return await navigate(b.dataset.page);
    if (b.dataset.removeOneOff !== undefined) {
      oneOffNames = await hmr.oneOff('remove', page, Number(b.dataset.removeOneOff));
      return showResults();
    }
    if (b.dataset.oneOffCancel !== undefined) return navigate(page);
    if (b.dataset.pickFolder !== undefined) {
      const folder = await hmr.oneOff('pick', page);
      if (folder) {
        oneOffFolder = folder;
        $('one-off-folder').textContent = folder;
      }
      return;
    }
    if (b.dataset.next) {
      event.stopPropagation();
      const step = b.dataset.step;
      if (['add findings', 'build report'].includes(step.toLowerCase())) return await openReport(b.dataset.next);
      if (step.toLowerCase() === 'make interview sheet') return await openInterview(b.dataset.next);
      if (step.toLowerCase() === 'confirm medicines') {
        await navigate('reports');
        return await reportClick({ dataset: { medicines: b.dataset.next } });
      }
      const job = H.stepName(step);
      if (job && !['intake_dry', 'intake_apply', 'register_xlsx'].includes(job)) {
        await enqueue([job], [Number(b.dataset.next)]);
        const site = { pathology: 'mhr', interactions: 'emims', claim: 'ppa' }[job];
        if (site) {
          if (runMessage.includes('\n') || !/^[1-9]\d* task\(s\) queued/.test(runMessage)) alert(runMessage);
          if (/^[1-9]\d* task\(s\) queued/.test(runMessage)) await navigate(site);
        }
        return;
      }
      await navigate('patients');
      return await showPatient(
        b.dataset.next,
        { visit: 'visited', 'send report': 'report_sent', claim: 'claimed', 'offer a time': 'book_phone' }[step],
      );
    }
    if (b.dataset.amhRow !== undefined) {
      const name = H.genericName(b.closest('td').querySelector('[data-col="0"]').value);
      if (!name) return;
      await navigate('amh');
      if (page === 'amh')
        await hmr.tab('load', 'amh', `https://amhonline.amh.net.au/search?q=${encodeURIComponent(name)}`);
      return;
    }
    if (b.dataset.claimAction) { drawerOpener = b; detailTab = 'Overview'; return await showPatient(b.dataset.id, b.dataset.claimAction); }
    if (b.dataset.claimRun) { await enqueue(['claim'], [Number(b.dataset.claimRun)]); if (!/^[1-9]\d* task\(s\) queued/.test(runMessage) || runMessage.includes('\n')) alert(runMessage); if (/^[1-9]\d* task\(s\) queued/.test(runMessage)) await navigate('ppa'); return; }
    if (b.dataset.openFollowup) return await openFollowup(b.dataset.id, b.dataset.openFollowup);
    if (await dashboardClick(b)) return;
    if (await followupClick(b)) return;
    if (b.dataset.openInterview) return await openInterview(b.dataset.openInterview);
    if (await messageClick(b)) return;
    if (await interviewClick(b)) return;
    if (await reportEditorClick(b)) return;
    if (await runClick(b)) return;
    if (await reportClick(b)) return;
    if (b.dataset.forgetSignIn) {
      await hmr.signIns('forget', b.dataset.forgetSignIn);
      await settings();
      return;
    }
    if (await agentClick(b)) return;
    if (b.dataset.patientLayout !== undefined) {
      if (!['patients', 'to_book'].includes(page)) return await openPatientWorkspace(selected, detailTab, b.dataset.patientLayout);
      return setPatientLayout(b.dataset.patientLayout);
    }
    if (b.dataset.closePatient !== undefined) return closePatient();
    if (b.dataset.drawerPatient) {
      drawerOpener = b.closest('summary') || b;
      await showPatient(b.dataset.drawerPatient, b.dataset.action);
      return $('detail')?.querySelector('[data-close-patient]')?.focus();
    }
    if (b.dataset.openFullPatient !== undefined) return await openPatientWorkspace(b.dataset.openFullPatient, 'Overview', 'patient');
    if (b.dataset.backToPatients !== undefined) return setPatientLayout('split');
    if (b.dataset.patientHistory !== undefined) return await openPatientWorkspace(b.dataset.patientHistory, 'Activity', 'patient');
    if (b.dataset.patientActivity !== undefined) return await openPatientWorkspace(b.dataset.patientActivity, 'Activity', 'split');
    if (b.dataset.call !== undefined) {
      if (!['patients', 'to_book'].includes(page)) await navigate('patients');
      return await showPatient(b.dataset.call, 'call');
    }
    if (b.dataset.runTask !== undefined) {
      return await enqueue([b.dataset.runTask], [Number(b.dataset.patientId)]);
    }
    if (b.dataset.patient) {
      if (page === 'messages') return await openPatientWorkspace(b.dataset.patient, 'Conversation', 'patient');
      if (!['patients', 'to_book'].includes(page)) return await openPatientWorkspace(b.dataset.patient, 'Overview', 'patient');
      return await showPatient(b.dataset.patient);
    }
    if (b.dataset.filter) {
      filter = b.dataset.filter;
      if (page === 'patients') return await refresh();
      return renderPatients();
    }
    if (b.dataset.action) {
      if (formOpen && $('action-form') && !confirm('Replace the open action and discard its unsaved changes?')) return;
      return openForm(b.dataset.action, await hmr.api('GET', `/api/patients/${selected}`));
    }
    if (b.dataset.cancel !== undefined) {
      formOpen = false;
      return showPatient(selected);
    }
    if (b.dataset.tab) {
      return selectPatientTab(b.dataset.tab);
    }
    if (b.dataset.job) return await runJob(b.dataset.job);
    if (b.dataset.confirmHistory !== undefined) {
      $('history-confirm').innerHTML =
        '<p>Apply this history import?</p><button class="primary" data-job="import_history_apply">Confirm apply</button>';
      return;
    }
    if (b.dataset.openSheet !== undefined) return await hmr.tab('open', 'sheet');
    if (b.dataset.confirm !== undefined) {
      $('confirm').innerHTML =
        '<p>This will rename and move files in TO SORT and add referral patients to the register.</p>' +
        '<button class="primary" data-job="intake_apply">Confirm apply</button>';
    }
    if (b.dataset.edit !== undefined) {
      const i = b.dataset.edit;
      const row = window.intakeRows[i];
      formOpen = true;
      $(`edit-${i}`).innerHTML = `<form data-correction="${i}" class="form">${Object.entries(row.fields || {})
        .map(([k, v]) => `<label>${esc(k)}<input name="${esc(k)}" value="${esc(v)}"></label>`)
        .join('')}
        <button>Save correction</button><button type="button" data-intake-cancel>Cancel</button><p class="error"></p></form>`;
    }
    if (b.dataset.intakeCancel !== undefined) {
      formOpen = false;
      await intake();
    }
  } catch (error) {
    alert(errorText(error));
  }
});
document.addEventListener('change', async (event) => {
  if (event.target.matches('[data-sign-in-mode]')) {
    try {
      await hmr.signIns('mode', event.target.dataset.signInMode, event.target.value);
    } catch (error) {
      alert(errorText(error));
    }
    await settings();
    return;
  }
  if (event.target.matches('#interview-patient')) return await switchInterview(event.target.value);
  if (event.target.matches('[data-agent-route]')) {
    const entry = agentEntries.find((a) => a.name === event.target.dataset.agentRoute);
    const { has_key, ...agent } = entry;
    try {
      await hmr.api('POST', '/api/agents', { ...agent, route: event.target.value });
      agentMessage = 'Route saved.';
    } catch (error) {
      agentMessage = errorText(error);
    }
    await settings();
  }
  if (event.target.matches('[data-select-patient]')) {
    const id = Number(event.target.dataset.selectPatient);
    if (event.target.checked) checkedPatients.add(id);
    else checkedPatients.delete(id);
    renderPatients();
  }
  if (event.target.matches('[data-select-all]')) {
    for (const id of shownPatients) {
      if (event.target.checked) checkedPatients.add(id);
      else checkedPatients.delete(id);
    }
    renderPatients();
  }
  if (event.target.matches('[data-run-step]')) {
    if (event.target.checked) tickedSteps.add(event.target.dataset.runStep);
    else tickedSteps.delete(event.target.dataset.runStep);
    updateStepButton();
  }
  if (event.target.matches('#agent-type')) {
    $('agent-api').hidden = event.target.value !== 'api';
    $('agent-cli').hidden = event.target.value !== 'cli';
  }
});
document.addEventListener('submit', async (event) => {
  if (event.target.id === 'practice-settings') {
    event.preventDefault();
    await saveSettings(event.target);
    return;
  }
  if (event.target.id === 'medicines-form') {
    event.preventDefault();
    const saveBtn = event.target.querySelector('button.primary');
    if (saveBtn) saveBtn.disabled = true;
    try {
      readMedicines();
      await hmr.api('POST', `/api/patients/${encodeURIComponent(medicinePatient)}/meds`, {
        meds: medicineData.meds,
        allergies: medicineData.allergies,
        interview_usage: medicineData.interview_usage || [],
        alternatives: medicineData.alternatives,
        medicine_snapshot_sha256: medicineData.medicine_snapshot_sha256,
      });
      medicinePatient = null;
      medicineData = null;
      formOpen = false;
      if (page === 'reports') await reports(); else await showPatient(selected);
    } catch (error) {
      if (saveBtn) saveBtn.disabled = false;
      event.target.querySelector('.error').textContent = errorText(error);
    }
    return;
  }
  if (['agent-form', 'agent-select'].includes(event.target.id)) {
    event.preventDefault();
    await agentSubmit(event.target);
    return;
  }
  if (event.target.id === 'one-off-form') {
    event.preventDefault();
    try {
      const fields = Object.fromEntries(new FormData(event.target));
      oneOffNames = await hmr.oneOff('add', page, { ...fields, folder_path: oneOffFolder });
      await navigate(page);
    } catch (error) {
      event.target.querySelector('.error').textContent = errorText(error);
    }
    return;
  }
  if (event.target.id === 'run-picker') {
    event.preventDefault();
    await submitRunPicker(event.target);
    return;
  }
  if (event.target.dataset.correction === undefined) return;
  event.preventDefault();
  const row = window.intakeRows[event.target.dataset.correction];
  try {
    await hmr.api('POST', '/api/intake/correction', {
      file: row.file,
      fields: Object.fromEntries(new FormData(event.target)),
    });
    formOpen = false;
    await intake();
  } catch (error) {
    event.target.querySelector('.error').textContent = errorText(error);
  }
});
document.addEventListener('input', (event) => {
  if (event.target.closest?.('#detail form, #detail .message-composer, #one-off-form')) formOpen = true;
});
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && page === 'interview') {
    event.preventDefault();
    saveInterview();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && page === 'report_editor') {
    event.preventDefault();
    reportSaver.save();
  }
  if (event.key === 'Enter' && event.target.matches('tr[data-patient]')) event.target.click();
  if (event.key === 'Escape' && ['today', 'calendar'].includes(page) && $('detail') && !$('detail').hidden && !event.defaultPrevented) closePatient();
});
let drawerOpener = null;
function closePatient() {
  if (formOpen && !confirm('Close this patient and discard unsaved changes?')) return;
  patientRequest++;
  patientLayout = 'split';
  selected = null;
  formOpen = false;
  fullPatientView = false;
  if ($('chips')) $('chips').hidden = false;
  if ($('bulk')) $('bulk').hidden = false;

  if ($('detail')) $('detail').hidden = true;
  renderPatients();
  if (drawerOpener?.isConnected) drawerOpener.focus();
  drawerOpener = null;
}
$('one-off-add').onclick = async () => {
  try {
    await hmr.tab('hide');
    oneOffFolder = '';
    const fields =
      page === 'mhr'
        ? `
      <label>Surname<input name="last" required></label>
      <label>Date of birth<input name="dob" placeholder="DD-Mmm-YYYY" required></label>
      <label>Sex<select name="sex" required><option value="">Choose</option>
        <option value="F">Female</option><option value="M">Male</option></select></label>
      <label>Medicare number<input name="medicare"></label><label>IHI<input name="ihi"></label>`
        : `
      <label>Name for result file<input name="name" required></label>
      <label>Medicines, one per line (generic, optional brand)<textarea name="meds" required></textarea></label>
      <label>Allergies, one per line<textarea name="allergies"></textarea></label>`;
    $('screen').innerHTML = `<h2>Add someone not in the list</h2><form id="one-off-form" class="one-off-form">
      ${fields}<div><button type="button" data-pick-folder>Choose folder</button>
      <span id="one-off-folder">No folder chosen</span></div><p class="error" role="alert"></p>
      <div><button class="primary">Add</button> <button type="button" data-one-off-cancel>Cancel</button></div></form>`;
  } catch (error) {
    $('results').textContent = errorText(error);
  }
};
$('app-back').onclick = goBack;
$('back').onclick = async () => {
  try { if (!await hmr.tab('back', page)) await goBack(); }
  catch (error) { $('results').textContent = errorText(error); }
};
$('reload').onclick = () => hmr.tab('reload', page);
$('tab-action').onclick = async () => {
  try {
    results = results.filter((r) => r.site !== page);
    $('results').textContent = await hmr.tab('toggle', page);
  } catch (error) {
    $('results').textContent = error.message;
  }
};
hmr.onTab((s) => {
  health();
  if (s.site !== page) return;
  $('address').value = s.url;
  $('tab-action').textContent = s.armed
    ? 'Stop'
    : { mhr: 'Collect pathology', emims: 'Run interactions', ppa: 'Fill claims' }[s.site] || '';
});
hmr.onResult((r) => {
  results.push(r);
  showResults();
});
nav();
clock();
refresh();
setInterval(clock, 1000);
setInterval(() => {
  if (['today', 'calendar', 'patients'].includes(page) && !formOpen) refresh();
  else health();
}, 60000);

window.addEventListener('beforeunload', (event) => {
  if ((page === 'followup_editor' && followupSaver.dirty()) || (page === 'interview' && interviewDirty()) || (page === 'report_editor' && reportSaver.dirty())) {
    event.preventDefault();
    event.returnValue = '';
  }
});

$('save-sign-in').onclick = async () => {
  try {
    await hmr.signIns('request', page);
  } catch {
    $('results').textContent = 'Could not save sign-in';
  }
};
hmr.onSignIn((s) => {
  if (s.site === page) $('save-sign-in').hidden = !s.canSave;
});
