"""Synthetic end-to-end sign-off -> sent interaction-evidence freshness.

The installed production route stores approval payload in signed_off events.
The event must carry the exact interaction digest that passed sign-off, so a
subsequent altered interaction check cannot authorise the 'sent' transition.
"""
import json

import pytest

import db
import report_auth
from test_report_auth import case


def test_sent_refuses_changed_interaction_evidence_after_signoff(tmp_path, monkeypatch):
    import interaction_scope
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    state = {'digest': 'synthetic-current-interactions'}
    monkeypatch.setattr(interaction_scope, 'evidence_digest',
                        lambda _conn, _patient: state['digest'])
    event = conn.execute(
        "SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
        (patient['id'],)
    ).fetchone()
    build = json.loads(event['detail'])
    build['interactions_evidence_sha256'] = state['digest']
    with conn:
        conn.execute('UPDATE events SET detail=? WHERE id=?',
                     (json.dumps(build), event['id']))
    signed = report_auth.check_approval(conn, patient, body)
    assert signed['interactions_evidence_sha256'] == state['digest']
    with conn:
        db.log(conn, patient['id'], 'signed_off', signed, 'app')
    assert report_auth.check_sent(conn, patient)
    state['digest'] = 'synthetic-new-interactions'
    with pytest.raises(ValueError, match='Interaction evidence changed'):
        report_auth.check_sent(conn, patient)
    conn.close()


def test_legacy_signed_event_without_interaction_marker_remains_legacy_compatible(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    signed = report_auth.check_approval(conn, patient, body)
    assert 'interactions_evidence_sha256' not in signed
    with conn:
        db.log(conn, patient['id'], 'signed_off', signed, 'app')
    assert report_auth.check_sent(conn, patient)
    conn.close()
