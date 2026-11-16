const messageKinds = { custom: 'Custom message', offer: 'Offer', follow_up: 'Follow-up', confirmation: 'Confirmation', reminder: 'Reminder', thanks_decline: 'Thanks for declining' };
let patientDraft = null;
let draftPatient = null;
let messageFilterQuery = '';
function messageTime(value) {
  if (!value) return '';
  return `${date(value)} ${String(value).slice(11, 16)}`.trim();
}
function messageCard(m, section, board = {}) {
  const reply = section === 'needs_you' && ['in', 'incoming'].includes(m.direction);
  const draftItem = (board.needs_you || []).find(x => String(x.id) === String(m.ai_draft_id) || String(x.answers_message_id || '') === String(m.id));
  const blocked = board.outbox_mode === 'test' && !(m.is_test_patient || draftItem?.is_test_patient || (board.test_patient_id != null && String(board.test_patient_id) === String(m.patient_id)));
  if (reply) return `<article class="card message-card"><div class="message-patient-row"><button class="message-patient" data-patient="${esc(m.patient_id)}">${esc(m.patient_name || m.name || 'Patient')}</button> <button class="btn-link" data-patient-history="${esc(m.patient_id)}">History</button></div><p class="message-reply">&ldquo;${esc(m.body || '')}&rdquo;</p>${m.offered_at || m.visit_date ? `<small>Offered: ${esc(messageTime(m.offered_at || m.visit_date))} ${esc(m.visit_time || '')}</small>` : ''}<div class="actions"><strong>Resolve reply</strong>${[['yes', 'Confirm'], ['new_time', 'New time'], ['decline', 'Decline'], ['call', 'Call'], ['done', 'Done']].map(([value, label]) => `<button data-resolve="${value}" data-id="${esc(m.id)}" data-patient-id="${esc(m.patient_id)}">${label}</button>`).join('')}</div><div id="resolve-confirm-${esc(m.id)}"></div><p class="error" id="resolve-error-${esc(m.id)}" role="alert"></p>${draftItem ? `<small>Suggested reply (AI)</small>${draftItem.warning ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(draftItem.warning)}</p><label class="confirm-expired"><input type="checkbox" id="board-confirm-expired-${esc(draftItem.id)}"> I confirm sending despite expired referral</label>` : ''}<p>${esc(draftItem.body || '')}</p><div id="board-edit-${esc(draftItem.id)}" hidden><label>Message<textarea id="board-body-${esc(draftItem.id)}">${esc(draftItem.body || '')}</textarea></label></div><div class="actions"><button data-message-send="${esc(draftItem.id)}" ${blocked ? 'disabled' : ''}>Send</button>${blocked ? '<small>Test mode: this will not be sent</small>' : ''}<button data-message-edit="${esc(draftItem.id)}">Edit</button><button data-message-discard="${esc(draftItem.id)}">Discard</button></div><p class="error" id="board-error-${esc(draftItem.id)}" role="alert"></p>` : ''}</article>`;
  const patientId = m.patient_id ?? m.id;
  const draft = m.state === 'draft' || !!m.hold_reason;
  const badges = [m.hold_reason, m.unclear || m.state === 'unclear' ? 'Unclear' : '', m.call_list || m.state === 'call_list' ? 'Call list' : ''].filter(Boolean);
  const time = m.created_at || m.sent_at || m.offered_at || m.visit_date || m.time;
  let extra = '';
  if (section === 'waiting') {
    const start = new Date(m.sent_at || m.offered_at || m.created_at);
    if (!isNaN(start)) {
      const hours = Math.max(0, Math.floor((Date.now() - start.getTime()) / 3600000));
      extra = `Waiting ${hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d ${hours % 24}h`}`;
    }
  }
  if (section === 'upcoming') extra = `Reminder sent: ${m.reminder_sent ? 'Yes' : 'No'}`;
  return `<article class="card message-card"><div class="message-patient-row"><button class="message-patient" data-patient="${esc(patientId)}">${esc(m.patient_name || m.name || 'Patient')}</button> <button class="btn-link" data-patient-history="${esc(patientId)}">History</button></div>
    <div>${esc(messageKinds[m.kind] || m.kind || '')} ${badges.map((b) => `<span class="message-badge">${esc(b)}</span>`).join(' ')}</div>
    <p class="message-preview">${esc(m.body || '')}</p><small>${esc(messageTime(time))} ${esc(extra)}</small>
    ${draft ? `${m.warning ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(m.warning)}</p><label class="confirm-expired"><input type="checkbox" id="board-confirm-expired-${esc(m.id)}"> I confirm sending despite expired referral</label>` : ''}<div id="board-edit-${esc(m.id)}" hidden><label>Message<textarea id="board-body-${esc(m.id)}">${esc(m.body || '')}</textarea></label></div><div class="actions"><button data-message-send="${esc(m.id)}" ${blocked ? 'disabled' : ''}>Send</button>${blocked ? '<small>Test mode: this will not be sent</small>' : ''}<button data-message-edit="${esc(m.id)}">Edit</button><button data-message-discard="${esc(m.id)}">Discard</button></div><p class="error" id="board-error-${esc(m.id)}" role="alert"></p>` : ''}
    ${section === 'waiting' ? `<div class="actions"><button data-call="${esc(patientId)}">Log call</button><button data-patient="${esc(patientId)}">Open patient</button></div>` : section === 'recent' ? `<div class="actions"><button data-patient="${esc(patientId)}">Open patient</button></div>` : ''}</article>`;
}
let checkStatus = '';
let messageBoardData = null;
async function messagesBoard() {
  const data = await hmr.api('GET', '/api/messages/board');
  if (page !== 'messages' || formOpen) return;
  messageBoardData = data;
  renderMessageBoard(data);
}
function renderMessageBoard(data) {
  const q = (messageFilterQuery || '').toLowerCase().trim();
  const matches = (m) => !q || [m.patient_name, m.name, m.phone, m.body].some(v => String(v || '').toLowerCase().includes(q));
  $('screen').innerHTML = `<p class="outbox-banner">${data.outbox_mode === 'test' ? 'Test mode - only the test phone receives messages' : 'Live'}</p>
    <div class="message-search"><label class="search">Search messages<input id="message-search" placeholder="Search by patient name, phone or message text..." value="${esc(messageFilterQuery)}"></label></div>
    <div class="actions board-toolbar"><button class="primary" data-check-messages>Check messages now</button><span id="check-status" role="status">${checkStatus}</span></div>
    <div class="message-board">${[['needs_you', 'Needs you'], ['waiting', 'Waiting for reply'], ['upcoming', 'Upcoming visits'], ['recent', 'Recent']].map(([key, title]) => {
      const items = (data[key] || []).filter(m => !m.answers_message_id && !(data.needs_you || []).some(reply => reply.ai_draft_id != null && String(reply.ai_draft_id) === String(m.id))).filter(matches);
      return `<section><h2>${title}</h2>${items.map((m) => messageCard(m, key, data)).join('') || `<p class="muted">${{ needs_you: 'No replies need you.', waiting: 'Nobody is waiting for a reply.', upcoming: 'No visits coming up.', recent: 'No recent messages.' }[key]}</p>`}</section>`;
    }).join('')}</div>`;
}
function messageComposer() {
  if (draftPatient !== selected) { patientDraft = null; draftPatient = selected; }
  return `<section class="panel-section message-composer"><h3>Message</h3><label>Kind<select id="message-kind" ${patientDraft ? 'disabled' : ''}>${Object.entries(messageKinds).map(([value, label]) => `<option value="${value}" ${patientDraft?.kind === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
    <div id="message-schedule" class="form" hidden><label>Date<input id="message-date" type="date"></label><label>Time (Queensland)<input id="message-time" type="time"></label></div>
    <div id="composer-warning-area">${patientDraft?.warning ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(patientDraft.warning)}</p><label class="confirm-expired"><input type="checkbox" id="composer-confirm-expired"> I confirm sending despite expired referral</label>` : ''}</div>
    <label id="message-body-label">Message<textarea id="message-body">${esc(patientDraft?.body || '')}</textarea></label>
    <div class="actions"><button data-message-prepare ${patientDraft ? 'hidden' : ''}>Prepare</button><button class="primary" data-patient-message-send ${patientDraft ? '' : 'hidden'}>Send</button><button data-patient-message-discard ${patientDraft ? '' : 'hidden'}>Discard</button></div><p class="error" id="message-error" role="alert"></p></section>`;
}
document.addEventListener('change', (event) => {
  if (event.target.id !== 'message-kind') return;
  $('message-schedule').hidden = !['offer', 'follow_up'].includes(event.target.value);
  $('message-body-label').hidden = event.target.value !== 'custom';
});
document.addEventListener('input', (event) => {
  if (event.target.id === 'message-search') {
    messageFilterQuery = event.target.value;
    const position = event.target.selectionStart;
    if (messageBoardData) { renderMessageBoard(messageBoardData); $('message-search')?.focus(); $('message-search')?.setSelectionRange(position, position); }
    return;
  }
  if (event.target.closest('.message-composer') || event.target.id.startsWith('board-body-')) formOpen = true;
  if (event.target.id === 'message-body' && patientDraft) patientDraft.body = event.target.value;
});
async function messageClick(b) {
  const d = b.dataset;
  if (d.resolveCancel !== undefined) { formOpen = false; $(`resolve-confirm-${d.resolveCancel}`).innerHTML = ''; return true; }
  if (d.resolve !== undefined) {
    if (d.resolve === 'decline' && !d.confirmed) {
      formOpen = true;
      $(`resolve-confirm-${d.id}`).innerHTML = `Mark as declined? <button data-resolve="decline" data-confirmed="1" data-id="${esc(d.id)}" data-patient-id="${esc(d.patientId)}">Yes</button> <button data-resolve-cancel="${esc(d.id)}">Cancel</button>`;
      return true;
    }
    try {
      b.disabled = true;
      await hmr.api('POST', `/api/messages/${encodeURIComponent(d.id)}/resolve`, { as: d.resolve });
      formOpen = false;
      if (d.resolve === 'new_time') { await navigate('patients'); await showPatient(d.patientId, 'offer_new'); $('offer-section')?.scrollIntoView(); }
      else if (page === 'messages') await messagesBoard(); else await showPatient(selected);
    } catch (e) { $(`resolve-error-${d.id}`).textContent = errorText(e); b.disabled = false; }
    return true;
  }
  if (d.checkMessages !== undefined) {
    b.disabled = true; b.textContent = 'Checking...';
    try {
      const r = await hmr.api('POST', '/api/messages/check', {});
      const n = r.new_replies || 0;
      checkStatus = `${n ? `${n} new ${n === 1 ? 'reply' : 'replies'}` : 'No new replies'} &middot; checked ${new Date().toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' })}`;
    } catch (e) { checkStatus = `<span class="error">${esc(String(e.message || e))}</span>`; }
    await messagesBoard();
    return true;
  }
  if (d.messageEdit !== undefined) {
    $(`board-edit-${d.messageEdit}`).hidden = false; formOpen = true; return true;
  }
  if (d.messageSend !== undefined || d.messageDiscard !== undefined) {
    const id = d.messageSend ?? d.messageDiscard;
    const error = $(`board-error-${id}`);
    const confirmBox = $(`board-confirm-expired-${id}`);
    if (d.messageSend !== undefined && confirmBox && !confirmBox.checked) {
      if (error) error.textContent = 'Please confirm sending despite expired referral or discard.';
      return true;
    }
    try {
      b.disabled = true;
      const payload = d.messageSend !== undefined ? {
        body: $(`board-body-${id}`)?.value,
        ...(confirmBox?.checked ? { confirm_expired: true } : {})
      } : {};
      await hmr.api('POST', `/api/messages/${encodeURIComponent(id)}/${d.messageSend !== undefined ? 'approve' : 'discard'}`, payload);
      formOpen = false; if (page === 'messages') await messagesBoard(); else await showPatient(selected);
    } catch (e) { if (error) error.textContent = String(e.message || e); b.disabled = false; }
    return true;
  }
  if (d.messagePrepare !== undefined) {
    const kind = $('message-kind').value, body = $('message-body').value;
    const error = $('message-error');
    if (kind === 'custom' && !body.trim()) { error.textContent = 'Enter a message.'; return true; }
    if (['offer', 'follow_up'].includes(kind) && (!$('message-date').value || !$('message-time').value)) { error.textContent = 'Enter a date and time.'; return true; }
    const fields = { kind };
    if (kind === 'custom') fields.body = body;
    if (['offer', 'follow_up'].includes(kind)) { fields.date = $('message-date').value; fields.time = $('message-time').value; }
    try {
      b.disabled = true;
      patientDraft = await hmr.api('POST', `/api/patients/${encodeURIComponent(selected)}/messages`, fields);
      draftPatient = selected; formOpen = true;
      const warnArea = $('composer-warning-area');
      if (warnArea) {
        warnArea.innerHTML = patientDraft.warning
          ? `<p class="warning-banner" role="alert"><strong>Warning:</strong> ${esc(patientDraft.warning)}</p><label class="confirm-expired"><input type="checkbox" id="composer-confirm-expired"> I confirm sending despite expired referral</label>`
          : '';
      }
      $('message-body').value = patientDraft.body || ''; $('message-body-label').hidden = false;
      $('message-kind').disabled = true; $('message-schedule').hidden = true;
      b.hidden = true; b.disabled = false;
      document.querySelector('[data-patient-message-send]').hidden = false;
      document.querySelector('[data-patient-message-discard]').hidden = false; error.textContent = '';
    } catch (e) { error.textContent = String(e.message || e); b.disabled = false; }
    return true;
  }
  if (d.patientMessageSend !== undefined || d.patientMessageDiscard !== undefined) {
    const confirmBox = $('composer-confirm-expired');
    if (d.patientMessageSend !== undefined && patientDraft?.warning && confirmBox && !confirmBox.checked) {
      $('message-error').textContent = 'Please confirm sending despite expired referral or discard.';
      return true;
    }
    try {
      b.disabled = true;
      const payload = d.patientMessageSend !== undefined ? {
        body: $('message-body').value,
        ...(confirmBox?.checked ? { confirm_expired: true } : {})
      } : {};
      await hmr.api('POST', `/api/messages/${encodeURIComponent(patientDraft.id)}/${d.patientMessageSend !== undefined ? 'approve' : 'discard'}`, payload);
      patientDraft = null; formOpen = false; await showPatient(selected);
    } catch (e) { $('message-error').textContent = String(e.message || e); b.disabled = false; }
    return true;
  }
  return false;
}
