"""Display-only report currency status. Authorisation stays with report_auth."""
import json

import db
import records
import report_auth
import report_status
from test_report_auth import case


def sign(conn, patient, body):
    proof = report_auth.check_approval(conn, patient, body)
    with conn:
        db.log(conn, patient['id'], 'signed_off', proof, 'app')


def test_no_build_is_not_generated(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    with conn:
        conn.execute("DELETE FROM events WHERE type='report_build'")
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'not_generated' and s['signed_off'] is False
    conn.close()


def test_matching_build_is_current_but_not_signed(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'current' and s['reasons'] == [] and s['signed_off'] is False
    assert s['file'] == 'HMR Synthetic.docx'
    conn.close()


def test_changed_report_content_or_files_make_it_outdated_with_reasons(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    records.put(conn, patient['id'], 'report_spec.json', b'{"edited":"after build"}'); conn.commit()
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'outdated' and 'report_content_changed' in s['reasons']
    (folder / 'HMR Synthetic.docx').write_bytes(b'outside edit')
    assert 'document_changed' in report_status.report_status(conn, patient)['reasons']
    conn.close()


def test_interview_or_pathology_change_makes_it_outdated(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    monkeypatch.setattr(report_status.interview, 'revision', lambda c, p: 'changed')
    assert 'interview_changed' in report_status.report_status(conn, patient)['reasons']
    monkeypatch.setattr(report_status.pathology_records, 'revision', lambda c, p: 'changed')
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'outdated' and {'interview_changed', 'pathology_changed'} <= set(s['reasons'])
    conn.close()


def test_signed_state_follows_the_signed_version_and_never_authorises(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    sign(conn, patient, body)
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'current' and s['signed_off'] is True and s['signed_version_intact'] is True
    (folder / 'HMR Synthetic.pdf').write_bytes(b'PDF modified outside application')
    s = report_status.report_status(conn, patient)
    assert s['signed_off'] is True and s['signed_version_intact'] is False
    assert 'authoris' in s['note'].lower() or 'sign-off' in s['note'].lower()
    conn.close()
