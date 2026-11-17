// Saved interview context only. This never writes medicine or follow-up fields.
function followupMedicineContextMarkup(context) {
  const esc = H.esc;
  const heading = '<section class="interview-section"><h2>Saved interview medicines</h2>';
  const warning = '<p>This is the saved interview record, not a confirmation of medicines used now. Check changes with the patient and record them in Medicine changes below. Reference links are recorded identifiers, not dosing advice.</p>';
  if (context.error) return heading + warning + '<p role="status">Saved medicine context could not be loaded. You can still document this follow-up.</p></section>';
  if (!context.available) return heading + '<p>No saved interview medicine record is available. Do not treat this as an empty current medicine list.</p></section>';
  const rows = context.medicines || [];
  return heading + warning + (rows.length ? '<div class="interview-table"><table><thead><tr><th>Medicine / origin</th><th>Directions on referral</th><th>At interview</th><th>Medicine use at interview</th><th>Recorded reference</th></tr></thead><tbody>' + rows.map(row => {
    const ref = row.reference;
    const reference = ref ? `${ref.display} (${String(ref.source).toUpperCase()} ${ref.code}, release ${ref.release})` : 'No reference linked';
    return `<tr><td>${esc(row.name)}<br><small>${esc(row.origin)}</small></td><td>${esc(row.listed_directions || 'Not recorded')}</td><td>${esc(row.interview_directions || 'Not recorded')}</td><td>${esc(row.use)}</td><td>${esc(reference)}</td></tr>`;
  }).join('') + '</tbody></table></div>' : '<p>No medicine rows were recorded in the saved interview. Confirm the current list separately.</p>') + '</section>';
}
