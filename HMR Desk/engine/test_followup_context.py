"""Synthetic, read-only saved-interview continuity, not current-medication inference."""
import contextlib
import pytest
import db, records, interview, followup, api

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    folder = tmp_path / 'workspace' / 'Visited' / 'Synthetic'; folder.mkdir(parents=True)
    with contextlib.closing(db.connect(str(tmp_path / 'userdata' / 'hmr.db'))) as conn:
        pid = conn.execute("INSERT INTO patients(key,name,state,folder) VALUES(?,?,?,?)", ('synthetic', 'Synthetic Example', 'visited', 'Visited/Synthetic')).lastrowid
        conn.commit(); patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        yield conn, patient

def saved(conn, patient):
    data = interview.blank(conn, patient)
    data['meds'] = [['<Synthetic> 20mg', 'One daily', 'Actually half daily', '', '']]
    data['other_meds'] = [['Brand Example', 'PRN', '', '']]
    ref = {'source': 'amt', 'code': '1001', 'display': 'Synthetic generic 20 mg tablet', 'release': '20260101'}
    data['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'not_using', 'use_reason': 'side_effects', 'use_details': 'Synthetic note', 'reference': ref}]
    data['details']['other_meds'] = [{'checked': False, 'priority': 0}]
    interview.validate(data)
    records.put_json(conn, patient['id'], 'interview.json', data); conn.commit()
    return ref

def test_missing_context_does_not_read_sources_or_create_record(setup, monkeypatch):
    conn, patient = setup
    monkeypatch.setattr(interview, 'blank', lambda *a: pytest.fail('must not generate a blank interview'))
    assert followup.medicine_context(conn, patient) == {'available': False, 'revision': 'missing', 'medicines': []}
    assert records.names(conn, patient['id']) == []

def test_context_keeps_links_status_and_directions_without_changing_any_record(setup, monkeypatch):
    conn, patient = setup
    ref = saved(conn, patient)
    before = records.get(conn, patient['id'], 'interview.json')
    monkeypatch.setattr(interview, 'load', lambda *a: pytest.fail('must not read source sidecars'))
    status, result = api.handle(conn, 'GET', f"/api/patients/{patient['id']}/medicine-context", {}, None)
    assert status == 200 and result['available'] and result['revision'] == records.digest(before)
    first, other = result['medicines']
    assert first['reference'] == ref and first['use'].startswith('Not using') and first['use'].endswith('Side effects: Synthetic note')
    assert first['listed_directions'] == 'One daily' and first['interview_directions'] == 'Actually half daily'
    assert other['origin'] == 'Found during interview' and other['use'] == 'Not recorded' and other['reference'] is None
    assert records.get(conn, patient['id'], 'interview.json') == before
    assert not records.exists(conn, patient['id'], 'followup1.json')

def test_corrupt_saved_context_is_not_silently_shown_as_no_medicines(setup):
    conn, patient = setup
    records.put_json(conn, patient['id'], 'interview.json', {'meds': 'bad'}); conn.commit()
    status, _ = api.handle(conn, 'GET', f"/api/patients/{patient['id']}/medicine-context", {}, None)
    assert status == 400
    status, _ = api.handle(conn, 'GET', '/api/patients/99999/medicine-context', {}, None)
    assert status == 404
