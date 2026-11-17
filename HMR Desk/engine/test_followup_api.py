"""Executable API regressions for follow-up rules (PPA HMR Program Rules Oct 2026 s5.9, s8). Synthetic data only."""
import datetime as dt, json, os
import pytest
import api, db, records, followup


@pytest.fixture()
def env(tmp_path):
    db.BASE = str(tmp_path)
    (tmp_path / 'patient').mkdir()
    conn = db.connect(str(tmp_path / 't.db'))
    conn.execute("INSERT INTO patients(key,name,state,folder) VALUES ('a','Synthetic Patient','claimed','patient')")
    conn.execute("INSERT INTO visits(patient_id,kind,visit_date,report_sent,claimed,source) VALUES (1,'hmr','2026-01-01','2026-01-02','2026-01-02','app')")
    conn.commit()
    return conn


def call(conn, method, route, body=None):
    return api.handle(conn, method, '/api/patients/1/' + route, {}, body or {})


def record(**kw):
    base = dict(date='', method='', preferred_method='', choice_offered_on='', spoke_with='', med_changes='', recommendations=[], issues='', outcome='', notes='')
    return {**base, **kw}


def test_calendar_month_alerts_and_claim_by(env):
    for day, alerts in [('2026-01-31', []), ('2026-02-01', ['follow-up 1 due']), ('2026-10-01', ['follow-up 1 due']), ('2026-10-02', [])]:
        assert api.patient_followups(env, 1, dt.date.fromisoformat(day))['alerts'] == alerts
    env.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (1,'followup1','2026-02-01','app')"); env.commit()
    r = api.patient_followups(env, 1, dt.date(2026, 3, 1))
    assert r['alerts'] == ['follow-up 1 to claim', 'follow-up 2 due'] and r['followup2_due'] == '2026-03-01'
    assert r['followup1_claim_by'] == '2026-03-31' and r['rule_basis'] == 'calendar-months-provisional'


def test_stored_day_override_is_visible(env):
    env.execute("INSERT INTO meta(key,value) VALUES ('followup_first_after_days','45')"); env.commit()
    r = api.patient_followups(env, 1, dt.date(2026, 2, 14))
    assert r['rule_basis'] == 'custom-days-override' and r['first_due'] == '2026-02-15'


def test_pre_nov_followup_is_historical_and_claimable(env):
    assert call(env, 'POST', 'action', {'action': 'followup_done', 'kind': 'followup1', 'date': '2026-02-01'})[0] == 200
    assert call(env, 'POST', 'action', {'action': 'followup_claimed', 'kind': 'followup1', 'date': '2026-02-20'})[0] == 200


def test_post_nov_followup_cannot_be_claimed_or_exported_undocumented(env):
    assert call(env, 'POST', 'action', {'action': 'followup_done', 'kind': 'followup1', 'date': '2026-11-10'})[0] == 200
    status, body = call(env, 'POST', 'action', {'action': 'followup_claimed', 'kind': 'followup1', 'date': '2026-11-11'})
    assert status == 400 and 'documented' in body['error']
    r = api.patient_followups(env, 1, dt.date(2026, 11, 12))
    assert r['next_action'] == 'followup1_document' and 'follow-up 1 documentation incomplete' in r['alerts'] and r['followup1_documentation_gaps']
    # saving a draft stays possible, and urgent or incomplete records are retained
    assert call(env, 'POST', 'followup/1', record(date='2026-11-10', method='video'))[0] == 200
    status, saved = call(env, 'GET', 'followup/1')
    assert status == 200 and len(saved['review_issues']) == 2
    assert call(env, 'POST', 'followup/1/export')[0] == 400
    assert call(env, 'POST', 'action', {'action': 'followup_claimed', 'kind': 'followup1', 'date': '2026-11-11'})[0] == 400
    # documented, then both are allowed
    assert call(env, 'POST', 'followup/1', record(date='2026-11-10', method='video', preferred_method='video', choice_offered_on='2026-11-03'))[0] == 200
    assert call(env, 'POST', 'followup/1/export')[0] == 200
    assert call(env, 'POST', 'action', {'action': 'followup_claimed', 'kind': 'followup1', 'date': '2026-11-11'})[0] == 200


def test_telehealth_against_face_to_face_preference_blocks_claim(env):
    call(env, 'POST', 'followup/1', record(date='2026-11-10', method='phone', preferred_method='in person', choice_offered_on='2026-11-03'))
    status, body = call(env, 'POST', 'action', {'action': 'followup_claimed', 'kind': 'followup1', 'date': '2026-11-11'})
    assert status == 400 and 'face-to-face' in body['error']
