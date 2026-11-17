/* Local lexical evidence retrieval. No recommendation insertion or clinical scoring. */
let evidenceReferenceRun=0,evidenceReferenceState=null;
function evidenceReferencePanel() {
 return '<section class="card" id="evidence-reference-panel"><h2>Reference passages from saved evidence</h2><p>Automatic literal text matching from saved notes, observations and verified pathology. These are reading prompts, not patient findings or clinical advice.</p><button type="button" data-evidence-reference-refresh>Refresh saved-evidence matches</button><div id="evidence-reference-results" aria-live="polite">Loading saved-evidence matches...</div></section>';
}
function invalidateEvidenceReferences(message='Evidence changed. Save and refresh before reviewing reference matches.') {
 evidenceReferenceRun++;evidenceReferenceState=null;
 const target=document.getElementById('evidence-reference-results');if(target)target.textContent=message;
}
function evidenceReferenceHtml(result) {
 const esc=H.esc;
 const row=e=>`<details open><summary>Original ${esc(e.kind)} | ${esc(e.id)}</summary><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(e.text)}</p><p>Source: ${esc(e.source || 'not established')} | Date: ${esc(e.date || 'not established')}${e.age_days !== undefined && e.age_days !== null ? ` | Age: ${esc(e.age_days)} days` : ''}</p>${e.unit !== undefined ? `<p>Units: ${esc(e.unit || 'missing')} | Reference interval: ${esc(e.reference_interval || 'not recorded')}</p>` : ''}<p>${esc(e.verification || '')}${e.verified_by ? ' | '+esc(e.verified_by)+' | '+esc(e.verified_at || '') : ''}</p>${e.comment ? `<p>Original comment: ${esc(e.comment)}</p>` : ''}${e.flags?.length ? `<p>Check: ${esc(e.flags.join('; '))}</p>` : ''}</details>`;
 return `<p>Reference: ${esc(result.reference.edition)}. Checked against saved context on ${esc(result.checked_on)}. Pharmacist review required.</p><p>${esc(result.method)}</p><p>Negated, historical or uncertain wording is kept as written. A text match does not assert the condition is present. No clinical relevance or expiry has been inferred.</p>${result.truncated ? '<p role="alert">Results are limited. This is not a complete evidence or reference review.</p>' : ''}<p>${esc(result.processed_evidence_rows)} eligible evidence rows checked; ${esc(result.matches.length)} of ${esc(result.total_matches)} matches shown.</p>${result.context_gaps?.length ? `<details><summary>Missing context and review cautions</summary><ul>${result.context_gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul></details>` : ''}` + (result.matches.length ? result.matches.map((hit,i)=>`<article class="card helper-card">${row(hit.evidence)}<h3>${esc(hit.reference.title)}</h3><p>Matched heading words: ${esc(hit.matched_heading_words.join('; '))}</p><p>${esc(hit.reference.edition)} | Physical PDF page ${esc(hit.reference.page)} | Section pages ${esc(hit.reference.section_page)}-${esc(hit.reference.section_page_end)}</p><blockquote style="white-space:pre-wrap;overflow-wrap:anywhere">${hit.reference.omitted_before ? '[...] ' : ''}${esc(hit.reference.snippet)}${hit.reference.omitted_after ? ' [...]' : ''}</blockquote><p class="muted">Extracted text, spacing normalized. Review the original source and current clinical references.</p><p class="muted" style="overflow-wrap:anywhere">PDF SHA-256: ${esc(hit.reference.pdf_sha256)}</p><button type="button" data-evidence-reference-open="${i}">Open original physical page ${esc(hit.reference.page)}</button></article>`).join('') : '<p>No literal matches. This does not rule out an issue or show that this review is complete.</p>');
}
function evidenceReferencePatient() {
 if(page==='interview')return String(interviewId || '');
 if(page==='report_editor')return String(reportId || '');
 return '';
}
function evidenceReferenceDirty() {
 return page==='interview' && (interviewDirty() || interviewConflict || interviewPathologyDirty);
}
async function refreshEvidenceReferences() {
 const id=evidenceReferencePatient(),target=document.getElementById('evidence-reference-results');
 if(!id || !target)return;
 if(evidenceReferenceDirty()) {invalidateEvidenceReferences();return;}
 const run=++evidenceReferenceRun;evidenceReferenceState=null;target.textContent='Loading reference passages from saved evidence...';
 try {
  const result=await hmr.api('GET',`/api/patients/${encodeURIComponent(id)}/reference-matches`);
  if(run!==evidenceReferenceRun || id!==evidenceReferencePatient() || !target.isConnected || evidenceReferenceDirty())return;
  evidenceReferenceState={id,result};target.innerHTML=evidenceReferenceHtml(result);
 } catch(error) {
  if(run===evidenceReferenceRun && id===evidenceReferencePatient() && target.isConnected)target.textContent=error.message+' No evidence-linked reference passages were generated. Manual reference search and saved evidence remain separate.';
 }
}
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-evidence-reference-refresh],[data-evidence-reference-open]');if(!el)return;
 if(el.hasAttribute('data-evidence-reference-refresh')) {await refreshEvidenceReferences();return;}
 const state=evidenceReferenceState,target=document.getElementById('evidence-reference-results');
 if(!state || state.id!==evidenceReferencePatient() || evidenceReferenceDirty()) {invalidateEvidenceReferences();return;}
 const hit=state.result.matches[Number(el.dataset.evidenceReferenceOpen)];if(!hit)return;
 const run=evidenceReferenceRun;
 try {
  // An open request revalidates BOTH current evidence revision and reference bytes.
  const current=await hmr.api('GET',`/api/patients/${encodeURIComponent(state.id)}/reference-matches`);
  if(run!==evidenceReferenceRun || state.id!==evidenceReferencePatient() || evidenceReferenceDirty())return;
  if(current.context_snapshot_sha256!==state.result.context_snapshot_sha256 || current.reference.pdf_sha256!==hit.reference.pdf_sha256 || current.reference.edition!==hit.reference.edition) {invalidateEvidenceReferences('Saved evidence or the reference changed. Refresh and re-review the matches.');return;}
  await hmr.openLocalReference(hit.reference.pdf_sha256,hit.reference.page);
 } catch(error) {if(run===evidenceReferenceRun && state.id===evidenceReferencePatient() && target?.isConnected) {invalidateEvidenceReferences(error.message);}}
});
