// On the PPA "HMR Service Claim" page, adds a panel to pick a patient from PPA_CLAIMS (claims.js) and fill the form.
// It never clicks Save or Submit: the pharmacist checks every field and submits.
const PHARMACIST = {mmr: '', given: '', family: ''};

function setText(id, value) {
  const e = document.getElementById(id);
  if (!e || value == null || value === '') return false;
  e.focus(); e.value = value;
  e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
  e.dispatchEvent(new Event('blur', {bubbles: true}));
  return true;
}
function tick(id, on) { const e = document.getElementById(id); if (e && e.checked !== !!on) e.click(); }

function fill(c) {
  // Only tick the declaration when HMR Desk holds signed consent for this patient.
  const consentRecorded = c.consentHeld === true;
  if (consentRecorded) tick('writtenPatientConsentHeld_0', true);
  const map = {
    patientMedicareDVANumber: c.medicare, patientGivenNames: c.given, patientFamilyName: c.family,
    patientDateOfBirth: c.dob, mrnOrSHPAAccreditationNumber: PHARMACIST.mmr,
    pharmacistGivenNames: PHARMACIST.given, pharmacistFamilyName: PHARMACIST.family,
    dateOfService: c.interview, dateCompletedReportSentToGP: c.reportSent, dateOfWrittenReferral: c.referral,
    providerNumberOfRequestingGeneralPractit: c.gpProvider, requestinggpGivenNames: c.gpGiven,
    requestinggpFamilyName: c.gpFamily, patientHomeSuburb: c.suburb, patientHomePostcode: c.postcode};
  const missing = Object.entries(map).filter(([id, v]) => !setText(id, v)).map(([id]) => id);
  for (const [id, key] of [['polypharmacy', 'polypharmacy'], ['suspectedAdverseEvent', 'adverse'],
    ['usingMedicinesWithNarrowTherapeuticRange', 'narrow'], ['otherReferral', 'other']]) tick(id, c.reasons.includes(key));
  if (c.reasons.includes('other')) setText('otherReasonForReferral', c.reasonOther);
  for (const [id, key] of [['increaseInDoseOfOneOrMoreMedicines', 'increase'], ['decreaseInDoseOfOneOrMoreMedicines', 'decrease'],
    ['changeOfMedicinesToDifferentMedicine', 'change'], ['cessationOfOneOrMoreMedicines', 'cessation'], ['otherRecommendation', 'other']])
    tick(id, c.outcomes.includes(key));
  if (c.outcomes.includes('other')) setText('otherRecommendationsToGP', c.outcomeOther);
  if (!consentRecorded) missing.push('written consent held (no signed consent recorded in HMR Desk; leave unticked until verified)');
  if (!c.reasons.length) missing.push('reason for referral');
  if (!c.outcomes.length) missing.push('outcomes');
  // Mark the fields that still need a value so they are easy to see.
  for (const id of missing) { const e = document.getElementById(id); if (e) e.style.outline = '3px solid #e67e22'; }
  return missing;
}

function panel() {
  if (document.getElementById('ppa-claim-helper') || !/\/hmr\/\d+\/claim\/new/.test(location.pathname)) return;
  if (!document.getElementById('patientMedicareDVANumber')) return;
  const box = document.createElement('div'); box.id = 'ppa-claim-helper';
  box.style.cssText = 'position:fixed;bottom:16px;left:16px;z-index:99999;background:#fff;border:2px solid #0b5394;border-radius:8px;padding:10px;font:14px sans-serif;max-width:360px;box-shadow:0 4px 14px rgba(0,0,0,.2)';
  const pending = (typeof PPA_CLAIMS !== 'undefined' ? PPA_CLAIMS : []);
  box.innerHTML = `<b>PPA Claim Helper</b> (${pending.length} ready)<br>
    <select id="pch-pick" style="width:100%;margin:6px 0">${pending.map((c, i) => `<option value="${i}">${c.given} ${c.family} · visit ${c.interview}</option>`).join('')}</select>
    <button id="pch-fill" style="padding:6px 10px">Fill form</button>
    <div id="pch-msg" style="margin-top:6px;color:#333"></div>`;
  document.body.appendChild(box);
  if (!pending.length) { box.querySelector('#pch-msg').textContent = 'No claims in claims.js. Run make-claims.py and reload the extension.'; return; }
  box.querySelector('#pch-fill').onclick = () => {
    const c = pending[+box.querySelector('#pch-pick').value];
    const missing = fill(c);
    box.querySelector('#pch-msg').innerHTML = (missing.length ? `<span style="color:#b9550a">Still to fill (orange): ${missing.join(', ')}</span><br>` : '')
      + `<b>Check every field against the register, then click Submit yourself.</b>`;
  };
}

// The page is a single-page app: watch for the claim form appearing.
new MutationObserver(panel).observe(document.documentElement, {childList: true, subtree: true});
panel();
