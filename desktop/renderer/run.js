let runTimer;
let runTasks = [];
let runStepsCatalog = [];
let runMessage = '';
let runPending = false;
let pickerOpen = false;
const siteNames = { mhr: 'My Health Record', emims: 'eMIMS', ppa: 'PPA' };
const tickedSteps = new Set();
const obsoleteSteps = new Set(['interview_spec']);
const pickerSteps = [
  ...H.bulkSteps,
  ...Object.keys(H.steps).filter((step) => !H.bulkSteps.includes(step) && !obsoleteSteps.has(step)),
];
function availableRunSteps(steps) {
  return runStepsCatalog.length ? steps.filter(step => runStepsCatalog.some(item => item.name === step)) : [];
}
function stepCheckboxes(steps) {
  steps = availableRunSteps(steps);
  return `<div class="step-checkboxes">${steps.map((step) =>
    `<label><input type="checkbox" data-run-step="${esc(step)}" ${tickedSteps.has(step) ? 'checked' : ''}>${esc(runStepsCatalog.find(item => item.name === step)?.label || H.steps[step] || step)}</label>`,
  ).join('')}</div><button type="button" data-steps-all>Tick all</button> <button type="button" data-steps-none>Untick all</button>`;
}
function selectedSteps(steps) {
  return availableRunSteps(steps).filter((step) => tickedSteps.has(step));
}
function updateStepButton() {
  const button = document.querySelector('[data-bulk-step], [data-picker-submit]');
  if (button) button.disabled = runPending || !selectedSteps(page === 'patients' ? H.bulkSteps : pickerSteps).length;
  const count = document.querySelector('#steps-count');
  if (count) count.textContent = `Steps: ${selectedSteps(H.bulkSteps).length} ticked`;
}
function skippedText(skipped) {
  return (skipped || []).map((item) => {
    const name =
      patients.find((p) => Number(p.id) === Number(item.patient_id))?.name ||
      (item.patient_id == null ? 'Batch' : `Patient ${item.patient_id}`);
    return `${name} - ${H.stepLabel(item.step)}: ${item.reason}`;
  });
}
async function enqueue(steps, ids) {
  if (runPending) return;
  runPending = true;
  const runButtons = document.querySelectorAll('[data-bulk-step], [data-bulk-flow], [data-picker-submit], [data-run-ready]');
  runButtons.forEach((b) => { b.disabled = true; });

  const stepList = steps === 'auto' ? ['auto'] : (Array.isArray(steps) ? steps : [steps]);
  const patientList = ids === 'ready' ? ['ready'] : (Array.isArray(ids) ? ids : [ids]);
  if (steps !== 'auto' && !runStepsCatalog.length) {
    try { const catalogue = await hmr.api('GET', '/api/run'); runStepsCatalog = catalogue.steps || []; runTasks = catalogue.tasks || []; } catch (_) {}
  }
  if (steps !== 'auto' && (!runStepsCatalog.length || stepList.some(step => !runStepsCatalog.some(item => item.name === step)))) {
    const invalid = stepList.filter(step => !runStepsCatalog.some(item => item.name === step));
    runPending = false; runMessage = runStepsCatalog.length ? `Nothing started: invalid steps: ${invalid.join(', ')}. Refresh and choose available steps.` : 'Nothing started: step catalogue unavailable. Refresh and try again.';
    if ($('queue-message')) $('queue-message').textContent = runMessage;
    runButtons.forEach(b => { b.disabled = false; }); updateStepButton(); return;
  }
  const submittedStepsCount = stepList.length;
  const submittedPatientsCount = patientList.length;

  const description = `${steps === 'auto' ? 'full flow' : `${submittedStepsCount} step(s)`} for ${ids === 'ready' ? 'ready patients' : `${submittedPatientsCount} patient(s)`}`;
  runMessage = `Submitting ${description}...`;
  if (page === 'patients' && $('queue-message')) $('queue-message').textContent = runMessage;

  try {
    const result = await hmr.api('POST', '/api/run', { steps, patient_ids: ids });
    const queued = result.queued ?? result.enqueued ?? [];
    const count = Array.isArray(queued) ? queued.length : (typeof queued === 'number' ? queued : 0);
    const skipped = skippedText(result.skipped);
    runMessage = `${count} task(s) queued (${description}).` + (skipped.length ? '\n' + skipped.join('\n') : '');
    try {
      const qRes = await hmr.api('GET', '/api/run');
      runTasks = qRes.tasks || [];
      if (qRes.steps) runStepsCatalog = qRes.steps;
    } catch (_err) {}
  } catch (error) {
    const err = errorText(error);
    runMessage = `Nothing started: ${err}. Please check step readiness and corrective instructions before retrying.`;
  } finally {
    runPending = false;
    updateStepButton();
  }
  if (page === 'patients') {
    if ($('queue-message')) $('queue-message').textContent = runMessage;
    renderPatients();
  }
  if (page === 'run') await runScreen();
}
async function runScreen() {
  clearTimeout(runTimer);
  try {
    const [list, queue] = await Promise.all([hmr.api('GET', '/api/patients'), hmr.api('GET', '/api/run')]);
    if (page !== 'run') return;
    patients = list.patients;
    runTasks = queue.tasks || [];
    if (queue.steps) runStepsCatalog = queue.steps;
    if (pickerOpen && $('run-picker')) {
      runTimer = setTimeout(runScreen, 3000);
      return;
    }
    const older = (t) => t.state === 'failed' && t.started && new Date(t.started).getTime() < Date.now() - 7 * 86400000;
    const table = (tasks) => `<table><thead><tr><th>Patient</th><th>Step</th><th>State</th><th>Started</th><th>Actions</th></tr></thead><tbody>${tasks.map((t) => {
      const pId = t.patient_id;
      const pName = t.patient_name || t.name || patients.find((p) => p.id === pId)?.name || 'Batch';
      const waitReason = t.waiting_for ? `Waiting for ${siteNames[t.waiting_for] || t.waiting_for}` : (t.reason || '');
      return `<tr><td>${pId ? `<button data-patient="${esc(pId)}">${esc(pName)}</button>` : esc(pName)}</td><td>${esc(H.stepLabel(t.step))}</td><td><span class="status-chip task-state state-${esc(t.state)}">${esc(t.state)}</span>${waitReason ? ` <small class="muted">(${esc(waitReason)})</small>` : ''}${t.state === 'failed' && t.output ? `<details><summary>Output</summary><pre>${esc(t.output)}</pre></details>` : ''}</td><td>${esc(date(t.started))} ${esc((t.started || '').slice(11, 16))}</td><td>${['queued', 'waiting'].includes(t.state) ? `<button data-task-cancel="${esc(t.id)}">Cancel</button>` : t.state === 'failed' ? `<button data-task-retry="${esc(t.id)}">Retry</button>` : ''}${pId ? ` <button data-patient="${esc(pId)}">Open patient</button>` : ''}</td></tr>`;
    }).join('')}</tbody></table>`;
    const recent = runTasks.filter((t) => !older(t)), old = runTasks.filter(older);
    $('screen').innerHTML = `<div class="actions"><button class="primary" data-run-ready ${runPending ? 'disabled' : ''}>Run everything that is ready</button><button data-run-pick>Run steps for...</button></div>
      <p class="muted">The flow never sends SMS, sends reports or submits claims.</p><div id="run-picker-area"></div>
      <p class="queue-message" role="status" aria-live="polite">${esc(H.runStatusText(runMessage, runTasks))}</p><h2>Tasks</h2>${recent.length ? table(recent) : '<p class="empty">No tasks yet. Steps you run for a patient show here.</p>'}${old.length ? `<details><summary>Older (${old.length})</summary>${table(old)}</details>` : ''}`;
    if (pickerOpen) renderRunPicker(true);
  } catch (error) {
    if (page === 'run') $('screen').innerHTML = `<p class="error">${esc(errorText(error))}</p>`;
  }
  if (page === 'run')
    runTimer = setTimeout(
      runScreen,
      runTasks.some((t) => ['queued', 'running', 'waiting'].includes(t.state)) ? 3000 : 30000,
    );
}
function renderRunPicker() {
  const area = $('run-picker-area');
  if (!area) return;
  area.innerHTML = `<form id="run-picker" class="card"><strong>Steps</strong>
    ${stepCheckboxes(pickerSteps)}
    <div class="picker-patients">${patients.map((p) =>
      `<label><input type="checkbox" name="patient" value="${esc(p.id)}">${esc(p.name)}</label>`,
    ).join('')}</div>
    <button class="primary" data-picker-submit ${selectedSteps(pickerSteps).length ? '' : 'disabled'}>Run ticked steps</button>
    <button type="button" data-picker-close>Cancel</button></form>`;
}
async function submitRunPicker(form) {
  const ids = new FormData(form).getAll('patient').map(Number);
  const steps = selectedSteps(pickerSteps);
  if (!steps.length) return;
  if (!ids.length) {
    alert('Select at least one patient.');
    return;
  }
  pickerOpen = false;
  await enqueue(steps, ids);
}
async function runClick(b) {
  if (b.dataset.runReady !== undefined) {
    const ready = patients.filter(
      (p) =>
        H.stepName(p.next_step) && !['intake_dry', 'intake_apply', 'register_xlsx'].includes(H.stepName(p.next_step)),
    );
    const preview = ready.map((p) => `${p.name}: ${H.stepLabel(p.next_step)}`).join('\n');
    if (confirm(`Run the flow for everyone ready? \n${ready.length} patient(s) with a listed next step:\n${preview}`)) {
      await enqueue('auto', 'ready');
    }
    return true;
  }
  if (b.dataset.runPick !== undefined) {
    pickerOpen = true;
    renderRunPicker(true);
    return true;
  }
  if (b.dataset.pickerClose !== undefined) {
    pickerOpen = false;
    $('run-picker-area').innerHTML = '';
    return true;
  }
  if (b.dataset.taskRetry !== undefined) {
    const task = runTasks.find((t) => String(t.id) === b.dataset.taskRetry);
    if (task) await enqueue([task.step], task.patient_id == null ? [] : [Number(task.patient_id)]);
    return true;
  }
  if (b.dataset.taskCancel !== undefined) {
    try {
      await hmr.api('POST', `/api/run/${encodeURIComponent(b.dataset.taskCancel)}/cancel`, {});
    } catch (error) {
      runMessage = errorText(error);
    }
    if (page === 'run') await runScreen(); else await refresh();
    return true;
  }
  if (b.dataset.stepsAll !== undefined || b.dataset.stepsNone !== undefined) {
    const steps = page === 'patients' ? H.bulkSteps : pickerSteps;
    for (const step of availableRunSteps(steps)) {
      if (b.dataset.stepsAll !== undefined && !['interview_assist', 'report_assist', 'report_draft'].includes(step)) tickedSteps.add(step);
      else if (b.dataset.stepsNone !== undefined) tickedSteps.delete(step);
    }
    document.querySelectorAll('[data-run-step]').forEach((input) => { input.checked = tickedSteps.has(input.dataset.runStep); });
    updateStepButton();
    return true;
  }
  if (b.dataset.bulkClear !== undefined) {
    checkedPatients.clear();
    renderPatients();
    return true;
  }
  if (b.dataset.bulkStep !== undefined || b.dataset.bulkFlow !== undefined) {
    const steps = b.dataset.bulkStep !== undefined ? selectedSteps(H.bulkSteps) : 'auto';
    if (!checkedPatients.size || (Array.isArray(steps) && !steps.length)) return true;
    await enqueue(steps, [...checkedPatients]);
    return true;
  }
  return false;
}
