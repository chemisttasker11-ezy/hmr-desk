"""claim_list builds PPA claim rows from local data only. No network, no helper script, fake collaborators."""
import types
from unittest.mock import patch

import api
import db
import steps


class FakeHelper:
    @staticmethod
    def split_name(name):
        parts = (name or '').split()
        return (parts[0] if parts else '', ' '.join(parts[1:]))

    @staticmethod
    def iso(value):
        return f'iso:{value}' if value else ''


class FakeRecord:
    @staticmethod
    def outcomes(spec): return (['o1'], 'other-outcome')

    @staticmethod
    def reasons(spec): return ['r1']


def _db(tmp_path):
    db.BASE = str(tmp_path)
    return db.connect(str(tmp_path / 'claims.db'))


def _add(conn, name, state='sent', **extra):
    conn.execute('INSERT INTO patients(key,name,gp,state) VALUES (?,?,?,?)', (db.patient_key(name), name, 'Dora Doctor', state))
    pid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    for col, value in extra.items(): conn.execute(f'UPDATE patients SET {col}=? WHERE id=?', (value, pid))
    conn.commit()
    return pid


def test_returns_empty_when_ppa_helper_is_unavailable(tmp_path):
    conn = _db(tmp_path); _add(conn, 'Sam Example')
    with patch.object(api, 'claims_helper', None), patch.object(api, 'record', FakeRecord):
        assert api.claim_list(conn) == []
    with patch.object(api, 'claims_helper', FakeHelper), patch.object(api, 'record', None):
        assert api.claim_list(conn) == []


def test_lists_only_sent_real_unarchived_patients_in_name_order_with_mapped_fields(tmp_path):
    conn = _db(tmp_path)
    _add(conn, 'Zed Example', medicare='1234 56789 0', irn='1', dob='1950-01-02', referral_date='2026-01-03', suburb='4000 Brisbane City')
    _add(conn, 'Amy Example', postcode='4101', suburb='South Brisbane')
    _add(conn, 'Not Sent', state='new')
    _add(conn, 'Test Person', is_test=1)
    _add(conn, 'Archived Person', archived_at='2026-01-01')
    with patch.object(api, 'claims_helper', FakeHelper), patch.object(api, 'record', FakeRecord), \
         patch.object(api, 'report_data', lambda c, p: {'doctor': 'Dr X\nProvider No: 123456A', 'reason': 'x'}), \
         patch.object(api, 'consent_evidence', lambda c, p: 'paper form'), \
         patch.object(steps, 'event_date', lambda c, p, name: {'visited': '2026-02-01', 'report_sent': '2026-02-02'}[name]):
        rows = api.claim_list(conn)
    assert [r['family'] for r in rows] == ['Example', 'Example'] and [r['given'] for r in rows] == ['Amy', 'Zed']
    amy, zed = rows
    assert zed['medicare'] == '123456789' + '0' + '1'
    assert (zed['dob'], zed['referral']) == ('iso:1950-01-02', 'iso:2026-01-03')
    assert (zed['postcode'], zed['suburb']) == ('4000', 'Brisbane City')
    assert (amy['postcode'], amy['suburb']) == ('4101', 'South Brisbane')
    assert (zed['interview'], zed['reportSent']) == ('iso:2026-02-01', 'iso:2026-02-02')
    assert zed['gpProvider'] == '123456A' and (zed['gpGiven'], zed['gpFamily']) == ('Dora', 'Doctor')
    assert zed['reasons'] == ['r1'] and zed['outcomes'] == ['o1'] and zed['outcomeOther'] == 'other-outcome' and zed['reasonOther'] == ''
    assert zed['consentHeld'] is True and zed['consentEvidence'] == 'paper form'


def test_consent_is_not_held_without_evidence_and_missing_report_gives_empty_lists(tmp_path):
    conn = _db(tmp_path); _add(conn, 'Quin Example')
    with patch.object(api, 'claims_helper', FakeHelper), patch.object(api, 'record', FakeRecord), \
         patch.object(api, 'report_data', lambda c, p: None), patch.object(api, 'consent_evidence', lambda c, p: ''):
        row, = api.claim_list(conn)
    assert row['consentHeld'] is False and row['reasons'] == [] and row['outcomes'] == [] and row['gpProvider'] == ''
