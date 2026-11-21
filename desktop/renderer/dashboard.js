const attentionGroupHtml = (group, primary = false) => `<section class="card"><h2>${esc(group.title)} <span class="count-pill">${group.items.length}</span></h2>${group.items.length ? group.items.map((item, i) => `<div class="attention-row"><div>${item.patient_id == null ? `<strong>${esc(item.name)}</strong>` : `<button data-drawer-patient="${esc(item.patient_id)}">${esc(item.name)}</button>`}<span class="muted"> ${H.attentionDetail(item, group.key)}</span></div><div><button ${primary ? 'class="primary"' : ''} data-attention-group="${esc(group.key)}" data-attention-index="${i}">${esc(H.attentionLabel(item.action))}</button><span id="attention-confirm-${esc(group.key)}-${i}"></span></div></div>`).join('') : `<p class="muted">${esc(attentionEmpty[group.key] || '')}</p>`}</section>`;
const attentionEmpty = {
  today_visits: 'No visits today.', visits_to_check: 'No visits to check.', visits_to_record: 'No visits to check.',
  replies_waiting: 'No replies waiting.', offers_passed: 'No offers past their date.', prep: 'Nothing to prepare this week.',
  reports: 'No reports waiting.', claims: 'No claims due.', followups: 'No follow-ups due.',
  referrals: 'No referrals expiring.', stuck: 'Nothing is stuck.',
};
let attentionGroups = [];
async function dashboard() {
  const data = await hmr.api('GET', '/api/attention');
  if (page !== 'today' || formOpen) return;
  if ($('detail') && !$('detail').hidden) { await showPatient(selected); return; }
  attentionGroups = data.groups || [];

  const filled = attentionGroups.filter((g) => g.items.length), empty = attentionGroups.filter((g) => !g.items.length);
  $('screen').innerHTML = `<div class="dashboard-grid">${filled.map((group, index) => attentionGroupHtml(group, index === 0)).join('')}${empty.length ? `<section class="card all-clear"><h2>${filled.length ? 'Nothing due in these areas' : 'All clear'}</h2>${empty.map(g => `<p>${esc(attentionEmpty[g.key] || '')}</p>`).join('')}</section>` : ''}</div><p id="attention-status" role="status"></p><div id="detail" class="detail drawer" role="dialog" aria-label="Patient" hidden></div>`;
}
async function dashboardClick(button) {
  if (button.dataset.attentionCancel !== undefined) {
    formOpen = false;
    button.parentElement.innerHTML = '';
    return true;
  }
  const key = button.dataset.attentionGroup;
  if (!key) return false;
  const item = attentionGroups.find((g) => g.key === key)?.items[Number(button.dataset.attentionIndex)];
  if (!item) return true;
  const id = item.patient_id;
  if (item.action === 'not_visited') {
    if (!button.dataset.attentionYes) {
      formOpen = true;
      $(`attention-confirm-${key}-${button.dataset.attentionIndex}`).innerHTML = ` Mark as not visited? <button class="primary" data-attention-group="${esc(key)}" data-attention-index="${esc(button.dataset.attentionIndex)}" data-attention-yes="1">Yes</button> <button data-attention-cancel>Cancel</button>`;
    } else {
      await hmr.api('POST', `/api/patients/${encodeURIComponent(id)}/action`, { action: 'not_visited' });
      formOpen = false;
      await dashboard();
    }
  } else if (item.action === 'open_interview') await openInterview(id);
  else if (item.action === 'open_report') await openReport(id);
  else if (['open_messages', 'check_phone'].includes(item.action)) await navigate('messages');
  else if (['followup1', 'followup2'].includes(item.action)) await openFollowup(id, item.action.slice(-1));
  else if (['pathology', 'interview_sheet', 'retry'].includes(item.action)) {
    await enqueue([item.action === 'retry' ? item.step : item.action], id == null ? [] : [Number(id)]);
    $('attention-status').textContent = runMessage;
  } else if (id != null) {
    drawerOpener = button;
    const action = ({
      visited: 'visited',
      expired: 'expired',
      followup1_claimed: 'followup1_claimed',
      followup2_claimed: 'followup2_claimed',
    })[item.action] || item.action;
    await showPatient(id, action);
    $('detail')?.querySelector('[data-close-patient]')?.focus();
  }
  return true;
}

async function claimScreen() {
  const res = await hmr.api('GET', '/api/patients');
  if (page !== 'claim') return;
  patients = res.patients;
  const list = (state, empty, actions) => {
    const rows = patients.filter((p) => p.state === state);
    return rows.length ? rows.map((p) => `<div class="attention-row"><button data-drawer-patient="${esc(p.id)}">${esc(p.name)}</button><div>${actions(p)}</div></div>`).join('') : `<p class="muted">${empty}</p>`;
  };
  $('screen').innerHTML = `<section class="card"><h2>Report to send</h2>${list('signed_off', 'No reports waiting to be sent.', (p) => `<button data-claim-action="report_sent" data-id="${esc(p.id)}">Mark report sent</button>`)}</section>
    <section class="card"><h2>To claim</h2>${list('sent', 'Nothing to claim.', (p) => `<button data-claim-run="${esc(p.id)}">Open claim</button> <button data-claim-action="claimed" data-id="${esc(p.id)}">Mark claimed</button>`)}</section><div id="detail" class="detail drawer" role="dialog" aria-label="Patient" hidden></div>`;
}
async function followupList() {
  const [attention, list] = await Promise.all([hmr.api('GET', '/api/attention'), hmr.api('GET', '/api/patients')]);
  if (page !== 'followup') return;
  patients = list.patients;
  const due = (attention.groups || []).find((g) => g.key === 'followups') || { key: 'followups', items: [] };
  due.title = 'Due now'; attentionGroups = [due];
  const followups = patients.filter((p) => p.stage === 'followup');
  const awaitingClaim = followups.filter((p) => /claim/i.test(p.stage_step || ''));
  const waiting = followups.filter((p) => /waiting/i.test(p.stage_step || ''));
  const duePatients = followups.filter((p) => !/claim|waiting/i.test(p.stage_step || ''));

  const section = (title, items, emptyText, actionFn) => `
    <section class="card"><h2>${title} <span class="count-pill">${items.length}</span></h2>
    ${items.length ? items.map(actionFn).join('') : `<p class="muted">${emptyText}</p>`}</section>`;

  const row = (p, btn) => `
    <div class="attention-row"><div><button data-drawer-patient="${esc(p.id)}">${esc(p.name)}</button><span class="muted"> ${esc(H.stepLabel(p.stage_step))}</span></div>
    <div>${btn}</div></div>`;

  $('screen').innerHTML = `${attentionGroupHtml(due)}
    ${section('Awaiting claim', awaitingClaim, 'No follow-up claims waiting.', (p) => {
      const n = /2/.test(p.stage_step || '') ? '2' : '1';
      return row(p, `<button data-drawer-patient="${esc(p.id)}" data-action="followup${n}_claimed">Record claim</button>`);
    })}
    ${section('Waiting', waiting, 'No upcoming follow-ups waiting.', (p) => {
      return row(p, `<button data-drawer-patient="${esc(p.id)}">Open patient</button>`);
    })}
    ${duePatients.length ? section('Other open follow-ups', duePatients, '', (p) => {
      const n = /2/.test(p.stage_step || '') ? '2' : '1';
      return row(p, `<button data-open-followup="${n}" data-id="${esc(p.id)}">Open follow-up form</button>`);
    }) : ''}
    <p id="attention-status" role="status"></p><div id="detail" class="detail drawer" role="dialog" aria-label="Patient" hidden></div>`;
}
