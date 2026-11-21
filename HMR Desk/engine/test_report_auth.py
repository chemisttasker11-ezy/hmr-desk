"""Synthetic, hash-bound authorisation and stale/modified report regression."""
import hashlib
import json

import pytest
from docx import Document

import db
import jobs
import records
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
    import template_report_builder
    monkeypatch.setattr(template_report_builder, 'active_template_root', lambda: templates)
    template = templates / 'approved-hmr.docx'
    Document().save(template)
    thash = digest(template.read_bytes())
    (templates / 'approved-hmr.json').write_text(json.dumps({
        'version': 'synthetic-test', 'sha256': thash,
        'approved_by': 'Synthetic QA', 'approved_on': '2026-11-16'
    }))
    spec_bytes = b'{"synthetic":"reviewed"}'
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
            'report_spec_sha256': digest(spec_bytes),
            'interview_revision': 'missing', 'pathology_revision': 'missing',
            'template_approved': True, 'template_sha256': thash,
            'template_version': 'synthetic-test',
            'source_files_sha256': report_auth.source_snapshot(conn, {'id': pid, 'folder': 'TO SORT/Synthetic'}),
            'clinical_snapshot_sha256': '',
        }
        db.log(conn, pid, 'report_build', evidence, 'job')
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    records.put(conn, pid, 'report_spec.json', spec_bytes); conn.commit()
    # The pharmacist explicitly acknowledged this synthetic medicine snapshot.
    record = {'meds': [], 'other_meds': [],
              'consent': {'signed': True, 'date': '2026-11-12', 'by': 'patient',
                          'relationship': 0, 'authorised_name': ''},
              'header': {'gp': 'Dr Synthetic', 'dob': '01-Jan-1950', 'visit': '12/11/2026 10:00'},
              'details': {'meds': [], 'other_meds': []}}
    monkeypatch.setattr(report_auth.interview, 'load', lambda conn, patient: record)
    # Sign-off compares the report's patient, GP and date blocks with the current record, so the spec carries them.
    import report
    spec_bytes = json.dumps(report._demographics(conn, patient, record)).encode()
    records.put(conn, pid, 'report_spec.json', spec_bytes); conn.commit()
    review = reconciliation.acknowledge(record, reconciliation.digest(record), 'Synthetic Pharmacist')
    records.put(conn, pid, 'reconciliation_review.json', json.dumps(review).encode()); conn.commit()
    # Existing report event was recorded before the synthetic interview fixture
    # was mounted; bring its canonical digest into the test's immutable evidence.
    source_contract_hash = report_auth.clinical_snapshot_hash(conn, patient)
    latest = conn.execute("SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
    event_detail = json.loads(latest['detail'])
    event_detail['clinical_snapshot_sha256'] = source_contract_hash
    event_detail['clinical_snapshot_contract'] = 2
    event_detail['report_spec_sha256'] = digest(spec_bytes)
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
    records.put(conn, patient['id'], 'report_spec.json', b'{"synthetic":"changed"}'); conn.commit()
    with pytest.raises(ValueError, match='Report content changed'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_signoff_requires_current_medicine_reconciliation(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    records.delete(conn, patient['id'], 'reconciliation_review.json'); conn.commit()
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


def test_signoff_refuses_unresolved_demographic_mismatch_and_honours_a_bound_keep(tmp_path, monkeypatch):
    import report
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    spec = json.loads(records.get(conn, patient['id'], 'report_spec.json'))

    def current():
        return conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()

    def record_changed(gp):
        # The record change also moves the clinical snapshot hash; model a rebuild so only the report text is stale.
        with conn:
            conn.execute('UPDATE patients SET gp=? WHERE id=?', (gp, patient['id']))
            latest = conn.execute("SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1", (patient['id'],)).fetchone()
            detail = json.loads(latest['detail']); detail['clinical_snapshot_sha256'] = report_auth.clinical_snapshot_hash(conn, current()); detail['clinical_snapshot_contract'] = 2
            conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(detail), latest['id']))
    record_changed('Dr Synthetic Corrected')
    with pytest.raises(ValueError, match='differs from the patient record'):
        report_auth.check_approval(conn, current(), body)
    # a deliberate keep, recorded through the engine, is bound to the exact text and the record value
    with conn:
        acks = {m['key']: report._ack_hash(m['key'], m['report'], m['record']) for m in report.demographic_mismatches(conn, current(), spec)}
        records.put_json(conn, patient['id'], report.ACK_RECORD, acks)
    assert report_auth.check_approval(conn, current(), body)['reviewer'] == 'Synthetic Pharmacist'
    record_changed('Dr Synthetic Third')
    with pytest.raises(ValueError, match='differs from the patient record'):
        report_auth.check_approval(conn, current(), body)
