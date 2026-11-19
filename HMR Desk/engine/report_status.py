"""Display-only report currency: is the latest built report still based on the saved clinical record?

Never an approval. Sign-off and sending keep using report_auth.check_approval and
report_auth.check_sent. This reads the same recorded build evidence and lists
reasons it no longer matches, so screens do not show an old report as current.
"""
import json
import logging
from pathlib import Path

import interview
import jobs
import pathology_records
import records
import report_auth
import reconciliation

READY_NOTE = 'Checklist of recorded state only. It is not clinical sign-off and does not approve the report.'
log = logging.getLogger('hmr.report_status')


def _unverifiable(where, error):
    # Display only: whatever cannot be read is shown as unknown / cannot_verify, never as current or ready.
    # Log the failing step and error type only, not the message (it can carry a patient file path).
    log.warning('report status could not check %s (%s)', where, type(error).__name__)


NOTE = 'Display status only. Pharmacist sign-off and sending are still checked separately.'


def _latest_build(conn, patient):
    row = conn.execute(
        "SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
        (patient['id'],)).fetchone()
    try:
        detail = json.loads(row['detail'] or '{}') if row else None
    except (ValueError, TypeError):
        return None
    return detail if isinstance(detail, dict) and detail else None


def _reasons(conn, patient, detail):
    reasons = []
    root = jobs.patient_folder(patient).resolve()
    name = detail.get('file', '')
    file = (root / name).resolve() if isinstance(name, str) and Path(name).name == name and name else None
    try:
        if not file or file.parent != root or not file.is_file() or report_auth.digest(file) != detail.get('sha256'):
            reasons.append('document_changed')
        pdf = file.with_suffix('.pdf') if file else None
        if not pdf or not pdf.is_file() or report_auth.digest(pdf) != detail.get('pdf_sha256'):
            reasons.append('pdf_changed')
        spec = records.get(conn, patient['id'], 'report_spec.json')
        import hashlib
        if spec is None or hashlib.sha256(spec).hexdigest() != detail.get('report_spec_sha256'):
            reasons.append('report_content_changed')
        if interview.revision(conn, patient) != detail.get('interview_revision'):
            reasons.append('interview_changed')
        if pathology_records.revision(conn, patient) != detail.get('pathology_revision'):
            reasons.append('pathology_changed')
        if detail.get('source_files_sha256') != report_auth.source_snapshot(conn, patient):
            reasons.append('source_files_changed')
        if detail.get('clinical_snapshot_sha256') != report_auth.clinical_snapshot_hash(conn, patient):
            reasons.append('clinical_record_changed')
    except Exception as error:  # an unreadable file or record is not a reason to fail the whole status
        _unverifiable('build evidence', error)
        reasons.append('cannot_verify')
    return reasons


def _item(key, label, state):
    return {'key': key, 'label': label, 'state': state}


def _safe(key, label, check):
    try:
        return _item(key, label, check())
    except Exception as error:
        _unverifiable(key, error)
        return _item(key, label, 'unknown')


def readiness(conn, patient):
    """Existing validated state shown as met / not_met / unknown. Never a pass, never approval."""
    def consent():
        # Reflect the same recorded interview consent contract enforced at sign-off.
        # A checked but undated consent must not show as completed.
        return 'met' if report_auth.consent_for_approval(interview.load(conn, patient)) else 'not_met'

    def meds():
        saved = records.get_json(conn, patient['id'], 'reconciliation_review.json') or {}
        return 'met' if reconciliation.review_status(interview.load(conn, patient), saved)['reviewed'] else 'not_met'

    def demographics():
        spec_bytes = records.get(conn, patient['id'], 'report_spec.json')
        if spec_bytes is None:
            return 'unknown'
        import report
        return 'not_met' if report.unresolved_demographics(conn, patient, json.loads(spec_bytes.decode('utf-8-sig'))) else 'met'

    return {'items': [_safe('consent_recorded', 'Patient consent recorded', consent),
                      _safe('medicines_reconciled', 'Medicine reconciliation reviewed for the current interview', meds),
                      _safe('demographics_match', 'Report patient, GP and date match the record', demographics)],
            'clinically_ready': None, 'note': READY_NOTE}


def report_status(conn, patient):
    detail = _latest_build(conn, patient)
    signed = conn.execute(
        "SELECT 1 FROM events WHERE patient_id=? AND type='signed_off' LIMIT 1", (patient['id'],)).fetchone()
    out = {'status': 'not_generated', 'reasons': [], 'file': '', 'signed_off': bool(signed),
           'signed_version_intact': None, 'note': NOTE, 'readiness': readiness(conn, patient)}
    if detail:
        reasons = _reasons(conn, patient, detail)
        out.update(status='outdated' if reasons else 'current', reasons=reasons, file=str(detail.get('file', '')))
    if signed:
        try:
            out['signed_version_intact'] = bool(report_auth.check_sent(conn, patient))
        except ValueError:
            out['signed_version_intact'] = False
    return out
