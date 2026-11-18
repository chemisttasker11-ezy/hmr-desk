"""Synthetic check: report saves can be conditional, so a stale save cannot overwrite a newer one."""
import pytest

import db
import interview
import jobs
import records
import report
import settings
from contextlib import contextmanager


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview, 'referral_text', lambda folder: (None, []))
    (tmp_path / 'workspace' / 'synthetic').mkdir(parents=True)
    path = str(tmp_path / 'userdata' / 'test.db')

    @contextmanager
    def connection():
        conn = db.connect(path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    monkeypatch.setattr(jobs, 'connection', connection)
    return connection


def _saved_report(conn):
    pid = conn.execute("INSERT INTO patients(key,name,state,folder) VALUES (?,?,?,?)",
                       ('synthetic', 'Synthetic Patient', 'visited', 'synthetic')).lastrowid
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    data = interview.blank(conn, patient)
    data['meds'] = [['Synthetic medicine', 'one daily', 'one daily', '', '']]
    data['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'taking', 'use_reason': '', 'use_details': ''}]
    data['revision'] = records.revision(conn, pid, 'interview.json')
    interview.save(conn, patient, data)
    records.put_json(conn, pid, 'confirmed_meds.json', {'meds': [['Synthetic medicine', '']], 'allergies': []})
    spec = report.start(conn, patient)
    spec.update(reason='First reason', intro='First intro',
                issues=[{'title': 'Finding', 'rec': 'Review', 'rationale': 'Because'}])
    report.save(conn, patient, spec)
    return patient, report.load(conn, patient)


def test_second_save_with_the_same_expected_revision_is_refused_and_nothing_is_lost(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        token = loaded['revision']
        first = {k: v for k, v in loaded.items()}
        first.update(reason='Second reason', expected_revision=token)
        report.save(conn, patient, first); conn.commit()
        stale = dict(loaded); stale.update(reason='Stale reason', expected_revision=token)
        with pytest.raises(records.Conflict):
            report.save(conn, patient, stale)
        conn.rollback()
        assert report.load(conn, patient)['reason'] == 'Second reason'


def test_saved_spec_never_stores_the_revision_fields(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded['expected_revision'] = loaded['revision']
        report.save(conn, patient, loaded); conn.commit()
        import json
        stored = json.loads(records.get(conn, patient['id'], 'report_spec.json'))
        assert 'revision' not in stored and 'expected_revision' not in stored


def test_save_without_expected_revision_still_works(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded['reason'] = 'Unconditional'
        report.save(conn, patient, loaded); conn.commit()
        assert report.load(conn, patient)['reason'] == 'Unconditional'


def test_save_and_refresh_return_the_revision_so_the_next_conditional_save_succeeds(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        first = dict(loaded, reason='Two', expected_revision=loaded['revision'])
        saved = report.save(conn, patient, first)
        assert saved['revision'] == records.revision(conn, patient['id'], 'report_spec.json')
        second = dict(saved, reason='Three', expected_revision=saved['revision'])
        saved = report.save(conn, patient, second)
        refreshed = report.refresh(conn, patient)
        assert refreshed['revision'] == records.revision(conn, patient['id'], 'report_spec.json')
        report.save(conn, patient, dict(refreshed, reason='Four', expected_revision=refreshed['revision']))
