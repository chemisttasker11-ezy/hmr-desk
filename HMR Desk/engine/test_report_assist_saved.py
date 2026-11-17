"""Synthetic regression: AI findings must not restart or overwrite a saved manual report."""
import json
from contextlib import contextmanager

import agents
import db
import interview
import jobs
import records
import report
import settings


def test_assist_preserves_saved_manual_report(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview, 'referral_text', lambda folder: (None, []))
    folder = tmp_path / 'workspace' / 'synthetic'
    folder.mkdir(parents=True)
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
    with connection() as conn:
        pid = conn.execute("INSERT INTO patients(key,name,state,folder) VALUES (?,?,?,?)",
                           ('synthetic', 'Synthetic Patient', 'visited', 'synthetic')).lastrowid
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        data = interview.blank(conn, patient)
        data['meds'] = [['Synthetic medicine', 'one daily', 'one daily', '', '']]
        data['details']['meds'] = [{'packed': '', 'as_instructed': False,
                                   'use_status': 'taking', 'use_reason': '', 'use_details': ''}]
        data['notes'] = 'Synthetic interview data only'
        data['revision'] = records.revision(conn, pid, 'interview.json')
        interview.save(conn, patient, data)
        records.put_json(conn, pid, 'confirmed_meds.json',
                         {'meds': [['Synthetic medicine', '']], 'allergies': []})
        settings.update(conn, {'clinical_ai_privacy_ack': True})
        manual = report.start(conn, patient)
        manual.update(reason='Handwritten synthetic reason', intro='Handwritten synthetic introduction',
                      issues=[{'title': 'Manual finding', 'rec': 'Manual review', 'rationale': 'Manual rationale'}])
        report.save(conn, patient, manual)
        original = records.get(conn, pid, 'report_spec.json')
        original_revision = records.revision(conn, pid, 'report_spec.json')

    def reply(name, prompt):
        clinical = json.loads(prompt.split('Clinical JSON: ', 1)[1])
        evidence_id = clinical['medicines'][0]['id']
        return json.dumps({'findings': [{'title': 'Synthetic AI finding', 'recommendation': 'Review only',
                                        'rationale': 'Synthetic rationale', 'evidence_ids': [evidence_id]}]})

    monkeypatch.setattr(agents, 'selected', lambda step: 'synthetic-api')
    monkeypatch.setattr(agents, 'get', lambda name: {'type': 'api', 'enabled': True})
    monkeypatch.setattr(agents, 'run', reply)
    jobs.report_assist(pid)

    with connection() as conn:
        assert records.get(conn, pid, 'report_spec.json') == original
        assert records.revision(conn, pid, 'report_spec.json') == original_revision
        candidate = records.get_json(conn, pid, 'report_spec.ai.json')
        assert candidate['issues'] == [{'title': 'Synthetic AI finding', 'rec': 'Review only',
                                       'rationale': 'Synthetic rationale'}]
        for key, value in manual.items():
            if key != 'issues':
                assert candidate[key] == value
    try:
        jobs.report_assist(pid)
    except FileExistsError as exc:
        assert 'Existing AI draft' in str(exc)
    else:
        raise AssertionError('An existing AI draft must not be overwritten')
    with connection() as conn:
        assert records.get(conn, pid, 'report_spec.json') == original
        assert records.get_json(conn, pid, 'report_spec.ai.json') == candidate
