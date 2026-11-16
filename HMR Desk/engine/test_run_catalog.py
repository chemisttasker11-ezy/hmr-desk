"""Offline run catalog and patient task history checks."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import api, db, steps

with TemporaryDirectory() as tmp, patch.object(db, 'BASE', tmp), closing(db.connect(str(Path(tmp) / 'test.db'))) as conn:
    conn.execute("INSERT INTO patients(key,name,state) VALUES ('first','First Patient','new')")
    conn.execute("INSERT INTO patients(key,name,state) VALUES ('second','Second Patient','new')")
    conn.execute("INSERT INTO tasks(id,patient_id,step,state,created) VALUES ('first-task',1,'pathology','done','now')")
    conn.executemany("INSERT INTO tasks(id,patient_id,step,state,created) VALUES (?,2,'pathology','done','now')", [('other-' + str(i),) for i in range(205)])
    conn.commit()
    status, result = api.handle(conn, 'GET', '/api/run', {}, None)
    assert status == 200 and len(result['tasks']) == 200
    assert result['steps'] == [{'name': x.name, 'label': x.label, 'runs_in': x.runs_in, 'ai_off': steps.ai_off(x.name, conn)} for x in steps.STEPS if x.name not in ('intake_dry', 'intake_apply')]
    assert 'interview_assist' in {x['name'] for x in result['steps']} and 'interview_spec' not in {x['name'] for x in result['steps']}
    status, result = api.handle(conn, 'GET', '/api/run', {'patient_id':['1']}, None)
    assert status == 200 and [x['id'] for x in result['tasks']] == ['first-task']
    status, detail = api.handle(conn, 'GET', '/api/patients/1', {}, None)
    assert status == 200 and detail['tasks'] == result['tasks']
    assert api.handle(conn, 'GET', '/api/run', {'patient_id':['1','2']}, None)[0] == 400
    assert api.handle(conn, 'GET', '/api/run', {'patient_id':'abc'}, None)[0] == 400
    assert api.handle(conn, 'GET', '/api/run', {'patient_id':'999'}, None)[0] == 404
    before = conn.execute('SELECT count(*) FROM tasks').fetchone()[0]
    with patch('jobs.ensure_worker') as worker:
        status, result = api.handle(conn, 'POST', '/api/run', {}, {'steps':['intake_dry','interview_spec','bad_step'], 'patient_ids':[1]})
        assert status == 400 and 'interview_spec' in result['error'] and 'bad_step' in result['error']
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == before and not worker.called
        status, result = api.handle(conn, 'POST', '/api/run', {}, {'steps':['pathology'], 'patient_ids':[1]})
        assert status == 200 and not result['enqueued'] and result['skipped'][0]['reason']
