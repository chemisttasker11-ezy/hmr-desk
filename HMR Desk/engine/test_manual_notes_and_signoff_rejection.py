"""Stored manual interaction notes and explicit-review rejection, as real pytest tests.

Replaces the unexecuted post-sign-off assertions of the legacy scripts only where they can be checked without an
approved report pair. The legacy scripts are kept unchanged. No gate is relaxed here."""
import datetime as dt

import pytest

import api, db, records


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'test.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path)); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    (tmp_path / 'patient').mkdir()
    conn = db.connect()
    conn.execute("INSERT INTO patients(key,name,state,folder,visit_date,visit_time) VALUES ('synthetic','Synthetic Patient','visited','patient',?,'10:30')", (dt.date.today().isoformat(),))
    conn.commit()
    yield conn, tmp_path / 'test.db'
    conn.close()


def act(conn, action, **kw):
    patient = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    return api.action(conn, patient, {'action': action, **kw})


def test_two_same_day_manual_notes_are_distinct_and_survive_reopen(env):
    conn, dbfile = env
    act(conn, 'interactions_manual', text='first note')
    act(conn, 'interactions_manual', text='second note')
    conn.commit()
    other = db.connect()  # reopen through the app's own connector: what was committed, not caller-local state
    try:
        names = [r[0] for r in other.execute("SELECT name FROM records WHERE patient_id=1 ORDER BY name")]
        bodies = {n: bytes(other.execute('SELECT body FROM records WHERE patient_id=1 AND name=?', (n,)).fetchone()[0]).decode() for n in names}
    finally:
        other.close()
    mims = {n: b for n, b in bodies.items() if n.lower().startswith('mims interactions')}
    assert len(mims) == 2
    assert sorted(b.splitlines()[-1] for b in mims.values()) == ['first note', 'second note']
    assert all(b.startswith('Checked by hand by ') for b in mims.values())
    assert len(set(records.digest(b.encode()) for b in mims.values())) == 2  # neither overwrote the other


def test_third_note_does_not_overwrite_earlier_ones(env):
    conn, _ = env
    for text in ('a', 'b', 'c'):
        act(conn, 'interactions_manual', text=text)
    names = records.names_like(conn, 1, 'mims interactions')
    assert len(names) == 3
    assert sorted(records.get(conn, 1, n).decode().splitlines()[-1] for n in names) == ['a', 'b', 'c']


@pytest.mark.parametrize('bad', ['', '   ', 'x' * 20001, None, 5])
def test_invalid_manual_note_stores_nothing(env, bad):
    conn, _ = env
    with pytest.raises(ValueError):
        act(conn, 'interactions_manual', text=bad)
    assert records.names_like(conn, 1, 'mims interactions') == []


@pytest.mark.parametrize('extra', [
    {},
    {'clinical_reviewed': False, 'reviewer': 'Dr Synthetic', 'report_file': 'r.docx', 'report_sha256': 'a' * 64},
    {'clinical_reviewed': True, 'reviewer': 'Dr Synthetic', 'report_file': 'r.docx'},
    {'clinical_reviewed': 'yes', 'reviewer': 'Dr Synthetic', 'report_file': 'r.docx', 'report_sha256': 'a' * 64},
    {'clinical_reviewed': True, 'reviewer': 'Dr Synthetic', 'report_file': 'r.docx', 'report_sha256': 'a' * 64, 'extra': 1},
])
def test_signoff_without_explicit_review_is_rejected_and_state_unchanged(env, extra):
    conn, _ = env
    conn.execute("UPDATE patients SET state='report_drafted' WHERE id=1"); conn.commit()
    with pytest.raises(ValueError):
        act(conn, 'signed_off', **extra)
    assert conn.execute('SELECT state FROM patients WHERE id=1').fetchone()[0] == 'report_drafted'


def test_signoff_with_review_fields_but_no_built_approved_report_is_rejected(env):
    conn, _ = env
    conn.execute("UPDATE patients SET state='report_drafted' WHERE id=1"); conn.commit()
    with pytest.raises(Exception):
        act(conn, 'signed_off', clinical_reviewed=True, reviewer='Dr Synthetic', report_file='missing.docx', report_sha256='a' * 64)
    assert conn.execute('SELECT state FROM patients WHERE id=1').fetchone()[0] == 'report_drafted'
