let medicinePatient = null;
let medicineData = null;
async function reports() {
  const [list, agents] = await Promise.all([hmr.api('GET', '/api/patients'), hmr.api('GET', '/api/agents')]);
  if (page !== 'reports') return;
  patients = list.patients;
  const agent = agents.per_step.report_draft || agents.default || 'No agent selected';
  const rows = patients.filter((p) => ['visited', 'report_drafted', 'signed_off'].includes(p.state));
  const details = await Promise.allSettled(
    rows.map(async (p) => {
      const [detail, spec] = await Promise.all([
        hmr.api('GET', `/api/patients/${encodeURIComponent(p.id)}`),
        hmr.api('GET', `/api/patients/${encodeURIComponent(p.id)}/report`),
      ]);
      return { ...detail, reportSpec: spec };
    }),
  );
  if (page !== 'reports') return;
  $('screen').innerHTML = `<p id="report-message" role="status">${esc(runMessage)}</p>
    <h2>Reports to write (${rows.length})</h2>${rows.map((p, i) => (details[i].status === 'fulfilled' ? reportRow(p, details[i].value, agent) : reportError(p, details[i].reason))).join('') || '<p class="empty">No reports waiting</p>'}<div id="detail" class="detail drawer" role="dialog" aria-label="Patient" hidden></div>`;
  if (medicinePatient && medicineData) renderMedicines();
}
function reportError(p, error) {
  const message = /patient folder missing/i.test(error.message)
    ? 'This patient has no folder yet. Use Edit details or file the referral first.'
    : errorText(error);
  return `<div class="card"><strong>${esc(p.name)}</strong><p class="error">${esc(message)}</p></div>`;
}
function reportRow(p, detail, agent) {
  const steps = Object.fromEntries((detail.steps || []).map((step) => [step.name, step]));
  const interactions = steps.interactions;
  const visited = ['visited', 'report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state);
  const medicines = {
    ready: visited,
    done: visited && !!interactions && interactions.reason !== 'confirm the medicine list first',
    reason: visited ? '' : 'Visit not recorded',
  };
  const build = steps.report_build;
  const sign = {
    done: ['signed_off', 'sent', 'claimed'].includes(p.state),
    ready: ['visited', 'report_drafted'].includes(p.state) && !!build?.done,
    reason: 'Word report must be built first',
  };
  const start = steps.report_start;
  const edit = {
    ready: !!start?.done || !!build?.ready || !!build?.done,
    reason: start?.reason || 'start the report first',
  };
  const hasFindings = !!detail.reportSpec?.issues?.length;
  const buildStatus =
    build?.ready && !hasFindings ? { ...build, ready: false, reason: 'add at least one finding' } : build;
  const buttons = [
    ['medicines', 'Check medicines for interaction check', medicines],
    ['interactions', 'Check interactions', interactions],
    ['report_start', 'Start report', start],
    ['edit', 'Edit report', edit],
    ['build', 'Build Word', buildStatus],
    ['pdf', 'Build Word + PDF', buildStatus],
    ['sign', 'Signed off', sign],
  ];
  const next = String(p.next_step || '').toLowerCase();
  const target = ({ 'confirm medicines': 'medicines', 'check interactions': 'interactions', 'start report': 'report_start', 'add findings': 'edit', 'build report': 'build', 'sign off': 'sign' })[next];
  const primary = target ? buttons.findIndex(([step]) => step === target) : (next ? -1 : buttons.findIndex(([, , status]) => status?.ready && !status?.done));
  const renderButton = ([step, label, status], index) => {
    const attr = step === 'medicines' ? `data-medicines="${esc(p.id)}"`
      : step === 'sign' ? `data-sign-off="${esc(p.id)}"`
      : ['edit', 'build', 'pdf'].includes(step) ? `data-report-open="${esc(p.id)}" data-build="${step}"`
      : `data-report-step="${esc(step)}" data-id="${esc(p.id)}"`;
    const disabled = !status?.ready || (status?.done && !['medicines', 'edit', 'build', 'pdf'].includes(step));
    return `<div><button ${index === primary ? 'class="primary"' : ''} ${attr} ${disabled ? 'disabled' : ''}>${esc(label)}${status?.done ? ' &#10003; Done' : ''}</button>${!status?.ready && !status?.done ? `<small>${esc(status?.reason || 'Step unavailable')}</small>` : ''}</div>`;
  };
  const main = next === 'send report' ? `<button class="primary" data-claim-action="report_sent" data-id="${esc(p.id)}">Mark report sent</button>`
    : primary >= 0 ? renderButton(buttons[primary], primary) : `<p>${esc(p.next_step || 'Review the report')}</p>`;
  return `<div class="card"><div class="card-head"><h3>${esc(p.name)}</h3><span class="status-chip stage-${H.stageClass(p.stage)}">${esc(p.status_text || p.state)}</span></div>
    <div class="report-steps"><strong>Next action</strong>${main}<details><summary>Other report steps</summary><div class="report-steps">${buttons.map((item, i) => i === primary ? '' : renderButton(item, i)).join('')}<button data-report-folder="${esc(p.id)}">Open folder</button></div></details></div>
    <div id="medicines-${esc(p.id)}"></div></div>`;
}
function renderMedicines() {
  const area = $(`medicines-${medicinePatient}`);
  if (!area) return;
  if (page === 'reports') area.closest('.card').querySelector('.report-steps .primary')?.classList.remove('primary');
  area.innerHTML = `<form id="medicines-form"><h3>Check medicines for interaction check</h3>
    <p>These are the medicines the patient is taking, copied from the interview. Check the generic names (and add brands if useful) &#8212; this list is used for the eMIMS interaction check. Stopped medicines are left out.</p>
    ${medicineData.proposed && (medicineData.meds.length || medicineData.allergies.length) ? `<p>Copied from the interview &#8212; ${medicineData.meds.length} medicines, ${medicineData.allergies.length} allergies</p>` : ''}
    ${(medicineData.interview_usage || []).length ? `<p>Review interview medicine use below. Confirm only medicines currently used; a different strength or formulation may still be used when another has stopped.</p><ul>${medicineData.interview_usage.map(item => `<li>${esc(item.source)} — ${esc(item.name)}: ${esc(item.detail)} ${esc((item.directions || []).filter(Boolean).join(" | "))}</li>`).join('')}</ul>` : ''}
    <div id="medicine-rows">${medicineData.meds
      .map(
        (med, i) => `<div class="medicine-row">
    <label>Generic name<input name="generic" value="${esc(med[0] || '')}"></label>
    <label>Brand<input name="brand" value="${esc(med[1] || '')}"></label>
    ${(medicineData.interview_usage || []).some(item => item.status === 'not_using') ? `<label>If a stopped medicine shares an ingredient, enter the exact name of the different medicine currently taken above and select it below<select name="alternative"><option value="">Choose if needed</option>${(medicineData.interview_usage || []).map((item, index) => item.status === 'taking' ? `<option value="${index}" ${JSON.stringify(medicineData.alternatives?.[i]) === JSON.stringify(item) ? 'selected' : ''}>${esc(item.name)} — ${esc(item.source)} — ${esc((item.directions || []).filter(Boolean).join(' | '))}</option>` : '').join('')}</select></label>` : ''}
    <button type="button" data-remove-medicine="${i}">Remove</button></div>`,
      )
      .join('')}</div>
    <button type="button" data-add-medicine>Add medicine</button>
    <label>Allergies, one per line<textarea name="allergies">${esc(medicineData.allergies.join('\n'))}</textarea>
    </label><p class="error" role="alert"></p><button class="primary">Save medicines</button>
    <button type="button" data-close-medicines>Cancel</button></form>`;
}
function readMedicines() {
  const form = $('medicines-form');
  medicineData.meds = [...form.querySelectorAll('.medicine-row')].map((row) => [
    row.querySelector('[name=generic]').value,
    row.querySelector('[name=brand]').value,
  ]);
  medicineData.alternatives = [...form.querySelectorAll('.medicine-row')].map(row => {
    const choice = row.querySelector('[name=alternative]')?.value;
    return choice === undefined || choice === '' ? null : medicineData.interview_usage[Number(choice)];
  });
  medicineData.allergies = form.elements.allergies.value
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
}
async function reportClick(b) {
  if (b.dataset.reportOpen) {
    await openReport(b.dataset.reportOpen);
    if (reportRecord && ['build', 'pdf'].includes(b.dataset.build)) await buildReport(b.dataset.build === 'pdf');
    return true;
  }
  if (b.dataset.medicines) {
    medicinePatient = b.dataset.medicines;
    try {
      medicineData = await hmr.api('GET', `/api/patients/${encodeURIComponent(medicinePatient)}/meds`);
      medicineData.meds ||= [];
      medicineData.allergies ||= [];
      medicineData.alternatives = medicineData.meds.map(() => null);
      formOpen = true;
      renderMedicines();
    } catch (error) {
      $('report-message').textContent = errorText(error);
    }
    return true;
  }
  if (b.dataset.addMedicine !== undefined || b.dataset.removeMedicine !== undefined) {
    readMedicines();
    if (b.dataset.addMedicine !== undefined) { medicineData.meds.push(['', '']); medicineData.alternatives.push(null); }
    else { const i = Number(b.dataset.removeMedicine); medicineData.meds.splice(i, 1); medicineData.alternatives.splice(i, 1); }
    renderMedicines();
    return true;
  }
  if (b.dataset.closeMedicines !== undefined) {
    medicinePatient = null;
    medicineData = null;
    formOpen = false;
    if (page === 'reports') await reports(); else await showPatient(selected);
    return true;
  }
  if (b.dataset.reportStep) {
    await enqueue([b.dataset.reportStep], [Number(b.dataset.id)]);
    if (b.dataset.reportStep === 'interactions' && /^[1-9]\d* task\(s\) queued/.test(runMessage)) {
      if (runMessage.includes('\n')) alert(runMessage);
      await navigate('emims');
    } else $('report-message').textContent = runMessage;
    return true;
  }
  if (b.dataset.reportFolder) {
    await hmr.openPatientFolder(Number(b.dataset.reportFolder));
    return true;
  }
  if (b.dataset.signOff) {
    await hmr.api('POST', `/api/patients/${encodeURIComponent(b.dataset.signOff)}/action`, { action: 'signed_off' });
    if (page === 'reports') await reports(); else await showPatient(b.dataset.signOff);
    return true;
  }
  return false;
}
