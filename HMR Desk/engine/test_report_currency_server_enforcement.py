"""Server side sign-off must refuse whenever report currency is not 'current' (synthetic data only).

The desktop gates the sign-off button on /report-status. These tests pin that the engine itself
refuses a stale, missing or unverifiable build, so the screen is never the only guard.
"""
import json

import pytest

import report_auth
import report_status
from test_report_auth import case


def test_current_build_is_current_and_approval_passes(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert report_status.report_status(conn, patient)['status'] == 'current'
    assert report_auth.check_approval(conn, patient, body)
    conn.close()


def test_missing_build_is_not_generated_and_approval_refused(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    with conn:
        conn.execute("DELETE FROM events WHERE patient_id=? AND type='report_build'", (patient['id'],))
    assert report_status.report_status(conn, patient)['status'] == 'not_generated'
    with pytest.raises(ValueError):
        report_auth.check_approval(conn, patient, body)
    conn.close()


@pytest.mark.parametrize('change', ['word', 'pdf', 'source', 'spec'])
def test_stale_build_is_outdated_and_approval_refused(tmp_path, monkeypatch, change):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    if change == 'word':
        (folder / 'HMR Synthetic.docx').write_bytes(b'edited outside')
    elif change == 'pdf':
        (folder / 'HMR Synthetic.pdf').write_bytes(b'edited outside')
    elif change == 'source':
        (folder / 'referral.pdf').write_bytes(b'changed source')
    else:
        import records
        records.put(conn, patient['id'], 'report_spec.json', b'{"changed":1}'); conn.commit()
    assert report_status.report_status(conn, patient)['status'] == 'outdated'
    with pytest.raises(ValueError):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_unreadable_build_evidence_is_never_current_and_approval_refused(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    with conn:
        conn.execute("UPDATE events SET detail='not json' WHERE patient_id=? AND type='report_build'", (patient['id'],))
    assert report_status.report_status(conn, patient)['status'] != 'current'
    with pytest.raises(ValueError):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_unverifiable_check_reports_cannot_verify_not_current(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    def boom(*a, **k):
        raise OSError('unreadable')
    monkeypatch.setattr(report_auth, 'source_snapshot', boom)
    status = report_status.report_status(conn, patient)
    assert status['status'] == 'outdated' and 'cannot_verify' in status['reasons']
    with pytest.raises(OSError):
        report_auth.check_approval(conn, patient, body)  # fails closed too, never approves
    conn.close()


def test_approval_needs_the_selected_current_file_and_checksum(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    for bad in ({**body, 'report_sha256': '0' * 64}, {**body, 'report_file': 'Other.docx'}):
        with pytest.raises(ValueError):
            report_auth.check_approval(conn, patient, bad)
    conn.close()
