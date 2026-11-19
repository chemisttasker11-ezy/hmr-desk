"""A patient added through New referrals starts in state 'new'. Its next step must be a real, working action.

The retired intake_dry job only refuses ("Use New referrals..."), so it must never be offered as a next step.
"""
import os
import tempfile
from pathlib import Path

import db
import lifecycle
import steps
import messaging


def _conn(tmp):
    os.environ['HMR_DB'] = str(Path(tmp) / 'test.db')
    db.BASE = tmp
    return db.connect()


def test_new_patient_next_step_is_not_the_retired_intake_job():
    with tempfile.TemporaryDirectory() as tmp:
        c = _conn(tmp)
        c.execute("INSERT INTO patients (key,name,state) VALUES ('k','Synthetic New','new')")
        p = c.execute('SELECT * FROM patients WHERE key=?', ('k',)).fetchone()
        step = lifecycle.next_step(c, p)
        assert step == 'offer a time'
        assert step != steps.BY_NAME['intake_dry'].label
        assert 'review intake' not in step
        c.close()


def test_retired_intake_job_still_refuses():
    ready, why = steps.ready('intake_dry', None, None)
    assert ready is False and 'New referrals' in why


def test_offer_from_new_is_a_working_transition_so_the_next_step_is_truthful():
    # The message-send path moves new -> pooled -> offered, the same action the "offer a time" next step opens.
    assert 'offered' in db.STATES['pooled'] and 'pooled' in db.STATES['new']


def test_other_states_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        c = _conn(tmp)
        for i, (state, expected) in enumerate({'pooled': 'offer a time', 'offered': 'wait for reply',
                                              'report_drafted': 'sign off', 'signed_off': 'send report'}.items()):
            c.execute("INSERT INTO patients (key,name,state) VALUES (?,?,?)", ('k%d' % i, 'P%d' % i, state))
            p = c.execute('SELECT * FROM patients WHERE key=?', ('k%d' % i,)).fetchone()
            assert lifecycle.next_step(c, p) == expected, state
        c.close()
