"""Real sign-off evidence for the older full-length script tests (synthetic data only).

The sign-off gate needs an explicit pharmacist review, an owner-approved template, a built Word and PDF pair bound by
checksum, a current source snapshot and an acknowledged medicine reconciliation. The scripts that predate the gate
used to call `signed_off` with no evidence. Instead of bypassing `report_auth.check_approval`, `approve()` builds that
evidence for one synthetic patient in the script's own temporary database, so the gate runs unchanged and the later
sections of those scripts execute.
"""
import contextlib
import hashlib
import json
import tempfile
from pathlib import Path

from docx import Document

import db
import jobs
import records
import reconciliation
import report
import report_auth
import template_report_builder


def _digest(data):
    return hashlib.sha256(data).hexdigest()


_ASSETS = {}
_RECORD = {}


@contextlib.contextmanager
def reviewed_interview():
    """Serve the pharmacist-acknowledged interview record only while the sign-off request runs."""
    original = report_auth.interview.load
    report_auth.interview.load = lambda conn, patient: dict(_RECORD)
    try:
        yield
    finally:
        report_auth.interview.load = original


def _templates():
    if not _ASSETS:
        root = Path(tempfile.mkdtemp(prefix='hmr-legacy-assets-'))
        templates = root / 'templates'
        templates.mkdir()
        template = templates / 'approved-hmr.docx'
        Document().save(template)
        thash = _digest(template.read_bytes())
        (templates / 'approved-hmr.json').write_text(json.dumps(
            {'version': 'synthetic-test', 'sha256': thash, 'approved_by': 'Synthetic QA', 'approved_on': '2026-11-16'}))
        _ASSETS.update(root=root, templates=templates, thash=thash)
    jobs.APP_ASSETS = _ASSETS['root']
    template_report_builder.active_template_root = lambda: _ASSETS['templates']
    return _ASSETS['thash']


def approve(conn, pid, name='HMR Synthetic'):
    """Build approved evidence for patient `pid`; return the exact sign-off request body."""
    thash = _templates()
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    folder = jobs.patient_folder(patient)
    word = folder / (name + '.docx')
    pdf = folder / (name + '.pdf')
    word.write_bytes(b'synthetic DOCX representation')
    pdf.write_bytes(b'%PDF-1.4\nsynthetic')
    record = {'meds': [], 'other_meds': [],
              'consent': {'signed': True, 'date': '2026-11-12', 'by': 'patient', 'relationship': 0, 'authorised_name': ''},
              'header': {'gp': 'Dr Synthetic', 'dob': '01-Jan-1950', 'visit': '12/11/2026 10:00'},
              'details': {'meds': [], 'other_meds': []}}
    _RECORD.clear(); _RECORD.update(record)
    with reviewed_interview():
        spec_bytes = json.dumps(report._demographics(conn, patient, record)).encode()
    records.put(conn, pid, 'report_spec.json', spec_bytes)
    review = reconciliation.acknowledge(record, reconciliation.digest(record), 'Synthetic Pharmacist')
    records.put(conn, pid, 'reconciliation_review.json', json.dumps(review).encode())
    conn.commit()
    with reviewed_interview():
        snapshot = report_auth.clinical_snapshot_hash(conn, patient)
    evidence = {'file': word.name, 'sha256': _digest(word.read_bytes()), 'pdf_sha256': _digest(pdf.read_bytes()),
                'report_spec_sha256': _digest(spec_bytes), 'interview_revision': 'missing', 'pathology_revision': 'missing',
                'template_approved': True, 'template_sha256': thash, 'template_version': 'synthetic-test',
                'source_files_sha256': report_auth.source_snapshot(conn, patient),
                'clinical_snapshot_sha256': snapshot,
                'clinical_snapshot_contract': 2}
    with conn:
        db.log(conn, pid, 'report_build', evidence, 'job')
    return {'action': 'signed_off', 'report_file': word.name, 'report_sha256': evidence['sha256'],
            'reviewer': 'Synthetic Pharmacist', 'clinical_reviewed': True}
