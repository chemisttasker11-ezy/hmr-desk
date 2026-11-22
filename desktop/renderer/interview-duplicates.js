// Pharmacist-confirmed duplicate entries. A suggestion is never a confirmation: nothing is saved until the pharmacist
// ticks the box, and ticking records only the link. It never changes whether the medicine is taken, and never removes a row.
const interviewDupDraft = new Map();   // item_id -> target item_id chosen in the list but not yet confirmed

function interviewDupSig(row, meta) {
  const ref = meta && meta.reference, refId = ref && ref.source && ref.code ? ref.source + ':' + ref.code : '';
  return String(row[0] ?? '').toLowerCase().split(/\s+/).filter(Boolean).join(' ') + '|' + refId;
}
const interviewDupStrength = /(\d+(?:\.\d+)?)\s*(mg|mcg|\u00b5g|ug|g|ml|iu|units?|%)/g;
const interviewDupFormWords = { tablet: 'tablet', tablets: 'tablet', tab: 'tablet', capsule: 'capsule', capsules: 'capsule', cap: 'capsule', mr: 'mr', sr: 'sr', xr: 'xr', er: 'er', cr: 'cr', ec: 'ec', patch: 'patch', injection: 'injection', syrup: 'syrup', solution: 'solution', suspension: 'suspension', cream: 'cream', ointment: 'ointment', drops: 'drops', inhaler: 'inhaler', spray: 'spray', sachet: 'sachet', suppository: 'suppository', wafer: 'wafer', lozenge: 'lozenge' };
for (const w of ["modified", "release", "extended", "delayed", "controlled", "sustained", "slow", "long", "acting", "enteric", "coated", "film", "chewable", "dispersible", "soluble", "effervescent", "orally", "disintegrating", "odt", "liquid", "elixir", "gel", "foam", "powder", "granules", "pessary", "enema", "eye", "ear", "nasal", "topical", "oral", "iv", "im", "subcutaneous", "pen", "vial", "ampoule", "cartridge", "lotion", "paste", "implant", "pellet", "mouthwash", "gargle", "lancet", "infusion", "concentrate", "emulsion", "oil", "shampoo", "wash", "tape", "applicator", "device", "turbuhaler", "accuhaler", "nebule", "respule", "ml_liquid", "xl", "la", "cd", "dr", "di", "pr", "sl", "buccal", "sublingual", "transdermal", "rectal", "vaginal", "depot", "susp"]) if (!Object.hasOwn(interviewDupFormWords, w)) interviewDupFormWords[w] = w;
const interviewDupStrengthSet = text => [...new Set([...text.matchAll(interviewDupStrength)].map(m => String(parseFloat(m[1])) + ' ' + m[2]))].sort().join(',');
const interviewDupFormSet = text => [...new Set((text.match(/[a-z]+/g) || []).filter(w => Object.hasOwn(interviewDupFormWords, w)).map(w => interviewDupFormWords[w]))].sort().join(',');
// Same bounded rule as the engine (interview.duplicate_compatible), used only to refuse: entered texts equal after case, whitespace and
// tablet/capsule plural normalisation (every punctuation mark is kept), containing a real strength; different catalogue entries never qualify. Nothing is inferred.
const interviewDupSyn = { tablets: 'tablet', tabs: 'tablet', tab: 'tablet', capsules: 'capsule', caps: 'capsule', cap: 'capsule' };
const interviewDupCanon = text => (text.toLowerCase().replace(/\u00b5/g, 'mc').match(/[a-z]+|[0-9]+|\S/g) || []).map(w => interviewDupSyn[w] || w).join(' ');
function interviewDupCompatible(a, b) {
  const [ta, ra] = interviewDupSig(a.row, a.meta).split('|'), [tb, rb] = interviewDupSig(b.row, b.meta).split('|');
  if (ra && rb && ra !== rb) return false;
  return interviewDupCanon(ta) === interviewDupCanon(tb) && !!interviewDupStrengthSet(ta);
}
function interviewDupEntries(record) {
  const out = [];
  for (const [key, label] of [['meds', 'Referral list'], ['other_meds', 'Other medicines']]) {
    (record.details?.[key] || []).forEach((meta, i) => out.push({ key, label, i, row: record[key][i] || [''], meta }));
  }
  return out;
}
// Conservative suggestion: the whole entered medicine text must be identical and contain a strength digit. A linked catalogue
// entry never overrides the text: a stale code beside edited text (500 versus 850) gives no suggestion, and two entries linked
// to different catalogue entries never match. Name alone, an ingredient alone, another strength or another form never match.
function interviewDupMarked(meta) { return !!meta.duplicate_of && !meta.duplicate_of.lapsed; }
function interviewDupCandidates(record, entry) {
  // suggestions use the same predicate as confirmation, so nothing is suggested that could not be confirmed
  return interviewDupEntries(record).filter(other => other.meta !== entry.meta && other.meta.item_id && !interviewDupMarked(other.meta) && interviewDupCompatible(entry, other));
}
// A confirmation whose entries no longer match what was confirmed lapses for good. It stays on the record as audit, and the
// pharmacist has to confirm again; putting the old text back does not bring it back.
function interviewDupLapse(record) {
  let changed = false;
  for (const entry of interviewDupEntries(record)) {
    const link = entry.meta.duplicate_of;
    if (link && !link.lapsed) { const st = interviewDupState(record, entry); if (!st.current) { link.lapsed = true; changed = true; } }
  }
  return changed;
}
function interviewDupState(record, entry) {
  const link = entry.meta.duplicate_of;
  if (!link) return null;
  const target = interviewDupEntries(record).find(o => o.meta.item_id === link.item_id);
  const current = !link.lapsed && !!target && target.meta !== entry.meta && link.own_sig === interviewDupSig(entry.row, entry.meta) && link.target_sig === interviewDupSig(target.row, target.meta);
  return { link, target, current };
}
function interviewDupLabel(entry) { return `${entry.row[0] || '(no name)'} — ${entry.label}`; }

function interviewDuplicateControls(key, meta, i) {
  const record = interviewRecord, entry = interviewDupEntries(record).find(e => e.meta === meta);
  if (!entry) return '';
  const state = interviewDupState(record, entry), id = `dup-${key}-${i}`;
  const isTarget = interviewDupEntries(record).some(o => interviewDupMarked(o.meta) && o.meta.duplicate_of.item_id === meta.item_id);
  const suggestions = interviewDupCandidates(record, entry);
  const chosen = state ? state.link.item_id : (interviewDupDraft.get(meta.item_id) || '');
  const eligible = interviewDupEntries(record).filter(o => o.meta !== meta && o.meta.item_id && interviewDupCompatible(entry, o) && (!interviewDupMarked(o.meta) || o.meta.item_id === chosen));
  const options = eligible
    .map(o => `<option value="${esc(o.meta.item_id)}" ${o.meta.item_id === chosen ? 'selected' : ''}>${esc(interviewDupLabel(o))}</option>`).join('');
  const hint = state ? '' : suggestions.length ? `<p class="interview-dup-hint" role="note">Possible duplicate: the same medicine text${suggestions.some(s => s.meta.reference) ? ' or catalogue entry' : ''} is entered as ${suggestions.map(s => esc(interviewDupLabel(s))).join('; ')}. Check strength and form before confirming.</p>` : '';
  const stale = state && !state.current ? `<p class="interview-dup-stale" role="alert">An earlier duplicate confirmation is no longer current because an entry changed or was removed. It cannot come back by restoring the text. Untick it, then choose the entry and confirm again.</p>` : '';
  const none = !state && !eligible.length ? '<p class="interview-dup-hint" role="note">No other entry has the same medicine text including a strength, so none can be confirmed as a duplicate of this one. If they are the same, edit both entries to the same wording with strength and form first.</p>' : '';
  const blocked = isTarget ? '<p class="interview-dup-hint" role="note">Another entry is marked as a duplicate of this one, so this entry cannot also be marked.</p>' : '';
  return `<fieldset class="interview-duplicate" data-dup-box="${id}"><legend>Possible duplicate entry</legend>${hint}${stale}${blocked}${none}
    <label>Same medicine as<select data-dup-target data-dup-key="${key}" data-row="${i}" ${isTarget || state ? 'disabled' : ''}><option value="">Not marked</option>${options}</select></label>
    <label class="interview-check"><input type="checkbox" data-dup-confirm data-dup-key="${key}" data-row="${i}" ${state ? 'checked' : ''} ${(isTarget || (!state && !chosen)) ? 'disabled' : ''}> I confirm this entry is a duplicate of the selected one. This does not record whether it is taken.</label>
    <label>Pharmacist note<textarea rows="2" data-dup-note data-dup-key="${key}" data-row="${i}" maxlength="2000" ${state && state.current ? '' : 'disabled'}>${esc(state ? state.link.note : '')}</textarea></label></fieldset>`;
}
function interviewDupBadge(key, meta, i) {
  const record = interviewRecord, entry = interviewDupEntries(record).find(e => e.meta === meta);
  if (!entry) return '';
  const state = interviewDupState(record, entry);
  const label = state ? (state.current ? 'Duplicate confirmed' : 'Duplicate confirmation outdated') : interviewDupCandidates(record, entry).length ? 'Possible duplicate' : '';
  return label ? `<button type="button" class="interview-badge" data-interview-badge="${key}" data-row="${i}" data-badge-kind="dup">${esc(label)}</button>` : '';
}

function interviewDupConfirm(key, i, confirmed) {
  const record = interviewRecord, entry = interviewDupEntries(record).find(e => e.key === key && e.i === i);
  if (!entry) return;
  if (!confirmed) { delete entry.meta.duplicate_of; interviewChanged(key); renderInterview(); return; }
  const target = interviewDupEntries(record).find(o => o.meta.item_id === interviewDupDraft.get(entry.meta.item_id));
  if (!target || target.meta === entry.meta || interviewDupMarked(target.meta) || !interviewDupCompatible(entry, target)) return;
  if (interviewDupEntries(record).some(o => interviewDupMarked(o.meta) && o.meta.duplicate_of.item_id === entry.meta.item_id)) return;   // another entry points here: no chains
  const own = interviewDupSig(entry.row, entry.meta), theirs = interviewDupSig(target.row, target.meta);
  if (own.length > 2000 || theirs.length > 2000) return;
  entry.meta.duplicate_of = { item_id: target.meta.item_id, own_sig: own, target_sig: theirs, target_text: String(target.row[0] || '').slice(0, 400), note: '' };
  interviewDupDraft.delete(entry.meta.item_id);
  interviewChanged(key); renderInterview();
}
document.addEventListener('change', event => {
  if (typeof page !== 'undefined' && page !== 'interview') return;
  const el = event.target, d = el.dataset || {};
  if (d.dupKey === undefined) return;
  const key = d.dupKey, i = Number(d.row), meta = interviewRecord?.details?.[key]?.[i];
  if (!meta) return;
  if (d.dupTarget !== undefined) { el.value ? interviewDupDraft.set(meta.item_id, el.value) : interviewDupDraft.delete(meta.item_id); renderInterview(); }
  else if (d.dupConfirm !== undefined) interviewDupConfirm(key, i, el.checked);
});
document.addEventListener('input', event => {
  const el = event.target, d = el.dataset || {};
  if (d.field === 'meds' || d.field === 'other_meds') { if (interviewRecord && interviewDupLapse(interviewRecord)) interviewChanged(d.field); return; }
  if (d.dupNote === undefined) return;
  const meta = interviewRecord?.details?.[d.dupKey]?.[Number(d.row)];
  if (meta?.duplicate_of && !meta.duplicate_of.lapsed) { meta.duplicate_of.note = el.value; interviewChanged(d.dupKey); }
});
