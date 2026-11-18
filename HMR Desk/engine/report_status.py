"""Display-only report currency: is the latest built report still based on the saved clinical record?

Never an approval. Sign-off and sending keep using report_auth.check_approval and
report_auth.check_sent. This reads the same recorded build evidence and lists
reasons it no longer matches, so screens do not show an old report as current.
"""
import json
from pathlib import Path

import interview
import jobs
import pathology_records
import records
import report_auth

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
    except (OSError, ValueError, TypeError):
        reasons.append('cannot_verify')
    return reasons


def report_status(conn, patient):
    detail = _latest_build(conn, patient)
    signed = conn.execute(
        "SELECT 1 FROM events WHERE patient_id=? AND type='signed_off' LIMIT 1", (patient['id'],)).fetchone()
    out = {'status': 'not_generated', 'reasons': [], 'file': '', 'signed_off': bool(signed),
           'signed_version_intact': None, 'note': NOTE}
    if detail:
        reasons = _reasons(conn, patient, detail)
        out.update(status='outdated' if reasons else 'current', reasons=reasons, file=str(detail.get('file', '')))
    if signed:
        try:
            out['signed_version_intact'] = bool(report_auth.check_sent(conn, patient))
        except ValueError:
            out['signed_version_intact'] = False
    return out
