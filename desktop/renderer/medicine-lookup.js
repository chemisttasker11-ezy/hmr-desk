// Medicine reference lookup for the interview. The pharmacist always picks; free text stays valid.
function interviewLookupControls(key, meta, i) {
  const ref = meta && meta.reference, esc = H.esc;
  const linked = ref ? `<span class="med-ref">Linked: ${esc(ref.display)} (${esc(ref.source.toUpperCase())} ${esc(ref.code)}, release ${esc(ref.release)}) <button type="button" data-med-unlink="${esc(key)}" data-row="${i}">Unlink</button></span>` : '';
  return `<div class="med-lookup"><button type="button" data-med-lookup="${esc(key)}" data-row="${i}">Look up medicine</button>${linked}<div class="med-lookup-results" data-med-results="${esc(key)}-${i}" role="status"></div></div>`;
}
// Editing a linked name makes the previous identity ambiguous. Never keep a silent stale link.
function medicineNameEdited(key, i, element) {
  const meta = interviewRecord.details[key][i], linked = !!meta.reference;
  delete meta.reference;
  const block = element.closest?.('tr')?.querySelector('.med-lookup');
  block?.querySelector('.med-ref')?.remove();
  const results = block?.querySelector('.med-lookup-results');
  results?.replaceChildren();
  if (linked && results) {
    const note = document.createElement('p');
    note.textContent = 'Name edited. Previous reference unlinked; look up again if needed. Your typed name is kept.';
    results.append(note);
  }
}
async function medicineLookupClick(b) {
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
    const found = await hmr.api('GET', '/api/medicines/search?q=' + encodeURIComponent(text));
    if (page !== 'interview' || interviewId !== patientId || interviewRecord !== record || record[key][i] !== medicine || medicine[0].trim() !== text || !out.isConnected) return true;
    if (!found.installed) { say('No medicine reference data is installed on this PC. Keep typing the name by hand; nothing is lost.'); return true; }
    if (!found.results.length) { say('No match in the reference data. Keep your typed name, or try another spelling.'); return true; }
    say('Pick the medicine you mean. Reference release ' + found.results[0].release + '. Check strength and form yourself.');
    for (const r of found.results) {
      const row = document.createElement('div'); row.className = 'med-lookup-result';
      const label = document.createElement('span'); label.textContent = r.display + ' [' + r.kind + ']';
      const use = document.createElement('button'); use.type = 'button'; use.textContent = 'Use this';
      use.addEventListener('click', () => {
        if (page !== 'interview' || interviewId !== patientId || interviewRecord !== record || record[key][i] !== medicine || medicine[0].trim() !== text || !out.isConnected) return;
        interviewRecord[key][i][0] = r.display;
        interviewRecord.details[key][i].reference = { source: r.source, code: r.code, display: r.display, release: r.release };
        interviewChanged(key); renderInterview();
      });
      row.append(label, use); out.append(row);
    }
  } catch (error) { say('Lookup failed: ' + errorText(error) + '. Type the name by hand.'); }
  return true;
}
document.addEventListener('click', (e) => { const b = e.target.closest && e.target.closest('[data-med-lookup], [data-med-unlink]'); if (b) medicineLookupClick(b); });
