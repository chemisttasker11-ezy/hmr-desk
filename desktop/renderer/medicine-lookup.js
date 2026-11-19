const medicineSuggestions = new WeakMap();
// One line per medicine for the suggestion panel. Lines come from the engine's groups when present; older
// proposals show each candidate. The pharmacist never sees or chooses a listing code.
function medicineProposalLines(proposal) {
  const c = proposal.candidates, groups = Array.isArray(proposal.groups) && proposal.groups.length ? proposal.groups : c.map((r, n) => ({label: r.display, indexes: [n]}));
  return groups.filter(g => c[g.indexes[0]]).map(g => ({index: g.indexes[0], count: g.indexes.length, label: g.label, generic_name: c[g.indexes[0]].generic_name, release: c[g.indexes[0]].release}));
}
// Medicine reference lookup for the interview. The pharmacist always picks; free text stays valid.
function interviewLookupControls(key, meta, i) {
  const ref = meta && meta.reference, esc = H.esc;
  const linked = ref ? `<span class="med-ref">Linked: ${esc(ref.display)} (${ref.source === 'pbs' ? 'PBS' : esc(ref.source.toUpperCase()) + ' ' + esc(ref.code)}, release ${esc(ref.release)}) <button type="button" data-med-unlink="${esc(key)}" data-row="${i}">Unlink</button></span>` : '';
  const evidence = meta?.source_evidence;
  const original = evidence ? `<details class="med-source"><summary>Extracted referral text (not current use)</summary>${evidence.lines.map((line,n)=>`<p>${esc(line)} <small>${evidence.page_candidates[n].length === 1 ? `Text located on page ${evidence.page_candidates[n][0]}` : evidence.page_candidates[n].length ? `Page candidates: ${evidence.page_candidates[n].join(', ')}` : 'Page not established'}</small></p>`).join('')}</details>` : '';
  const proposal = medicineSuggestions.get(meta);
  const suggestions = !ref && proposal ? `<div class="medicine-proposals"><p>${esc(({exact_candidate:'Exact displayed-text candidate, not confirmed. Check strength, form and release type.',ambiguous:'More than one exact text candidate. Choose only after reviewing the original.',review_candidates:'Possible matches only. OCR or product details differ; do not guess.',unmatched:'No catalogue candidate. Keep the source/free text and review it.',unavailable:'Medicine reference unavailable. Free text still works.'})[proposal.state] || 'Review medicine candidates.')}${proposal.prepared==='intake' ? ' Prepared at intake from the referral text; the catalogue entry was re-checked when this interview opened.' : ''}${proposal.truncated ? ' More candidates exist; use manual lookup to narrow.' : ''}</p>${medicineProposalLines(proposal).map(g=>`<div class="med-lookup-result"><span>${esc(g.label)}${g.generic_name ? ` | Modelled generic: ${esc(g.generic_name)}` : ''}${g.count>1 ? ` (${g.count} matching entries combined)` : ''} | release ${esc(g.release)}</span><button type="button" data-med-suggestion="${esc(key)}" data-row="${i}" data-candidate="${g.index}">Use this</button></div>`).join('')}</div>` : '';
  return `<div class="med-lookup">${original}${suggestions}<button type="button" data-med-lookup="${esc(key)}" data-row="${i}">Look up medicine</button>${linked}<div class="med-lookup-results" data-med-results="${esc(key)}-${i}" role="status"></div></div>`;
}
// Editing a linked name makes the previous identity ambiguous. Never keep a silent stale link.
function medicineNameEdited(key, i, element) {
  const meta = interviewRecord.details[key][i], linked = !!meta.reference;
  medicineSuggestions.delete(meta);
  delete meta.reference;
  const block = element.closest?.('tr')?.querySelector('.med-lookup');
  block?.querySelector('.med-ref')?.remove();
  block?.querySelector('.medicine-proposals')?.remove?.();
  const results = block?.querySelector('.med-lookup-results');
  results?.replaceChildren();
  if (linked && results) {
    const note = document.createElement('p');
    note.textContent = 'Name edited. Previous reference unlinked; look up again if needed. Your typed name is kept.';
    results.append(note);
  }
}
// The main-process API guard only allows [A-Za-z0-9_/?=&%.-]; encodeURIComponent also leaves ! ~ * ' ( ) raw,
// so a name such as "Suvorexant 20 mg tablet (Belsomra)" was rejected before it reached the engine.
const medicineQuery = (text) => encodeURIComponent(text).replace(/[!~*'()]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase());
async function medicineLookupClick(b) {
  if (b.dataset.medSuggestion !== undefined) {
    const key=b.dataset.medSuggestion, i=Number(b.dataset.row), meta=interviewRecord.details[key]?.[i];
    const proposal=medicineSuggestions.get(meta), candidate=proposal?.candidates[Number(b.dataset.candidate)];
    if (!candidate || interviewRecord[key][i][0] !== proposal.input_text) return true;
    const line=medicineProposalLines(proposal).find(g=>g.index===Number(b.dataset.candidate)), shown=line?.label || candidate.display;
    interviewRecord[key][i][0]=shown;
    meta.reference={source:candidate.source,code:candidate.code,display:shown,release:candidate.release};
    medicineSuggestions.delete(meta);interviewChanged(key);renderInterview();return true;
  }
  if (b.dataset.medUnlink !== undefined) {
    const meta = interviewRecord.details[b.dataset.medUnlink][Number(b.dataset.row)];
    delete meta.reference; interviewChanged(b.dataset.medUnlink); renderInterview();
    return true;
  }
  if (b.dataset.medLookup === undefined) return false;
  const key = b.dataset.medLookup, i = Number(b.dataset.row);
  const patientId = interviewId, record = interviewRecord, medicine = record[key][i];
  const out = document.querySelector(`[data-med-results="${key}-${i}"]`);
  const box = document.querySelector(`textarea[data-field="${key}"][data-row="${i}"][data-col="0"]`);
  const text = (box ? box.value : '').trim();
  out.replaceChildren();
  const say = (t) => { const p = document.createElement('p'); p.textContent = t; out.append(p); };
  if (text.length < 2) { say('Type at least two letters of the medicine name, then look up.'); return true; }
  try {
    const found = await hmr.api('GET', '/api/medicines/search?grouped=1&q=' + medicineQuery(text));
    if (page !== 'interview' || interviewId !== patientId || interviewRecord !== record || record[key][i] !== medicine || medicine[0].trim() !== text || !out.isConnected) return true;
    if (!found.installed) { say('No medicine reference data is installed on this PC. Keep typing the name by hand; nothing is lost.'); return true; }
    if (!found.results.length) { say('No match in the reference data. Keep your typed name, or try another spelling.'); return true; }
    say('Pick the medicine you mean. Reference release ' + found.results[0].release + '. Check strength and form yourself.');
    const choose = (r) => {
      if (page !== 'interview' || interviewId !== patientId || interviewRecord !== record || record[key][i] !== medicine || medicine[0].trim() !== text || !out.isConnected) return;
      interviewRecord[key][i][0] = r.display;
      interviewRecord.details[key][i].reference = { source: r.source, code: r.code, display: r.display, release: r.release };
      interviewChanged(key); renderInterview();
    };
    // Identical PBS listings arrive as one group; each listing stays individually pickable. Older replies are flat.
    const groups = Array.isArray(found.groups) ? found.groups : found.results.map((r) => ({ grouped: false, label: '', listings: [r], count: 1 }));
    for (const g of groups) {
      const row = document.createElement('div'); row.className = 'med-lookup-result';
      const label = document.createElement('span');
      const first = g.listings[0];
      // A group is one medicine as the source states it. The pharmacist sees no listing codes; the stored
      // reference is one real catalogue listing of that group (the first by code) so provenance stays intact.
      const pick = g.label ? Object.assign({}, first, { display: g.label }) : first;
      label.textContent = (g.label || first.display) + (g.listings.length > 1 ? ' (' + g.listings.length + ' matching entries combined)' : '');
      const use = document.createElement('button'); use.type = 'button'; use.textContent = 'Use this';
      use.addEventListener('click', () => choose(pick));
      row.append(label, use); out.append(row);
    }
    if (found.more_available) say('More matches exist. Type more of the name to narrow the list.');
  } catch (error) { say('Lookup failed: ' + errorText(error) + '. Type the name by hand.'); }
  return true;
}
document.addEventListener('click', (e) => { const b = e.target.closest && e.target.closest('[data-med-lookup], [data-med-unlink], [data-med-suggestion]'); if (b) medicineLookupClick(b); });


async function medicinePrefillSuggestions() {
  const record=interviewRecord, patient=interviewId;
  const rows=(record?.meds || []).map((row,i)=>({row,meta:record.details.meds[i],i}))
    .filter(x=>x.meta?.source_evidence && !x.meta.reference);
  if (!rows.length) return;
  const queries=rows.map(x=>x.row[0]);
  try {
    const result=await hmr.api('POST','/api/medicines/suggest',{queries});
    if (page !== 'interview' || interviewId !== patient || interviewRecord !== record) return;
    if (!Array.isArray(result.results) || result.results.length !== rows.length) return;
    rows.forEach((entry,n)=>{
      let proposal=result.results[n], {row,meta,i}=entry;
      if (record.meds[i] !== row || record.details.meds[i] !== meta || row[0] !== queries[n] || meta.reference || proposal.input_text !== queries[n]) return;
      // A stored intake proposal is provenance, never authority: show it as
      // intake-prepared only when the current catalogue still resolves the same
      // unique exact candidate with identical contents for this row's text.
      const p=meta.prefill_proposal;
      if (p && p.candidate && p.input_text===row[0] && proposal.state==='exact_candidate' && proposal.candidates.length===1
          && ['source','code','display','kind','generic_name','brand_name','dose_form','release'].every(k=>proposal.candidates[0][k]===p.candidate[k]))
        proposal={...proposal,prepared:'intake'};
      medicineSuggestions.set(meta,proposal);
      const block=document.querySelector(`[data-med-results="meds-${i}"]`)?.closest('.med-lookup');
      if (block) block.outerHTML=interviewLookupControls('meds',meta,i);
    });
  } catch (error) {
    // Suggestions never block the saved interview or silently set a reference, but a failure is shown, not swallowed.
    if (page !== 'interview' || interviewId !== patient || interviewRecord !== record) return;
    rows.forEach(({i}) => {
      const out=document.querySelector(`[data-med-results="meds-${i}"]`);
      if (out && !out.childElementCount) { const p=document.createElement('p'); p.textContent='Suggestions unavailable ('+errorText(error)+'). Use Look up medicine or type the name by hand.'; out.append(p); }
    });
  }
    }
