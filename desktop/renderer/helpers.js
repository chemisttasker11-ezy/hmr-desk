const H = (() => {
  const localDate = (d = new Date()) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const esc = (value) =>
    String(value ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
  function date(value) {
    if (!value) return '';
    const match = String(value).match(/^(\d{4})-(\d\d)-(\d\d)/);
    return match ? `${match[3]}/${match[2]}/${match[1]}` : String(value);
  }
  function interviewOutstanding(record) {
    const referral = record.meds || [], found = record.other_meds || [];
    const meds = record.details?.meds || [], other = record.details?.other_meds || [];
    const active = referral.map((_, i) => meds[i] || {}).filter(m => m.use_status !== 'not_using');
    const all = [...active, ...found.map((_, i) => other[i] || {})];
    const health = ['falls', 'dizziness', 'drowsiness', 'pain', 'sleep', 'bowel', 'bladder', 'mood', 'memory', 'appetite'].map(key => record.details?.[`sx_${key}`] || '');
    return { checked: all.filter(m => m.checked).length, total: all.length,
      withoutStatus: referral.filter((_, i) => !meds[i]?.use_status || meds[i].use_status === 'unknown').length,
      clarify: (Array.isArray(record.clarify) ? record.clarify.join('\n') : record.clarify || '').split(/\r?\n/).filter(line => line.trim()).length,
      consentMissing: !(record.consent_file || record.consent_signed_draft || record.consent?.signed), healthUnanswered: health.some(Boolean) ? health.filter(value => !value).length : 0 };
  }
  function visitDefaultDate(patient, today = localDate()) {
    return /^\d{4}-\d{2}-\d{2}$/.test(patient.visit_date || '') && patient.visit_date <= today ? patient.visit_date : today;
  }
  function interviewHeader(header = {}) {
    const name = [header.name, header.age !== '' && header.age != null ? `age ${header.age}` : '']
      .filter(Boolean)
      .join(', ');
    const visit = String(header.visit || '')
      .trim()
      .split(/\s+/);
    return [
      [
        name,
        header.dob && `DOB ${date(header.dob)}`,
        visit[0] && `Visit ${date(visit[0])}${visit[1] ? ' ' + visit[1].slice(0, 5) : ''}`,
        header.gp && `GP ${header.gp}`,
      ]
        .filter(Boolean)
        .join(` ${String.fromCharCode(183)} `),
      [header.address, header.phone].filter(Boolean).join(` ${String.fromCharCode(183)} `),
    ];
  }
  function sourceLabel(source) {
    return /brainstorm/i.test(source || '') ? 'Brainstorm' : /past/i.test(source || '') ? 'Past cases' : 'Library';
  }
  function firstLines(value) {
    return String(value || '')
      .split(/\r?\n/)
      .slice(0, 3)
      .join('\n');
  }
  function group(state) {
    if (['new', 'pooled', 'offered'].includes(state)) return 'Offered';
    if (['confirmed', 'pathology_ready', 'sheet_ready'].includes(state)) return 'Scheduled';
    if (['visited', 'report_drafted', 'signed_off', 'sent'].includes(state)) return 'Visited';
    if (state === 'claimed') return 'Claimed';
    if (state === 'hold') return 'Hold';
    if (['declined', 'expired'].includes(state)) return 'Declined';
    return 'Other';
  }
  function sentence(event) {
    let detail = {};
    try {
      detail = JSON.parse(event.detail || '{}');
    } catch {
      /* Older event details may be plain text. */
    }
    const labels = {
      book_phone: 'Visit booked by phone',
      move: 'Visit moved',
      decline_phone: 'Declined by phone',
      hold: 'Put on hold',
      note: 'Note added',
      visited: 'Visit completed',
      report_sent: 'Report sent',
      claimed: 'Claimed',
      update: 'Details updated',
      referral_received: 'Referral received',
      pathology_result: 'Pathology result recorded',
      interview_sheet: 'Interview sheet created',
      report_drafted: 'Report drafted',
      signed_off: 'Report signed off',
      state: 'Status changed',
    };
    const extra = detail.text || detail.note || detail.reason || detail.date || '';
    return `${labels[event.type] || String(event.type || 'Event').replaceAll('_', ' ')}${extra ? ': ' + extra : ''}`;
  }
  const steps = {
    interview_pack: 'Prepare interview pack',
    report_draft: 'Draft report',
    intake_dry: 'Review intake',
    intake_apply: 'Apply intake',
    pathology: 'Collect pathology',
    interview_sheet: 'Make interview sheet',
    interview_assist: 'Interview assist (AI)',
    report_extract: 'Extract report',
    report_start: 'Start report',
    report_assist: 'Draft with AI',
    interactions: 'Check interactions',
    report_build: 'Build report',
    claim: 'Claim',
    register_xlsx: 'Export register',
  };
  const plainSteps = { 'confirm medicines': 'Check medicines for interaction check' };
  function sectionOf(page) {
    return ({ messages: 'book', intake: 'book', to_book: 'book', calendar: 'visit', interview: 'visit',
      reports: 'report', report_editor: 'report', followup_editor: 'followup', run: 'activity' })[page] || page;
  }
  function toBook(patients, now = new Date()) {
    const passed = (p) => (Array.isArray(p.flags) && p.flags.includes('offer_passed')) || (p.state === 'offered' && p.visit_date && new Date(`${p.visit_date}T${p.visit_time || '00:00'}`) < now);
    return patients.filter((p) => ['intake', 'booking'].includes(p.stage)).slice().sort((a, b) =>
      Number(!!passed(b)) - Number(!!passed(a)) || String(a.visit_date || '9999').localeCompare(String(b.visit_date || '9999')) ||
      String(a.visit_time || '').localeCompare(String(b.visit_time || '')));
  }
  function stepLabel(step) { return plainSteps[String(step || '').replaceAll('_', ' ').toLowerCase()] || steps[step] || ({ followup1: 'Follow-up 1', followup2: 'Follow-up 2' })[step] || String(step || '').replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()); }
  function stageText(p) {
    const stage = ({ followup: 'Follow-up', hold: 'On hold' })[p.stage] || String(p.stage || '').replace(/^./, c => c.toUpperCase());
    const step = String(p.stage_step || '').replaceAll('_', ' ');
    const displayStep = step.toLowerCase() === 'confirm medicines' ? 'check medicines for interaction check' : step;
    return stage + (displayStep ? ' &middot; ' + esc(displayStep) : '');
  }
  function stageClass(stage) {
    return ({ intake: 'booking', booking: 'booking', ready: 'ready', report: 'report', claim: 'report', followup: 'followup', hold: 'hold', declined: 'declined', expired: 'declined', done: 'done', archived: 'done' })[stage] || 'done';
  }
  function hasNextStep(p) {
    return !!p.next_step && !['declined', 'expired', 'done', 'hold', 'archived'].includes(p.stage);
  }
  function flagWords(p) {
    const labels = { needs_call: 'Needs a call', referral_expired: 'Referral expired', referral_expiring: 'Referral expiring', visit_passed: 'Visit date passed', offer_passed: 'Offer date passed', reply_waiting: 'Reply waiting', no_folder: 'No folder', archived: 'Archived', archive_suggested: 'Archive suggested' };
    const words = (p.flags || []).map(f => f === 'folder_mismatch' && p.folder_check ? `Folder is in ${p.folder_check.actual}, expected ${p.folder_check.expected}` : labels[f]).filter(Boolean);
    if (p.stage === 'hold' && !words.includes('On hold')) words.push('On hold');
    if (p.stage === 'archived' && !words.includes('Archived')) words.push('Archived');
    return words;
  }
  function stageActions(p, milestones = {}) {
    const actions = {
      intake: ['offer', 'book_phone', 'decline_phone', 'call', 'hold', 'expired', 'claim_now'],
      booking: ['offer', 'book_phone', 'decline_phone', 'call', 'hold', 'expired', 'claim_now', 'pathology_outcome'],
      ready: ['interview', 'visited', 'offer', 'call', 'pathology_outcome', 'hold', 'decline_phone', 'expired', 'claim_now'],
      report: ['medicines', 'interactions', 'interactions_manual', 'report_start', 'edit_report', 'build_report', 'signed_off', 'report_sent', 'pathology_outcome'],
      claim: ['claim', 'claimed', 'pathology_outcome'],
      followup: [],
      done: [],
      hold: ['resume'],
      declined: ['move_declined', 'archive'],
      expired: ['move_declined', 'archive'],
      archived: ['unarchive']
    }[p.stage] || [];
    const result = actions.filter(a => a !== 'move_declined' || !(p.folder || '').startsWith('Declined-Exp'));
    if (p.stage === 'booking' && p.visit_date && (p.visit_date <= localDate() || ['confirmed', 'pathology_ready', 'sheet_ready'].includes(p.state))) {
      if (!result.includes('visited')) result.push('visited');
    }
    if (p.stage === 'hold' && (p.flags || []).some(f => f.startsWith('referral_expir'))) {
      if (!result.includes('expired')) result.push('expired');
    }
    if (['followup', 'done'].includes(p.stage)) {
      for (const n of [1, 2]) {
        result.push(`followup${n}`);
        const pf = p.patient_followups || {};
        const done = milestones[`followup${n}_done`] || pf[`followup${n}_done`];
        const claimed = milestones[`followup${n}_claimed`] || pf[`followup${n}_claimed`];
        if (done && !claimed) result.push(`followup${n}_claimed`);
      }
      if ((p.flags || []).includes('archive_suggested')) result.push('archive');
    }
    return result;
  }
  function urgencySort(a, b) {
    const urgent = p => (p.flags || []).some(f => ['reply_waiting', 'offer_passed', 'visit_passed', 'referral_expired'].includes(f));
    return Number(urgent(b)) - Number(urgent(a)) || String(a.visit_date || '9999').localeCompare(String(b.visit_date || '9999')) || String(a.name || '').localeCompare(String(b.name || ''));
  }
  function stepName(label) {
    if (!label) return undefined;
    if (label === 'prepare interview sheet') return 'interview_sheet';
    return Object.keys(steps).find((key) => key === label || steps[key].toLowerCase() === String(label).toLowerCase());
  }
  const bulkSteps = [
    'pathology',
    'interview_sheet',
    'report_extract',
    'interactions',
    'report_start',
    'report_build',
    'claim',
  ];
  function patientPathway(p, milestones = {}, stepsList = []) {
    const stepsMap = Object.fromEntries((stepsList || p.steps || []).map((s) => [s.name, s]));
    const stage = p.stage;
    const isPastBooking = ['ready', 'report', 'claim', 'followup', 'done'].includes(stage);
    const isVisited = ['visited', 'report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state) || ['report', 'claim', 'followup', 'done'].includes(stage);
    const isReportComplete = ['sent', 'claimed'].includes(p.state) || ['claim', 'followup', 'done'].includes(stage) || !!milestones.report_sent;
    const isClaimComplete = ['claimed'].includes(p.state) || ['followup', 'done'].includes(stage) || !!milestones.claimed;
    const isFollowupComplete = stage === 'done' || (!!milestones.followup1_claimed && !!milestones.followup2_claimed);

    return [
      {
        id: 'booking',
        title: 'Booking & prep',
        completed: isPastBooking,
        current: stage === 'booking' || stage === 'intake',
        detail: p.visit_date ? `Booked ${date(p.visit_date)} ${p.visit_time || ''}` : 'Not booked yet',
      },
      {
        id: 'visit',
        title: 'Visit & interview',
        completed: isVisited,
        current: !isVisited && (stage === 'ready' || (stage === 'booking' && p.visit_date && p.visit_date <= localDate())),
        detail: isVisited ? 'Visit recorded' : (stage === 'ready' ? 'Ready for visit' : (p.visit_date ? (p.visit_date <= localDate() ? 'Visit due' : 'Booked, awaiting visit day') : 'Awaiting booking')),
      },
      {
        id: 'report',
        title: 'Medicines & report',
        completed: isReportComplete,
        current: isVisited && !isReportComplete && stage === 'report',
        detail: isReportComplete ? 'Report sent' : (stepsMap.report_build?.done ? 'Built, ready for sign-off' : (stepsMap.report_start?.done ? 'Draft in progress' : 'Awaiting report')),
      },
      {
        id: 'claim',
        title: 'Claim',
        completed: isClaimComplete,
        current: isReportComplete && !isClaimComplete && stage === 'claim',
        detail: isClaimComplete ? 'Claimed' : (stage === 'claim' ? 'Ready to claim' : 'Awaiting report completion'),
      },
      {
        id: 'followup',
        title: 'Follow-up',
        completed: isFollowupComplete,
        current: isClaimComplete && !isFollowupComplete && stage === 'followup',
        detail: isFollowupComplete ? 'Follow-ups complete' : (stage === 'followup' ? 'Follow-up active' : 'Post-claim'),
      },
    ];
  }
  function commonStep(patients) {
    const counts = {};
    for (const p of patients) {
      const step = stepName(p.next_step);
      if (bulkSteps.includes(step)) counts[step] = (counts[step] || 0) + 1;
    }
    return bulkSteps.reduce((best, step) => (counts[step] > (counts[best] || 0) ? step : best), bulkSteps[0]);
  }
  function suburb(value) {
    return String(value || '')
      .replace(/^\d{4}\s+/, '')
      .replace(/\s*\d{4}\s*$/, '')
      .trim();
  }
  function displayAddress(address, value) {
    const place = suburb(value);
    return [
      address,
      place &&
      !String(address || '')
        .toLowerCase()
        .includes(place.toLowerCase())
        ? place
        : '',
    ]
      .filter(Boolean)
      .join(', ');
  }
  function recordChanged(record, saved) {
    return JSON.stringify(record) !== saved;
  }
  function addRow(rows, width) {
    return [...rows, Array(width).fill('')];
  }
  function removeRow(rows, index) {
    return rows.filter((_, i) => i !== index);
  }
  function moveFinding(items, index, direction) {
    const to = index + direction;
    if (index < 0 || index >= items.length || to < 0 || to >= items.length) return [...items];
    const result = [...items];
    [result[index], result[to]] = [result[to], result[index]];
    return result;
  }
  function undoFinding(items, deleted) {
    const result = [...items];
    result.splice(Math.min(deleted.index, result.length), 0, deleted.item);
    return result;
  }
  function reviewed(fields, key) {
    return (fields || []).filter((field) => field !== key);
  }
  function findingFromResult(item) {
    return { title: item.title || '', rec: item.rec || '', rationale: item.rationale || '' };
  }
  function growTextarea(el) {
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }
  function genericName(value) {
    return String(value || '')
      .split(/\d/)[0]
      .trim()
      .replace(/[\s,;:/(-]+$/, '');
  }
  function settingsDiff(settings, values) {
    return Object.fromEntries(
      settings.filter((item) => values[item.key] !== item.value).map((item) => [item.key, values[item.key]]),
    );
  }
  function consentValidation(consent = {}) {
    if (
      consent.by === 'authorised' &&
      (!Number.isInteger(Number(consent.relationship)) ||
        Number(consent.relationship) < 1 ||
        Number(consent.relationship) > 5)
    )
      return "Choose the authorised person's relationship.";
    if (consent.by === 'authorised' && !String(consent.authorised_name || '').trim())
      return "Enter the authorised person's name.";
    return '';
  }
  function showInterviewRefresh(record, detail) {
    return record?.interview_newer === true && !['sent', 'claimed'].includes(detail?.state) && !detail?.report_sent && !detail?.visits?.[0]?.report_sent;
  }
  // A typed date such as 01102026 (no separators) can be read as 1 Oct or 10 Jan. The text is never
  // rewritten; the pharmacist is only told to write it unambiguously.
  function dateTextHint(value) {
    const text = String(value ?? '').trim();
    return /^\d{6,8}$/.test(text) ? `"${text}" has no separators. Write it as DD/MM/YYYY so the day and month cannot be misread.` : '';
  }
  function pathologyDateHints(rows) {
    return (rows || []).map((row, i) => (dateTextHint(Array.isArray(row) ? row[2] : '') ? `Row ${i + 1}: ${dateTextHint(row[2])}` : '')).filter(Boolean);
  }
  function tableInput(key, title, columns, rows, prefix) {
    return `<div class="interview-table"><table><thead><tr>${columns.map((c) => `<th scope="col">${esc(c)}</th>`).join('')}<th>Remove</th></tr></thead><tbody>${(rows || []).map((row, i) => `<tr>${columns.map((c, j) => `<td>${prefix === 'report' && !(key === 'meds' && j >= 2) ? `<input data-field="${esc(key)}" data-row="${i}" data-col="${j}" aria-label="${esc(c)} row ${i + 1}" value="${esc(row[j] || '')}">` : `<textarea data-field="${esc(key)}" data-row="${i}" data-col="${j}" aria-label="${esc(c)} row ${i + 1}">${esc(row[j] || '')}</textarea>`}${j === 0 && (key === 'meds' || (prefix === 'interview' && key === 'other_meds')) ? `<button type="button" data-amh-row aria-label="Search AMH for ${esc(c)} row ${i + 1}">AMH</button>` : ''}</td>`).join('')}<td><button type="button" data-${prefix}-remove="${esc(key)}" data-row="${i}" aria-label="Remove ${esc(title)} row ${i + 1}">Remove</button></td></tr>`).join('')}</tbody></table></div><button type="button" data-${prefix}-add="${esc(key)}">Add row</button>`;
  }
  function draftStorage() {
    // Plaintext localStorage is a legacy source only. In the packaged app
    // DPAPI-protected Electron IPC is the *sole* destination for new drafts.
    const vault = typeof window !== 'undefined' && window.hmr?.draftStore;
    if (!vault) return localStorage; // pure Node unit harness without Electron
    const legacyKeys = () => Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .filter(key => key?.startsWith('hmr-draft:'));
    const allKeys = () => [...new Set([...vault.keys(), ...legacyKeys()])];
    return {
      get length() { return allKeys().length; },
      key: index => allKeys()[index] || null,
      getItem(key) {
        const secured = vault.getItem(key);
        if (secured != null) return secured;
        const old = localStorage.getItem(key);
        if (old != null) {
          vault.setItem(key, old); // persist encrypted before removing legacy source
          localStorage.removeItem(key);
        }
        return old;
      },
      setItem(key, value) {
        vault.setItem(key, value);
        localStorage.removeItem(key);
      },
      removeItem(key) {
        vault.removeItem(key);
        localStorage.removeItem(key);
      },
    };
  }
  function interviewDrafts() {
    const drafts = [], prefix = 'hmr-draft:interview:';
    try {
      for (let i = 0; i < draftStorage().length; i++) {
        const key = draftStorage().key(i);
        if (!key || !key.startsWith(prefix)) continue;
        const id = key.slice(prefix.length);
        if (!/^[1-9][0-9]*$/.test(id)) continue;
        try {
          const entry = JSON.parse(draftStorage().getItem(key));
          if (!entry || typeof entry.base !== 'string' || typeof entry.snapshot !== 'string' || !Array.isArray(entry.conflicts || [])) continue;
          const record = JSON.parse(entry.snapshot);
          if (!record || typeof record !== 'object' || Array.isArray(record)) continue;
          if ((entry.conflicts || []).some(value => {
            if (typeof value !== 'string') return true;
            const parsed = JSON.parse(value);
            return !parsed || typeof parsed !== 'object' || Array.isArray(parsed);
          })) continue;
          const name = typeof record.header?.name === 'string' ? record.header.name.trim().slice(0, 160) : '';
          drafts.push({ id, name });
        } catch (_) { /* Keep unreadable drafts untouched. */ }
      }
    } catch (_) { return []; }
    return drafts;
  }
  function autosaver({ getRecord, getId, endpoint, status, errorText, draftKey, loadCurrent, onReconcile, equivalent }) {
    let saved = '', timer, saving = null, error = '', generation = 0, key = '', conflicts = [], storageError = false, unreadable = false, retries = 0, offline = false, verifying = null;
    const dirty = () => !!getRecord() && (conflicts.length > 0 || recordChanged(getRecord(), saved));
    const storageMessage = 'Local draft unavailable; keep this window open until saved';
    const conflictMessage = 'A previous local draft conflicts with saved data; resolve it before saving';
    function writeDraft() {
      if (!draftKey || !key || !getRecord()) return true;
      try {
        draftStorage().setItem(key, JSON.stringify({ base: saved, snapshot: JSON.stringify(getRecord()), conflicts }));
        storageError = false;
        return true;
      } catch (_) {
        storageError = true;
        status(storageMessage);
        return false;
      }
    }
    function removeDraft(snapshot, draftId) {
      if (!draftId) return;
      try {
        const entry = JSON.parse(draftStorage().getItem(draftId));
        if (entry && (entry.snapshot === snapshot || equivalent?.(entry.snapshot, snapshot)) && (!entry.conflicts || !entry.conflicts.length)) draftStorage().removeItem(draftId);
      } catch (_) { /* Preserve an unreadable draft for manual recovery. */ }
    }
    function scheduleRetry() {
      if (retries >= 5) return;
      clearTimeout(timer);
      timer = setTimeout(() => { retries++; save(); }, 10000);
    }
    function readDraft(draftId) {
      const raw = draftStorage().getItem(draftId);
      if (!raw) return null;
      const entry = JSON.parse(raw);
      if (typeof entry.base !== 'string' || typeof entry.snapshot !== 'string' || !Array.isArray(entry.conflicts || [])) throw new Error();
      for (const value of [entry.snapshot, ...(entry.conflicts || [])]) {
        if (typeof value !== 'string') throw new Error();
        const parsed = JSON.parse(value);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
      }
      return entry;
    }
    async function verifyCurrent() {
      if (verifying) return verifying;
      const currentGeneration = generation, id = getId();
      verifying = (async () => {
        try {
          if (!loadCurrent) throw new Error();
          const current = await loadCurrent(id);
          if (generation !== currentGeneration || !current || typeof current !== 'object') return false;
          const currentSnapshot = JSON.stringify(current);
          if (currentSnapshot !== saved && !equivalent?.(currentSnapshot, saved)) {
            const localSnapshot = JSON.stringify(getRecord());
            if (localSnapshot !== currentSnapshot) conflicts.push(localSnapshot);
            const record = getRecord();
            Object.keys(record).forEach(field => delete record[field]);
            Object.assign(record, current);
            saved = currentSnapshot;
            offline = false;
            writeDraft();
            if (conflicts.length) status(conflictMessage);
            if (onReconcile) onReconcile();
            return !conflicts.length;
          }
          offline = false;
          return true;
        } catch (_) {
          if (generation === currentGeneration) {
            error = 'Unable to verify saved data; retrying';
            status(storageError ? storageMessage : `Not saved - ${error}`);
            scheduleRetry();
          }
          return false;
        }
      })();
      const result = await verifying;
      verifying = null;
      return result;
    }
    async function save(force = false) {
      clearTimeout(timer);
      if (!getRecord()) return true;
      if (conflicts.length) { status(conflictMessage); return false; }
      if (offline && !(await verifyCurrent())) return false;
      if (saving) {
        await saving;
        if (saving) return save(force);
      }
      if (!dirty() && !force) return !error;
      const snapshot = JSON.stringify(getRecord()), id = getId(), currentGeneration = generation, currentKey = key;
      status('Saving...');
      const operation = (async () => {
        try {
          const result = await endpoint(id, JSON.parse(snapshot));
          removeDraft(snapshot, currentKey);
          if (generation === currentGeneration) {
            const confirmed = JSON.parse(snapshot);
            if (result && typeof result.revision === 'string') {
              confirmed.revision = result.revision; confirmed.saved = true;
              getRecord().revision = result.revision; getRecord().saved = true;
            }
            saved = JSON.stringify(confirmed);
            error = '';
            retries = 0;
            if (dirty()) writeDraft();
            else status(`Saved ${new Date().toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })}`);
          }
          return true;
        } catch (e) {
          if (generation === currentGeneration) {
            if (loadCurrent && /interview conflict/i.test(String(e.message || e))) {
              offline = true;
              await verifyCurrent();
              return false;
            }
            error = draftKey ? 'Unable to reach storage; retrying' : errorText(e);
            status(storageError ? storageMessage : `Not saved - ${error}`);
            scheduleRetry();
          }
          return false;
        }
      })();
      saving = operation;
      const ok = await operation;
      if (saving === operation) saving = null;
      if (generation !== currentGeneration) return false;
      if (ok && dirty()) return save();
      return ok;
    }
    if (draftKey && typeof window !== 'undefined') window.addEventListener('online', () => {
      if (dirty() && !conflicts.length) { retries = 0; save(); }
    });
    return {
      reset(record) {
        clearTimeout(timer);
        generation++;
        saved = JSON.stringify(record);
        error = '';
        retries = 0;
        conflicts = [];
        storageError = false;
        unreadable = false;
        offline = false;
        key = draftKey && getId() ? `hmr-draft:${draftKey()}` : '';
        let recovered = false;
        if (key) {
          try {
            const entry = readDraft(key);
            if (entry) {
              const draft = JSON.parse(entry.snapshot);
              if (!draft || typeof draft !== 'object' || Array.isArray(draft)) throw new Error();
              conflicts = entry.conflicts || [];
              const sameBase = entry.base === saved || equivalent?.(entry.base, saved);
              if (sameBase) {
                Object.keys(record).forEach((field) => delete record[field]);
                Object.assign(record, draft);
                recovered = recordChanged(record, saved);
              } else if (entry.snapshot !== saved) conflicts.push(entry.snapshot);
              if (conflicts.length) status(conflictMessage);
              else if (recovered) status('Recovered local draft - not saved');
              if (!sameBase) writeDraft();
              if (recovered && !conflicts.length) timer = setTimeout(save, 500);
            }
          } catch (_) {
            storageError = true;
            unreadable = true;
            status(storageMessage);
          }
        }
        return { recovered, conflict: !!conflicts.length, storageError };
      },
      offlineDraft() {
        try {
          const draftId = draftKey && getId() ? `hmr-draft:${draftKey()}` : '';
          const entry = draftId && readDraft(draftId);
          return entry ? JSON.parse(entry.snapshot) : null;
        } catch (_) { return null; }
      },
      resetOffline(record) {
        clearTimeout(timer);
        generation++;
        key = draftKey && getId() ? `hmr-draft:${draftKey()}` : '';
        try {
          const entry = key && readDraft(key);
          if (!entry || !loadCurrent) return false;
          saved = entry.base;
          conflicts = entry.conflicts || [];
          error = '';
          retries = 0;
          storageError = false;
          unreadable = false;
          offline = true;
          status(conflicts.length ? conflictMessage : 'Recovered local draft - awaiting connection');
          if (!conflicts.length) timer = setTimeout(save, 500);
          return true;
        } catch (_) { status(storageMessage); return false; }
      },
      dirty,
      hasConflict: () => conflicts.length > 0,
      save,
      changed() {
        clearTimeout(timer);
        retries = 0;
        if (!unreadable) writeDraft();
        if (conflicts.length) status(conflictMessage);
        else if (!storageError) status('Not saved');
        if (!conflicts.length) timer = setTimeout(save, 500);
      },
      resolveConflict(choice) {
        if (!conflicts.length || !['restore', 'discard'].includes(choice)) return false;
        const record = getRecord(), draft = JSON.parse(conflicts[0]);
        if (!record || !draft || typeof draft !== 'object' || Array.isArray(draft)) return false;
        try {
          const archiveKey = key + ':conflict-history';
          const history = JSON.parse(draftStorage().getItem(archiveKey) || '[]');
          history.push({ remote: JSON.stringify(record), local: conflicts[0] });
          draftStorage().setItem(archiveKey, JSON.stringify(history));
        } catch (_) { status(storageMessage); return false; }
        if (choice === 'restore') {
          const remote = JSON.parse(saved);
          draft.revision = remote.revision;
          if (remote.consent?.signed || remote.consent_file) { draft.consent = remote.consent; draft.consent_file = remote.consent_file; }
          Object.keys(record).forEach((field) => delete record[field]);
          Object.assign(record, draft);
        }
        conflicts.shift();
        writeDraft();
        if (conflicts.length) status(conflictMessage);
        else if (dirty()) { status('Not saved'); timer = setTimeout(save, 500); }
        else { removeDraft(JSON.stringify(getRecord()), key); status('Saved'); }
        return true;
      },
      async leave() {
        const ok = await save();
        const message = storageError
          ? 'Not saved and local draft unavailable. Leave and lose these changes?'
          : draftKey ? 'Not saved. Leave and keep the local draft for recovery?'
            : `Not saved - ${error}. Leave and discard these changes?`;
        if (!ok && !confirm(message)) return false;
        clearTimeout(timer);
        return true;
      },
    };
  }
  function nextVisitText(visits, now) {
    const day = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const today = day(now), tomorrowDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    const tomorrow = day(tomorrowDate);
    const next = (visits || []).filter((v) => ['confirmed', 'pathology_ready', 'sheet_ready'].includes(v.state) &&
      [today, tomorrow].includes(v.visit_date) && /^\d{2}:\d{2}$/.test(v.visit_time || ''))
      .map((v) => ({ v, at: new Date(`${v.visit_date}T${v.visit_time}:00`) }))
      .filter(({ at }) => at > now).sort((a, b) => a.at - b.at)[0];
    if (!next) return 'No visit today or tomorrow';
    const place = next.v.suburb ? ` &middot; ${esc(next.v.suburb)}` : '';
    if (next.v.visit_date === tomorrow) return `Next visit tomorrow ${next.v.visit_time}${place}`;
    const minutes = Math.ceil((next.at - now) / 60000), hours = Math.floor(minutes / 60), remainder = minutes % 60;
    return `Next visit ${next.v.visit_time}${place} &middot; in ${hours ? `${hours} h${remainder ? ' ' : ''}` : ''}${remainder ? `${remainder} min` : ''}`;
  }
  function defaultInterviewId(visits, now) {
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    const rows = (visits || []).filter((p) => p.visit_date === today && ['confirmed', 'pathology_ready', 'sheet_ready'].includes(p.state))
      .sort((a, b) => String(a.visit_time || '').localeCompare(String(b.visit_time || '')));
    return String((rows.find((p) => (p.visit_time || '99:99') >= now.toTimeString().slice(0, 5)) || rows[0])?.id || '');
  }
  function taskGroups(tasks) {
    return tasks
      .filter((t) => t.state === 'waiting')
      .reduce((groups, task) => {
        (groups[task.waiting_for || 'other'] ||= []).push(task);
        return groups;
      }, {});
  }
  function attentionLabel(action) {
    return ({ open_interview: 'Open interview', not_visited: 'Did not happen', visited: 'Record visit',
      open_messages: 'Open messages', offer: 'Offer a new time', pathology: 'Collect pathology',
      interview_sheet: 'Make sheet', open_report: 'Open report', claim: 'Open claim',
      followup1: 'Open follow-up form', followup2: 'Open follow-up form',
      followup1_claimed: 'Record claim', followup2_claimed: 'Record claim',
      expired: 'Mark expired',
      retry: 'Retry', check_phone: 'Check phone' })[action] || 'Open patient';
  }
  function attentionDetail(item, key) {
    const parts = [];
    if (key === 'today_visits' || key === 'prep') {
      parts.push(item.time || item.visit_time, item.suburb);
      if (item.pathology_done === false) parts.push('pathology missing');
      if (item.sheet_done === false) parts.push('sheet missing');
    } else if (key === 'offers_passed' && item.visit_date) {
      parts.push(`Offered for ${date(item.visit_date)}${item.visit_time ? ' ' + item.visit_time : ''}`);
    } else if (item.reply) parts.push(`"${item.reply}"`);
    else if (item.draft_id) parts.push(`Draft ${String(item.kind || 'message').replaceAll('_', ' ')} waiting to be sent`);
    else if (key === 'referrals' && item.days_left != null) {
      const days = Number(item.days_left);
      if (Number.isFinite(days)) parts.push(days < 0 ? `Expired ${-days} days ago` : `${days} days left`);
    }
    if (!parts.filter(Boolean).length) parts.push(item.detail);
    return parts.filter(Boolean).map(esc).join(' &middot; ');
  }
  function medicineItemId() { return globalThis.crypto.randomUUID().replaceAll('-', ''); }
  return {
    medicineItemId,
    localDate,
    esc,
    date,
    attentionLabel,
    attentionDetail,
    interviewHeader,
    interviewOutstanding,
    visitDefaultDate,
    sourceLabel,
    firstLines,
    group,
    sentence,
    steps,
    sectionOf, toBook, stepLabel, stageText, stageClass, hasNextStep, flagWords, stageActions, urgencySort,
    plainSteps,
    stepName,
    taskGroups,
    nextVisitText,
    defaultInterviewId,
    bulkSteps,
    patientPathway,
    commonStep,
    suburb,
    displayAddress,
    recordChanged,
    addRow,
    removeRow,
    moveFinding,
    undoFinding,
    reviewed,
    findingFromResult,
    growTextarea,
    genericName,
    settingsDiff,
    consentValidation,
    dateTextHint,
    pathologyDateHints,
    tableInput,
    showInterviewRefresh,
    interviewDrafts,
    autosaver,
  };
})();
if (typeof module !== 'undefined') module.exports = H;
