"""Synthetic acceptance contract: report sign-off uses consent already recorded in interview."""
import json

import pytest

import report_auth
import report_status
from test_report_auth import case


@pytest.mark.parametrize('consent', [
    None,
    {},
    {'signed': False, 'date': '2026-11-12', 'by': 'patient'},
    {'signed': True, 'date': '', 'by': 'patient'},
    {'signed': True, 'date': '2026-13-44', 'by': 'patient'},
    {'signed': True, 'date': '2026-11-12', 'by': 'unknown'},
    {'signed': True, 'date': '2026-11-12', 'by': 'authorised',
     'relationship': 0, 'authorised_name': 'Synthetic Guardian'},
    {'signed': True, 'date': '2026-11-12', 'by': 'authorised',
     'relationship': 2, 'authorised_name': ' '},
])
def test_invalid_or_missing_interview_consent_refuses_report_signoff(tmp_path, monkeypatch, consent):
    conn, patient, _, body = case(tmp_path, monkeypatch)
    record = report_auth.interview.load(conn, patient)
    record['consent'] = consent
    # Rebuild the synthetic clinical-source checksum so no unrelated stale-build
    # failure masks the specific missing-consent gate.
    latest = conn.execute(
        "SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
        (patient['id'],),
    ).fetchone()
    evidence = json.loads(latest['detail'])
    evidence['clinical_snapshot_sha256'] = report_auth.clinical_snapshot_hash(conn, patient)
    evidence['clinical_snapshot_contract'] = 2
    with conn:
        conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(evidence), latest['id']))
    displayed = report_status.report_status(conn, patient)
    states = {item['key']: item['state'] for item in displayed['readiness']['items']}
    assert states['consent_recorded'] == 'not_met'
    with pytest.raises(ValueError, match='Signed, dated patient consent'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def test_interview_patient_consent_allows_report_authorisation_without_a_pdf(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert not list(folder.glob('PPA Consent* signed.pdf'))
    assert {item['key']: item['state'] for item in report_status.report_status(conn, patient)['readiness']['items']}['consent_recorded'] == 'met'
    assert report_auth.check_approval(conn, patient, body)['clinical_reviewed'] is True
    conn.close()


def test_interview_authorised_person_consent_is_accepted_with_complete_details(tmp_path, monkeypatch):
    conn, patient, _, body = case(tmp_path, monkeypatch)
    record = report_auth.interview.load(conn, patient)
    record['consent'] = {'signed': True, 'date': '2026-11-12', 'by': 'authorised',
                         'relationship': 2, 'authorised_name': 'Synthetic Guardian'}
    latest = conn.execute(
        "SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
        (patient['id'],),
    ).fetchone()
    evidence = json.loads(latest['detail'])
    evidence['clinical_snapshot_sha256'] = report_auth.clinical_snapshot_hash(conn, patient)
    evidence['clinical_snapshot_contract'] = 2
    with conn:
        conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(evidence), latest['id']))
    assert {item['key']: item['state'] for item in report_status.report_status(conn, patient)['readiness']['items']}['consent_recorded'] == 'met'
    assert report_auth.check_approval(conn, patient, body)['clinical_reviewed'] is True
    conn.close()
