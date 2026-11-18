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


def test_refresh_rebuilds_demographics_from_the_current_patient_record(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        assert 'DOB: ' in loaded['patient']
        conn.execute("UPDATE patients SET dob=?, gp=? WHERE id=?", ('01-Feb-1950', 'Dr Synthetic Corrected', patient['id']))
        conn.commit()
        refreshed = report.refresh(conn, dict(conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()))
        assert 'DOB: 01-Feb-1950' in refreshed['patient']
        assert 'Dr Synthetic Corrected' in refreshed['doctor'] and refreshed['dear'] == 'Dear Dr Synthetic Corrected,'


def _patient_row(conn, pid):
    return dict(conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())


def test_refresh_keeps_a_pharmacist_edited_block_and_offers_a_choice(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        authored = loaded['doctor'] + '\nPractice manager: Synthetic Person'
        edited = dict(loaded, doctor=authored, expected_revision=loaded['revision'])
        report.save(conn, patient, edited)
        conn.execute("UPDATE patients SET dob=?, gp=? WHERE id=?", ('01-Feb-1950', 'Dr Synthetic Corrected', patient['id']))
        conn.commit()
        refreshed = report.refresh(conn, _patient_row(conn, patient['id']))
        assert refreshed['doctor'] == authored                      # authored edit survives
        assert 'DOB: 01-Feb-1950' in refreshed['patient']           # untouched block still follows the record
        assert [c['key'] for c in refreshed['demographic_conflicts']] == ['doctor']
        assert refreshed['dear'] == 'Dear Dr Synthetic Corrected,'
        assert all(c['report'] and c['record'] for c in refreshed['demographic_conflicts'])
        assert 'demographic_conflicts' not in report.load(conn, patient)
        # still a conflict next time (not silently resolved), and findings are intact
        again = report.refresh(conn, _patient_row(conn, patient['id']))
        assert any(c['key'] == 'doctor' for c in again['demographic_conflicts'])
        assert again['issues'] == loaded['issues']
        # an explicit choice replaces only the chosen block
        chosen = report.refresh(conn, _patient_row(conn, patient['id']), ['doctor'])
        assert 'Dr Synthetic Corrected' in chosen['doctor'] and not any(c['key'] == 'doctor' for c in chosen['demographic_conflicts'])
        with pytest.raises(ValueError):
            report.refresh(conn, _patient_row(conn, patient['id']), ['issues'])


def test_refresh_never_overwrites_a_block_of_a_spec_without_generation_record(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        legacy = {k: v for k, v in loaded.items() if k != 'demographics_generated'}
        legacy.update(patient='Typed by hand', expected_revision=loaded['revision'])
        report.save(conn, patient, legacy)
        refreshed = report.refresh(conn, _patient_row(conn, patient['id']))
        assert refreshed['patient'] == 'Typed by hand'
        assert any(c['key'] == 'patient' for c in refreshed['demographic_conflicts'])
