"""Allergies added to the interview after medicines were confirmed must never show as an older (empty) list."""
import db, api, interview, report


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'ws')); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'data'))
    (tmp_path / 'ws' / 'TO SORT' / 'Synthetic').mkdir(parents=True); (tmp_path / 'data').mkdir()
    conn = db.connect()
    with conn:
        pid = conn.execute("INSERT INTO patients(key,name,folder,state) VALUES (?,?,?,?)", ('synthetic example', 'Synthetic Example', 'TO SORT/Synthetic', 'confirmed')).lastrowid
    return conn, pid


def test_allergies_added_after_confirmation_show_current_text_and_old_list(tmp_path, monkeypatch):
    conn, pid = _setup(tmp_path, monkeypatch)
    p = lambda: conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    d = interview.load(conn, p())
    d['meds'] = [['Synthetic medicine A', 'daily', 'daily', '', '']]
    d['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'taking', 'use_reason': '', 'use_details': ''}]
    interview.save(conn, p(), d); conn.commit()
    g = api.handle(conn, 'GET', f'/api/patients/{pid}/meds', {}, None)[1]
    assert g['allergies'] == [] and 'allergies_confirmed_earlier' not in g
    body = {'meds': g['meds'], 'allergies': g['allergies'], 'interview_usage': g['interview_usage'], 'medicine_snapshot_sha256': g['medicine_snapshot_sha256']}
    assert api.handle(conn, 'POST', f'/api/patients/{pid}/meds', {}, body)[0] == 200
    report.start(conn, p()); conn.commit()
    d = interview.load(conn, p()); d['allergies'] = 'Synthetic allergy one\nSynthetic allergy two'
    interview.save(conn, p(), d); conn.commit()
    spec = report.load(conn, p())
    assert spec['allergies'] == '' and spec['interview_newer'] is True  # the report is stale and says so
    g = api.handle(conn, 'GET', f'/api/patients/{pid}/meds', {}, None)[1]
    assert g['medicine_snapshot_changed'] is True
    assert g['allergies'] == ['Synthetic allergy one', 'Synthetic allergy two']
    assert g['allergies_confirmed_earlier'] == []
