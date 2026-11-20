"""Stale reconciliation review: re-acknowledgement stays digest-bound and is never automatic."""
import json
import pytest
import api, db, interview


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'; (root / 'TO SORT' / 'Synthetic').mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(root)); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.delenv('HMR_DB_KEY', raising=False)
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)", ('synthetic example', 'Synthetic Example', 'TO SORT/Synthetic')).lastrowid
    yield conn, pid
    conn.close()


def get(conn, pid): return api.handle(conn, 'GET', f'/api/patients/{pid}/reconciliation', {}, None)[1]
def ack(conn, pid, digest): return api.handle(conn, 'POST', f'/api/patients/{pid}/reconciliation', {}, {'source_hash': digest, 'reviewed_by': 'Synthetic Pharmacist'})


def test_review_goes_stale_when_medicines_change_and_needs_a_new_bound_acknowledgement(case):
    conn, pid = case
    first = get(conn, pid)
    assert first['reviewed'] is False and first['stale'] is False
    assert ack(conn, pid, first['source_hash'])[0] == 200 and get(conn, pid)['reviewed'] is True
    p = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    data = interview.load(conn, p); data['meds'] = [['Synthetic medicine', 'daily', '', '', '']]; data['details']['meds'] = [{'packed': '', 'as_instructed': False}]
    interview.save(conn, p, data); conn.commit()
    stale = get(conn, pid)
    assert stale['reviewed'] is False and stale['stale'] is True and stale['source_hash'] != first['source_hash']
    assert ack(conn, pid, first['source_hash'])[0] == 400  # an old digest is refused; nothing is acknowledged automatically
    assert get(conn, pid)['reviewed'] is False
    assert ack(conn, pid, stale['source_hash'])[0] == 200
    assert get(conn, pid)['reviewed'] is True and get(conn, pid)['stale'] is False
