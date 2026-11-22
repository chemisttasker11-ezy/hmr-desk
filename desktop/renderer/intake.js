let referralRows = [];
let referralListings = [];
// Discovered and submitted come from the folder listing. How many were reviewed is only what the engine returned as rows.
function listingNotice(listing) {
  const n = listing.found, p = listing.pdfs;
  return `Discovered ${n} item${n === 1 ? '' : 's'} in the folder: ${p} PDF${p === 1 ? '' : 's'} submitted for review, ${listing.skippedTotal} not submitted.`;
}
const REFERRAL_IDENTITY_KEYS = ['name','dob','gp','gp_provider','clinic','clinic_address','clinic_phone','referral_date','phone',
  'address','suburb','sex','medicare','irn','ihi'];
function referralReviewFields(form) {
  const data = new Map(new FormData(form));
  return {
    fields: Object.fromEntries(REFERRAL_IDENTITY_KEYS.map(key => [key, String(data.get(key) || '')])),
    clinical: {
      conditions: String(data.get('clinical_conditions') || ''),
      allergies: String(data.get('clinical_allergies') || ''),
      medicines: String(data.get('clinical_medicines') || ''),
      observations: String(data.get('clinical_observations') || ''),
      allergies_status: String(data.get('clinical_allergies_status') || 'unknown'),
      source_pages: Object.fromEntries(['conditions','allergies','medicines','observations'].map(key =>
        [key, Number(data.get('clinical_page_' + key) || 0)])),
      reviewed_by: String(data.get('clinical_reviewer') || ''),
      confirmed: data.get('clinical_confirmed') === 'on',
    },
  };
}


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
  const labels = {name:'Patient name', dob:'Date of birth', gp:'GP', gp_provider:'GP provider number', clinic_address:'Practice address', clinic_phone:'Practice phone', referral_date:'Referral date', medicare:'Medicare', irn:'IRN', ihi:'IHI'};
  const shown = referralRows.filter(row => !row.userSkipped);
  const counts = ['review', 'manual', 'duplicate', 'rejected', 'error', 'added'].map(status => `${status}: ${shown.filter(row => row.status === status).length}`).concat(referralRows.length - shown.length ? [`skipped by you: ${referralRows.length - shown.length}`] : []).join(' · ');
  const listingHtml = referralListings.map(listing => `<section class="referral-listing" role="status"><p>${esc(listingNotice(listing))}</p>${listing.skippedTotal ? `<details><summary>Not submitted (${listing.skippedTotal})</summary><ul>${listing.skipped.map(item => `<li>${esc(item.name)}: ${esc(item.reason)}</li>`).join('')}${listing.skippedTotal > listing.skipped.length ? `<li>and ${listing.skippedTotal - listing.skipped.length} more</li>` : ''}</ul></details>` : ''}</section>`).join('');
  target.innerHTML = listingHtml + `${referralRows.length ? `<p>${esc(counts)}</p>` : ''}` + referralRows.map((row, i) => row.userSkipped ? '' : `<article class="card"><h3>${esc(row.file)}</h3><p><strong>${esc(({review:'Ready for review',manual:'Requires pharmacist classification',duplicate:'Possible duplicate',rejected:'Not recognised as a referral',error:'Could not read PDF',added:'Added'})[row.status] || row.status)}</strong>${row.message ? ': ' + esc(row.message) : ''}</p>
    ${row.status === 'duplicate' ? `<p>${row.duplicate_kind === 'identity' ? 'The extracted name matches an existing patient or another referral. Compare date of birth and identifiers before adding. A different person with the same name requires explicit acknowledgement.' : 'This PDF has already been reviewed or added.'}</p>` : ''}
    ${row.status === 'manual' ? '<p>This document was not recognised automatically. Verify the original PDF is a genuine Home Medicines Review referral before entering identifiers and creating a patient. No unknown information will be filled automatically.</p>' : ''}
    ${row.token ? `<button type="button" data-referral-source="${esc(row.token)}">Open original PDF for visual page comparison</button>` : ''}
    ${row.flags?.length ? `<section class="referral-extraction-warnings" aria-label="Original extraction warnings"><h4>Original extraction warnings (before your review)</h4><p>${row.status === 'added' ? 'The patient was added with the fields you reviewed. ' : ''}These warnings describe the original extraction, not a check of your corrected fields. They are kept with the source for review.</p><p class="flag">${row.flags.map(esc).join('<br>')}</p></section>` : ''}
    ${row.annotation_evidence?.some(page => page.count > 0) ? `<details class="referral-annotation-review"><summary>Review typed PDF annotations separately (unverified)</summary><p>These may be GP additions or later notes. No author is inferred. Compare with the original PDF before accepting any field.</p>${row.annotation_evidence.map((page, index) => page.count ? `<section class="card"><h4>Source page ${index + 1} — ${Number(page.count)} FreeText annotation(s)</h4>${(page.details || []).map(annotation => `<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(annotation.text_unverified || 'Annotation without readable text; inspect original PDF')}</pre>`).join('')}${page.truncated ? '<p>Additional annotations are present; open the original PDF for full review.</p>' : ''}</section>` : '').join('')}</details>` : ''}
    ${row.page_previews?.length ? `<details class="referral-source-preview"><summary>Review extracted PDF pages (${row.page_previews.length} shown)</summary><div class="referral-page-preview">${row.page_previews.map(page => `<section class="card"><h4>Source page ${esc(page.page)} — ${page.method === 'ocr' ? 'OCR (unconfirmed)' : page.method === 'text+unread_image' ? 'Searchable text + substantial PDF image (pixel review required)' : 'PDF text (unconfirmed)'}</h4><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(page.text || 'No readable text; inspect the original PDF')}</pre>${page.ocr_comparison_unverified ? `<details class="referral-ocr-comparison"><summary>Compare independent local OCR with native PDF text (unverified)</summary><p>This OCR may duplicate or contradict the source text. Never accept a medication or direction without checking the original PDF pixels.</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(page.ocr_comparison_unverified)}</pre></details>` : ''}</section>`).join('')}</div><p>Compare these unconfirmed values to the original PDF before adding the patient. OCR is not evidence of correctness.</p></details>` : ''}
    ${row.status === 'review' || row.status === 'manual' || (row.status === 'duplicate' && row.duplicate_kind === 'identity') ? `<form data-referral-commit="${i}" class="form">${['name','dob','gp','gp_provider','referral_date','clinic','clinic_address','clinic_phone','phone','address','suburb','sex','medicare','irn','ihi'].map(k => `<label>${esc(labels[k] || k)}<input name="${k}" value="${esc(row.fields?.[k] || '')}"></label>`).join('')}
    <fieldset><legend>Clinical source review — not automatically inferred</legend>
      <p>Only enter facts you can verify on the original PDF page. Unknown allergies are not the same as an explicitly documented absence of allergies.</p>
      <label>Reviewing pharmacist<input name="clinical_reviewer" value="${esc(row.clinical?.reviewed_by || '')}"></label>
      <label>Conditions and indications<textarea name="clinical_conditions" rows="3">${esc(row.clinical?.conditions || '')}</textarea></label>
      <label>Conditions source page<input name="clinical_page_conditions" type="number" min="0" step="1" value="${esc(row.clinical?.source_pages?.conditions ?? 0)}"></label>
      <label>Prescribed medicines / directions (one medicine per line)<textarea name="clinical_medicines" rows="4">${esc(row.clinical?.medicines || '')}</textarea></label>
      <label>Medicines source page<input name="clinical_page_medicines" type="number" min="0" step="1" value="${esc(row.clinical?.source_pages?.medicines ?? 0)}"></label>
      <label>Observations / measurements<textarea name="clinical_observations" rows="3">${esc(row.clinical?.observations || '')}</textarea></label>
      <label>Observations source page<input name="clinical_page_observations" type="number" min="0" step="1" value="${esc(row.clinical?.source_pages?.observations ?? 0)}"></label>
      <label>Allergy documentation state<select name="clinical_allergies_status">
        ${[['unknown','Unknown / not specified'],['explicit_none','Explicitly documented none'],['listed','Allergies listed']].map(([value,label]) =>
          `<option value="${value}" ${(row.clinical?.allergies_status || 'unknown') === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
      <label>Documented allergy details<textarea name="clinical_allergies" rows="2">${esc(row.clinical?.allergies || '')}</textarea></label>
      <label>Allergies source page<input name="clinical_page_allergies" type="number" min="0" step="1" value="${esc(row.clinical?.source_pages?.allergies ?? 0)}"></label>
      <label><input type="checkbox" name="clinical_confirmed" ${row.clinical?.confirmed ? 'checked' : ''}>
        I checked each clinical field against its own original PDF page (enter the page where that fact appears). Preserve all other information as unconfirmed.</label>
    </fieldset>
    ${row.kind !== 'referral' ? '<fieldset><legend>Manual source classification</legend><label><input type="checkbox" data-manual-referral required> I inspected the original PDF and confirm it is an HMR referral for this patient. The document and all clinical details remain unconfirmed until reviewed.</label><p><button type="button" data-referral-skip="' + i + '">Not a referral, skip this file</button> <small class="muted">Only removes it from this list. Nothing is added or recorded, and the PDF stays where it is.</small></p></fieldset>' : ''}
    ${row.status === 'duplicate' && row.duplicate_kind === 'identity' ? `<fieldset><legend>Same-name patient safety check</legend>
    ${row.duplicate_candidates?.length ? `<p>Existing local records to compare: ${row.duplicate_candidates.map(candidate => `#${Number(candidate.id)} · ${esc(candidate.name)} · DOB ${esc(candidate.dob || 'unknown')} · GP ${esc(candidate.gp || 'unknown')}`).join('; ')}</p>` : '<p>Another referral in this batch contains this name.</p>'}
    <label><input type="checkbox" data-distinct-person required> I compared reliable identifiers against the source PDF and confirm this is a different person (not a duplicate document).</label>
    <p>If the DOB, Medicare number or IHI match, open the existing patient instead. If reliable identifiers are unavailable, gather them before creating another same-name record.</p></fieldset>` : ''}<button class="primary">Confirm and add patient</button><p class="referral-pending" role="status"></p><p class="error" role="alert" tabindex="-1"></p></form>` : ''}
    ${row.patient_id ? `<button data-referral-open="${Number(row.patient_id)}">Open patient</button>` : ''}</article>`).join('');
}

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-referral-pick], [data-referral-open], [data-referral-source], [data-referral-skip]');
  if (!button) return;
  try {
    if (button.dataset.referralSkip !== undefined) {
      const row = referralRows[Number(button.dataset.referralSkip)];
      if (row && row.status === 'manual') { row.userSkipped = true; renderReferrals(); }
      return;
    }
    if (button.dataset.referralOpen) return await openPatientWorkspace(Number(button.dataset.referralOpen), 'Overview', 'patient');
    if (button.dataset.referralSource) return await hmr.openReviewedReferral(button.dataset.referralSource);
    button.disabled = true;
    $('referral-status').textContent = 'Reading referrals…';
    const result = await hmr.referralPick(button.dataset.referralPick);
    if (result) referralRows.push(...result.rows);
    if (result?.listing) referralListings.push(result.listing);
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
  const pending = form.querySelector('.referral-pending'), error = form.querySelector('.error'), label = button.textContent;
  button.disabled = true;
  button.textContent = 'Adding patient...';
  // No timeout on purpose: if the answer is slow the add may still complete, and a second submit could duplicate it.
  if (pending) pending.textContent = 'Adding the patient. Wait for the result before trying again.';
  if (error) error.textContent = '';
  try {
    const reviewed = referralReviewFields(form);
    const result = await hmr.api('POST', '/api/referrals/commit', {
      token: row.token, fields: reviewed.fields, clinical: reviewed.clinical,
      distinct_person: !!form.querySelector('[data-distinct-person]')?.checked,
      manual_referral: !!form.querySelector('[data-manual-referral]')?.checked,
    });
    row.status = 'added'; row.patient_id = result.patient_id;
    row.dirty = false;
    if (page === 'intake') formOpen = referralRows.some(item => item.dirty && item.status !== 'added');
    renderReferrals();
  } catch (failure) {
    // Keep the form and every entered value. Show why, right where the pharmacist is looking.
    button.disabled = false;
    button.textContent = label;
    if (pending) pending.textContent = '';
    if (error) {
      error.textContent = 'Not added: ' + errorText(failure);
      error.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
      error.focus?.({ preventScroll: true });
    }
  }
});

document.addEventListener('dragover', event => {
  if (event.target.closest?.('#referral-drop')) event.preventDefault();
});
document.addEventListener('input', event => {
  const form = event.target.closest?.('[data-referral-commit]');
  if (!form) return;
  const row = referralRows[Number(form.dataset.referralCommit)];
  const reviewed = referralReviewFields(form);
  row.fields = reviewed.fields;
  row.clinical = reviewed.clinical;
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
