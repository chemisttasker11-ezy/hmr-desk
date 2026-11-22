// Display freshness for the interview form. When the window regains focus, check once whether the saved record changed elsewhere (API,
// MCP). A form with no unsaved edits reloads from the saved record; a form with unsaved edits keeps them and shows the existing
// conflict choice. Nothing is saved, merged or restored here, and the engine revision check on save is unchanged.
let interviewFreshnessBusy = false, interviewFreshnessAt = 0, interviewFreshnessNote = '';
async function interviewFreshnessCheck(force) {
  const patient = interviewId, request = interviewRequest, record = interviewRecord;
  if (page !== 'interview' || !patient || !record || interviewFreshnessBusy || interviewPathologyDirty) return 'skipped';
  if (!force && Date.now() - interviewFreshnessAt < 2000) return 'skipped';
  interviewFreshnessBusy = true; interviewFreshnessAt = Date.now();
  try {
    const result = await interviewSaver.checkRemote();
    // The patient, the screen load and the form object must be the ones the check started on, and nothing may have been typed meanwhile.
    const same = page === 'interview' && interviewId === patient && interviewRequest === request && interviewRecord === record;
    if (!same) return 'skipped';
    if (result === 'stale-clean') {
      if (interviewSaver.dirty() || interviewPathologyDirty) return 'skipped';
      interviewRecord = null;
      await interviewScreen();
      if (page === 'interview' && interviewId === patient && interviewRecord) { interviewFreshnessNote = 'Updated from saved data'; interviewSaveStatus = interviewFreshnessNote; if ($('interview-status')) $('interview-status').textContent = interviewFreshnessNote; }
      return 'reloaded';
    }
    return result;
  } finally { interviewFreshnessBusy = false; }
}
if (typeof window !== 'undefined') window.addEventListener('focus', () => { void interviewFreshnessCheck(); });
if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void interviewFreshnessCheck(); });
