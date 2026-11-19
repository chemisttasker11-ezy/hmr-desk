"""An unreadable referral PDF with no saved interview must not break the display-only report status.

report_status reads the interview record. When none is saved, interview.load rebuilds a blank one from the
referral PDF, and an unopenable PDF raised FileDataError out of the whole /report-status call. The status
stays display only: what cannot be checked is shown as unknown / cannot_verify, never as current or ready.
"""
import json

import interview
import records
import report_status
from test_report_auth import case

REAL_LOAD = interview.load


def unreadable_case(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    monkeypatch.setattr(interview, 'load', REAL_LOAD)   # case() mounts a fixture record; use the real loader
    assert not records.exists(conn, patient['id'], 'interview.json')
    (folder / 'referral.pdf').write_bytes(b'this is not a pdf')
    return conn, patient, folder


def test_unreadable_referral_without_saved_interview_still_returns_status(tmp_path, monkeypatch):
    conn, patient, folder = unreadable_case(tmp_path, monkeypatch)
    status = report_status.report_status(conn, patient)       # used to raise FileDataError
    assert status['status'] != 'current'
    assert 'cannot_verify' in status['reasons']
    assert {i['state'] for i in status['readiness']['items']} == {'unknown'}
    assert status['readiness']['clinically_ready'] is None
    assert status['signed_off'] is False
    conn.close()


def test_status_route_returns_200_with_unverified_state_not_an_engine_error(tmp_path, monkeypatch):
    import api
    conn, patient, folder = unreadable_case(tmp_path, monkeypatch)
    code, body = api.handle(conn, 'GET', f"/api/patients/{patient['id']}/report-status", {}, None)
    assert code == 200 and body['status'] != 'current' and 'error' not in body
    assert 'cannot_verify' in body['reasons']
    conn.close()


def test_a_readable_saved_interview_is_unaffected(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    status = report_status.report_status(conn, patient)
    assert status['status'] == 'current' and 'cannot_verify' not in status['reasons']
    conn.close()


def boom(*_a, **_k):
    raise RuntimeError('synthetic failure with a private path /patients/Synthetic')


def test_any_failure_while_checking_the_build_is_cannot_verify_never_current(tmp_path, monkeypatch, caplog):
    targets = (('report_auth', report_status.report_auth, 'clinical_snapshot_hash'),
               ('report_auth', report_status.report_auth, 'source_snapshot'),
               ('pathology', report_status.pathology_records, 'revision'),
               ('interview', report_status.interview, 'revision'))
    for label, module, name in targets:
        conn, patient, folder, body = case(tmp_path / f'{label}-{name}', monkeypatch)
        with monkeypatch.context() as m:
            m.setattr(module, name, boom)
            caplog.clear()
            with caplog.at_level('WARNING', logger='hmr.report_status'):
                status = report_status.report_status(conn, patient)
        assert status['status'] == 'outdated' and 'cannot_verify' in status['reasons'], name
        assert status['signed_off'] is False
        messages = ' '.join(r.getMessage() for r in caplog.records)
        assert 'build evidence' in messages and 'RuntimeError' in messages, name
        assert 'private path' not in messages and '/patients/' not in messages, name   # type only, never the message
        conn.close()


def test_a_failing_readiness_check_is_unknown_and_logged_without_the_message(tmp_path, monkeypatch, caplog):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    monkeypatch.setattr(report_status.reconciliation, 'review_status', boom)
    with caplog.at_level('WARNING', logger='hmr.report_status'):
        status = report_status.report_status(conn, patient)
    states = {i['key']: i['state'] for i in status['readiness']['items']}
    assert states['medicines_reconciled'] == 'unknown'
    assert status['readiness']['clinically_ready'] is None
    messages = ' '.join(r.getMessage() for r in caplog.records)
    assert 'medicines_reconciled' in messages and 'RuntimeError' in messages and 'private path' not in messages
    conn.close()


def test_corrupt_report_spec_or_missing_build_files_are_not_current(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    records.put(conn, patient['id'], 'report_spec.json', b'{not json'); conn.commit()
    status = report_status.report_status(conn, patient)
    assert status['status'] == 'outdated' and 'report_content_changed' in status['reasons']
    (folder / 'HMR Synthetic.docx').unlink()
    (folder / 'HMR Synthetic.pdf').unlink()
    status = report_status.report_status(conn, patient)
    assert status['status'] == 'outdated' and {'document_changed', 'pdf_changed'} <= set(status['reasons'])
    conn.close()


def test_status_never_reaches_the_approval_gates(tmp_path, monkeypatch):
    # Authorisation stays in report_auth: a failing status check must not change what check_approval decides.
    import report_auth
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    before = report_auth.check_approval(conn, patient, body)
    assert report_status.report_status(conn, patient)['status'] == 'current'
    with monkeypatch.context() as m:
        m.setattr(report_status.interview, 'revision', boom)       # status degrades; the gate is a separate module
        assert report_status.report_status(conn, patient)['status'] == 'outdated'
    after = report_auth.check_approval(conn, patient, body)
    assert after == before
    assert 'report_status' not in open(report_auth.__file__, encoding='utf-8').read()
    conn.close()
