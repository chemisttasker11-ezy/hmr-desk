"""Characterization of the patient action state machine (patient_actions.py).

Every expected value is a literal recorded from the engine before the code moved out of api.py.
"""
import datetime as dt

import pytest

import api
import db
import patient_actions


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 't.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    return db.connect()


def _patient(conn, state):
    n = conn.execute('SELECT count(*) FROM patients').fetchone()[0] + 1
    conn.execute('INSERT INTO patients(key,name,gp,state) VALUES (?,?,?,?)', (str(n), 'Patient %d' % n, 'GP', state))
    conn.commit()
    return conn.execute('SELECT * FROM patients WHERE id=last_insert_rowid()').fetchone()['id']


def _act(conn, state, name, **kw):
    pid = _patient(conn, state)
    row = lambda: conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    try:
        result = api.action(conn, row(), {'action': name, **kw})
        return ('ok', result, row()['state'])
    except ValueError as e:
        return ('err', str(e), row()['state'])


SOON = (dt.date.today() + dt.timedelta(days=3)).isoformat()
SLOT = {'date': SOON, 'time': '09:00', 'end': '10:00'}

CASES = [
    ('new', 'book_phone', {}, ('err', 'invalid date', 'new')),
    ('new', 'book_phone', {'date': 'bad', 'time': '09:00', 'end': '10:00'}, ('err', 'invalid date', 'new')),
    ('new', 'book_phone', {'date': SOON, 'time': '07:00', 'end': '08:00'}, ('err', 'start must be after 08:00', 'new')),
    ('new', 'book_phone', {'date': SOON, 'time': '10:00', 'end': '09:00'}, ('err', 'end must be after start', 'new')),
    ('new', 'book_phone', SLOT, ('ok', {'ok': True}, 'confirmed')),
    ('new', 'move', SLOT, ('err', 'move needs a booked visit', 'new')),
    ('confirmed', 'move', {'date': SOON, 'time': '11:00', 'end': '12:00'}, ('ok', {'ok': True}, 'confirmed')),
    ('new', 'hold', {}, ('ok', {'ok': True}, 'hold')),
    ('hold', 'hold', {}, ('ok', {'ok': True}, 'hold')),
    ('new', 'decline_phone', {}, ('err', 'patient folder missing', 'new')),
    ('new', 'visited', {}, ('err', 'invalid date', 'new')),
    ('confirmed', 'visited', {}, ('err', 'invalid date', 'confirmed')),
    ('visited', 'report_drafted', {}, ('ok', {'ok': True}, 'report_drafted')),
    ('new', 'report_sent', {}, ('err', 'invalid date', 'new')),
    ('new', 'claimed', {}, ('err', 'invalid date', 'new')),
    ('new', 'expired', {}, ('err', 'patient folder missing', 'new')),
    ('new', 'nonsense', {}, ('err', 'unknown action', 'new')),
    ('new', 'keep', {}, ('err', 'unknown action', 'new')),
    ('new', 'undo_stage', {}, ('err', 'Nothing to undo', 'new')),
    ('confirmed', 'undo_stage', {}, ('err', 'Nothing to undo', 'confirmed')),
    ('new', 'archive', {}, ('err', 'Cannot archive this patient', 'new')),
    ('new', 'claim_now', {'visit_date': 'bad', 'report_sent': 'bad'}, ('err', 'invalid date', 'new')),
    ('new', 'not_visited', {}, ('err', 'latest visit is not an automatic visit', 'new')),
    ('sent', 'followup_done', {}, ('err', 'invalid date', 'sent')),
    ('sent', 'followup_claimed', {}, ('err', 'invalid date', 'sent')),
]


@pytest.mark.parametrize('state,name,body,expected', CASES)
def test_action_outcomes(conn, state, name, body, expected):
    assert _act(conn, state, name, **body) == expected


def test_followup_date_rules_keep_their_values():
    assert str(api.add_months(dt.date(2026, 1, 31), 1)) == '2026-02-28'
    assert str(api.add_months(dt.date(2026, 11, 30), 3)) == '2027-02-28'
    assert str(api.claim_deadline(dt.date(2026, 5, 1))) == '2026-06-30'
    assert str(api.clock('09:30')) == '09:30:00'
    assert str(api.anydate('2026-11-18')) == '2026-11-18'


def test_api_reexports_are_the_module_functions():
    assert api.action is patient_actions.action
    assert api._action is patient_actions._action
