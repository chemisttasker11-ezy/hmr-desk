let referralRows = [];

async function intake() {
  $('screen').innerHTML = `<div class="actions"><button class="primary" data-referral-pick="inbox">Check TO SORT</button><button data-referral-pick="files">Choose PDFs</button><button data-referral-pick="folder">Choose inbox folder</button></div>
    <p>Choose a folder, select PDFs or drop PDFs here. Each referral is reviewed before a patient is added; the original stays in place.</p>
    <div id="referral-drop" class="card" tabindex="0" aria-label="Drop referral PDFs here">Drop PDF files here</div>
    <p id="referral-status" role="status"></p><div id="referral-results"></div>`;
  renderReferrals();
  formOpen = referralRows.some(row => row.dirty && row.status !== 'added');
}

function renderReferrals() {
  const target = $('referral-results');
  if (!target) return;
  const labels = {name:'Patient name', dob:'Date of birth', gp:'GP', referral_date:'Referral date', medicare:'Medicare', irn:'IRN', ihi:'IHI'};
  const counts = ['review', 'duplicate', 'rejected', 'error', 'added'].map(status => `${status}: ${referralRows.filter(row => row.status === status).length}`).join(' · ');
  target.innerHTML = `${referralRows.length ? `<p>${esc(counts)}</p>` : ''}` + referralRows.map((row, i) => `<article class="card"><h3>${esc(row.file)}</h3><p><strong>${esc(({review:'Ready for review',duplicate:'Possible duplicate',rejected:'Not recognised as a referral',error:'Could not read PDF',added:'Added'})[row.status] || row.status)}</strong>${row.message ? ': ' + esc(row.message) : ''}</p>
    ${row.status === 'duplicate' ? `<p>${row.duplicate_kind === 'identity' ? 'The extracted name matches another patient or referral. Check and correct the details before adding; an existing name cannot be added twice.' : 'This PDF has already been reviewed or added.'}</p>` : ''}
    ${row.flags?.length ? `<p class="flag">${row.flags.map(esc).join('<br>')}</p>` : ''}
    ${row.status === 'review' || (row.status === 'duplicate' && row.duplicate_kind === 'identity' && row.kind === 'referral') ? `<form data-referral-commit="${i}" class="form">${['name','dob','gp','referral_date','clinic','phone','address','suburb','sex','medicare','irn','ihi'].map(k => `<label>${esc(labels[k] || k)}<input name="${k}" value="${esc(row.fields?.[k] || '')}"></label>`).join('')}<button class="primary">Confirm and add patient</button><p class="error" role="alert"></p></form>` : ''}
    ${row.patient_id ? `<button data-referral-open="${Number(row.patient_id)}">Open patient</button>` : ''}</article>`).join('');
}

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-referral-pick], [data-referral-open]');
  if (!button) return;
  try {
    if (button.dataset.referralOpen) return await openPatientWorkspace(Number(button.dataset.referralOpen), 'Overview', 'patient');
    button.disabled = true;
    $('referral-status').textContent = 'Reading referrals…';
    const result = await hmr.referralPick(button.dataset.referralPick);
    if (result) referralRows.push(...result.rows);
    renderReferrals();
    if ($('referral-status')) $('referral-status').textContent = result ? 'Review the results below.' : '';
  } catch (error) { if ($('referral-status')) $('referral-status').textContent = errorText(error); }
  finally { button.disabled = false; }
});

document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-referral-commit]');
  if (!form) return;
  event.preventDefault();
  const row = referralRows[Number(form.dataset.referralCommit)], button = form.querySelector('button');
  button.disabled = true;
  try {
    const result = await hmr.api('POST', '/api/referrals/commit', { token: row.token, fields: Object.fromEntries(new FormData(form)) });
    row.status = 'added'; row.patient_id = result.patient_id;
    row.dirty = false;
    if (page === 'intake') formOpen = referralRows.some(item => item.dirty && item.status !== 'added');
    renderReferrals();
  } catch (error) { form.querySelector('.error').textContent = errorText(error); button.disabled = false; }
});

document.addEventListener('dragover', event => {
  if (event.target.closest?.('#referral-drop')) event.preventDefault();
});
document.addEventListener('input', event => {
  const form = event.target.closest?.('[data-referral-commit]');
  if (!form) return;
  const row = referralRows[Number(form.dataset.referralCommit)];
  row.fields = Object.fromEntries(new FormData(form));
  row.dirty = true;
  formOpen = true;
});
hmr.onReferralDrop(result => {
  const status = $('referral-status');
  if (result.loading) { if (status) status.textContent = 'Reading referrals…'; return; }
  if (result.error) { if (status) status.textContent = result.error; return; }
  referralRows.push(...result.rows);
  renderReferrals();
  if (status) status.textContent = 'Review the results below.';
});
