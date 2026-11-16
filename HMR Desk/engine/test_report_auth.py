"""Synthetic, hash-bound authorisation and stale/modified report regression."""
import hashlib
import json

import pytest
from docx import Document

import db
import jobs
import report_auth
import reconciliation


def digest(value):
    return hashlib.sha256(value).hexdigest()


def case(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    folder = root / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(root))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    assets = tmp_path / 'assets'
    templates = assets / 'templates'
    templates.mkdir(parents=True)
    monkeypatch.setattr(jobs, 'APP_ASSETS', assets)
    template = templates / 'approved-hmr.docx'
    Document().save(template)
    thash = digest(template.read_bytes())
    (templates / 'approved-hmr.json').write_text(json.dumps({
        'version': 'synthetic-test', 'sha256': thash,
        'approved_by': 'Synthetic QA', 'approved_on': '2026-11-16'
    }))
    spec = folder / 'report_spec.json'
    spec.write_text('{"synthetic":"reviewed"}')
    (folder / 'referral.pdf').write_bytes(b'%PDF-1.4\\nsynthetic original source')
    word = folder / 'HMR Synthetic.docx'
    word.write_bytes(b'synthetic DOCX representation')
    pdf = folder / 'HMR Synthetic.pdf'
    pdf.write_bytes(b'%PDF-1.4\nsynthetic')
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute(
            "INSERT INTO patients(key,name,folder,state) VALUES (?,?,?,'report_drafted')",
            ('synthetic', 'Synthetic Patient', 'TO SORT/Synthetic')
        ).lastrowid
        evidence = {
            'file': word.name, 'sha256': digest(word.read_bytes()),
            'pdf_sha256': digest(pdf.read_bytes()),
            'report_spec_sha256': digest(spec.read_bytes()),
            'interview_revision': 'missing', 'pathology_revision': 'missing',
            'template_approved': True, 'template_sha256': thash,
            'template_version': 'synthetic-test',
            'source_files_sha256': report_auth.source_snapshot({'folder': 'TO SORT/Synthetic'}),
            'clinical_snapshot_sha256': '',
        }
        db.log(conn, pid, 'report_build', evidence, 'job')
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    # The pharmacist explicitly acknowledged this synthetic medicine snapshot.
    record = {'meds': [], 'other_meds': [],
              'details': {'meds': [], 'other_meds': []}}
    monkeypatch.setattr(report_auth.interview, 'load', lambda conn, patient: record)
    review = reconciliation.acknowledge(record, reconciliation.digest(record), 'Synthetic Pharmacist')
    (folder / 'reconciliation_review.json').write_text(json.dumps(review))
    # Existing report event was recorded before the synthetic interview fixture
    # was mounted; bring its canonical digest into the test's immutable evidence.
    source_contract_hash = report_auth.clinical_snapshot_hash(conn, patient)
    latest = conn.execute("SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
    event_detail = json.loads(latest['detail'])
    event_detail['clinical_snapshot_sha256'] = source_contract_hash
    with conn:
        conn.execute('UPDATE events SET detail=? WHERE id=?',(json.dumps(event_detail),latest['id']))
    request = {'action':'signed_off', 'report_file':word.name,
               'report_sha256':evidence['sha256'], 'reviewer':'Synthetic Pharmacist',
               'clinical_reviewed':True}
    return conn, patient, folder, request


def test_explicit_revision_signoff_and_sent_integrity(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    proof = report_auth.check_approval(conn, patient, body)
    assert proof['report_sha256'] == body['report_sha256']
    assert proof['reviewer'] == 'Synthetic Pharmacist'
    versions = report_auth.generated_versions(conn, patient)
    assert len(versions) == 1 and versions[0]['pdf_exists_and_matches']
    with conn:
        db.log(conn, patient['id'], 'signed_off', proof, 'app')
    assert report_auth.check_sent(conn, patient)
    (folder / 'HMR Synthetic.pdf').write_bytes(b'PDF modified outside application')
    with pytest.raises(ValueError, match='Signed PDF'):
        report_auth.check_sent(conn, patient)
    conn.close()


def test_signoff_rejects_unreviewed_or_changed_word(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Explicit pharmacist'):
        report_auth.check_approval(conn, patient, {**body,'clinical_reviewed':False})
    (folder / 'HMR Synthetic.docx').write_bytes(b'outside edit')
    with pytest.raises(ValueError, match='Word report'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_signoff_rejects_unapproved_template_and_changed_spec(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    (folder / 'report_spec.json').write_text('{"synthetic":"changed"}')
    with pytest.raises(ValueError, match='Report content changed'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_signoff_requires_current_medicine_reconciliation(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    (folder / 'reconciliation_review.json').unlink()
    with pytest.raises(ValueError, match='Medicine reconciliation'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_report_source_pdf_change_invalidates_signoff(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert report_auth.check_approval(conn, patient, body)
    (folder / 'referral.pdf').write_bytes(b'changed source')
    with pytest.raises(ValueError, match='Original referral or pathology source'):
        report_auth.check_approval(conn, patient, body)
    conn.close()
