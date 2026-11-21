import datetime as dt, json, os, tempfile
from pathlib import Path
from unittest.mock import patch
import api, db, jobs, lifecycle, messaging, outbox, records, report, settings, steps
import legacy_signoff_support

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); os.environ['HMR_DB'] = str(root / 'test.db'); db.BASE = tmp; db.DATA_DIR = tmp
    folder = root / 'patient'; folder.mkdir(); skill = root / 'skill'; (skill / 'scripts').mkdir(parents=True)
    (skill / 'scripts' / 'example-spec.json').write_text(json.dumps({k: 'Mr Firstname Surname Dr Firstname Surname' for k in report.REVIEW}), encoding='utf-8'); jobs.SKILL = skill
    conn = db.connect(); today = dt.date.today()
    settings.update(conn, {'pharmacist_name': 'Synthetic Pharmacist', 'pharmacist_phone': '0400000000'}); conn.commit()  # drafts need the pharmacist's own details
    conn.execute("INSERT INTO patients(key,name,state,folder,gp,phone,address,visit_date,visit_time,referral_date) VALUES ('manual','Manual Patient','confirmed','patient','Doctor','0412345678','Home',?,'10:30','2020-01-01')", (str(today),)); conn.commit()
    conn.execute("UPDATE patients SET postcode='4216'"); conn.commit()
    def patient(): return conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    def act(action, **kw): return api.action(conn, patient(), {'action': action, **kw})
    settings.update(conn, {'ai_interview_assist': False, 'ai_report_assist': False, 'ai_reply_reading': 'off', 'flow_includes_ai_assist': True})
    conn.execute("INSERT INTO tasks(id,patient_id,step,state,created) VALUES ('waiting-path',1,'pathology','waiting',?)", (db.now(),)); conn.commit()
    act('pathology_outcome', outcome='none', note=''); assert conn.execute("SELECT state FROM tasks WHERE id='waiting-path'").fetchone()[0] == 'done'; assert steps.done('pathology', conn, patient())
    act('pathology_outcome', outcome='access_code', note='test'); assert not steps.done('pathology', conn, patient())
    prep = next(g for g in lifecycle.attention(conn)['groups'] if g['key'] == 'prep')['items']; assert next(x for x in prep if x['action'] == 'pathology')['note'] == 'access code needed'
    conn.execute("UPDATE patients SET state='visited' WHERE id=1"); conn.commit(); act('pathology_outcome', outcome='saved_by_hand', note=''); assert patient()['has_pathology'] == 1
    conn.execute("INSERT INTO tasks(id,patient_id,step,state,created) VALUES ('waiting-mims',1,'interactions','waiting',?)", (db.now(),)); conn.commit()
    for text in ('first', 'second'): act('interactions_manual', text=text)
    assert conn.execute("SELECT state FROM tasks WHERE id='waiting-mims'").fetchone()[0] == 'done'
    files = records.names_like(conn, 1, 'MIMS interactions'); assert len(files) == 2 and {records.get(conn, 1, x).decode('utf-8').splitlines()[-1] for x in files} == {'first', 'second'}
    for bad in ('', ' ', 'x' * 20001):
        try: act('interactions_manual', text=bad); assert False
        except ValueError: pass
    records.put(conn, 1, 'confirmed_meds.json', json.dumps({'meds': [['aspirin', 'brand']], 'allergies': ['penicillin']}).encode('utf-8')); conn.commit()
    assert not steps.done('interactions', conn, patient())
    act('interactions_manual', text='Reviewed against confirmed medicines')
    for name in ('interview_assist', 'report_draft', 'report_assist'): assert steps.ready(name, conn, patient()) == (False, 'AI assist is off in Settings')
    payload = api.handle(conn, 'GET', '/api/patients/1', {}, None)[1]; assert all(next(x for x in payload['steps'] if x['name'] == name)['ai_off'] for name in ('interview_assist', 'report_draft', 'report_assist'))
    assert steps.done('interactions', conn, patient()) and steps.ready('report_start', conn, patient())[0]
    spec = report.start(conn, patient()); conn.commit(); assert spec['meds'][0][:2] == ['aspirin', 'Not yet confirmed'] and spec['meds'][0][2] == 'Brand: brand' and spec['meds'][0][3] == '' and spec['allergies'] == 'penicillin' and not spec['issues']
    spec['issues'] = [{'title':'test', 'rec':'test', 'rationale':'test'}]; spec['reason'] = spec['intro'] = 'Written by the pharmacist'; records.put(conn, 1, 'report_spec.json', json.dumps(spec).encode('utf-8')); conn.commit(); (folder / 'report_spec.json').write_text(json.dumps(spec), encoding='utf-8'); assert steps.ready('report_build', conn, patient())[0]
    # The retired external build script is gone; the standalone renderer is covered by its own tests. Here the build
    # output is a synthetic Word and PDF pair with real hash-bound evidence, so the sign-off gate runs unchanged.
    act('report_drafted'); assert patient()['state'] == 'report_drafted'
    db.log(conn, 1, 'visited', {'date': str(today)}); conn.commit()
    request = legacy_signoff_support.approve(conn, 1)
    with legacy_signoff_support.reviewed_interview():
        act('signed_off', **{k: v for k, v in request.items() if k != 'action'}); act('report_sent', date=str(today)); records.put(conn, 1, 'interview.json', json.dumps({'consent': {'signed': True}}).encode('utf-8')); conn.commit(); assert steps.ready('claim', conn, patient())[0]
        act('claimed', date=str(today)); assert patient()['state'] == 'claimed'
    outbox.config = lambda: {'test_number': '0412345678'}
    for kind in ('offer', 'change', 'change_request', 'follow_up'):
        draft = messaging.draft(conn, patient(), {'kind': kind, 'date': str(today + dt.timedelta(days=1)), 'time': '11:30'}); assert draft['warning'] == 'Referral expired on 31/03/2020'
        try: messaging.approve(conn, conn.execute('SELECT * FROM messages WHERE id=?', (draft['id'],)).fetchone(), {}); assert False
        except ValueError as exc: assert str(exc) == draft['warning']
    with patch('outbox.queue') as queue:
        messaging.approve(conn, conn.execute('SELECT * FROM messages WHERE id=?', (draft['id'],)).fetchone(), {'confirm_expired': True}); assert queue.called
    conn.execute("UPDATE patients SET state='offered' WHERE id=1"); conn.execute("INSERT OR REPLACE INTO meta VALUES ('autopilot_since','2020-01-01T00:00:00+10:00')"); conn.execute("DELETE FROM messages")
    conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('offer-old',1,'out','x','offer','Sent',?)", ((dt.datetime.now() - dt.timedelta(days=3)).isoformat(),)); conn.commit()
    messaging.autopilot(conn); messaging.autopilot(conn); assert conn.execute("SELECT count(*) FROM events WHERE type='autopilot_skipped_expired'").fetchone()[0] == 1; assert not conn.execute("SELECT 1 FROM messages WHERE kind='follow_up'").fetchone()
    settings.update(conn, {'ai_report_assist': True}); conn.execute("INSERT INTO tasks(id,patient_id,step,state,created) VALUES ('ai-failed',1,'report_assist','queued',?)", (db.now(),)); conn.commit()
    class StopAfterOne:
        calls = 0
        def is_set(self):
            self.calls += 1
            return self.calls > 1
    def fail(_): raise RuntimeError('fake failure')
    with patch.object(jobs, '_stop_worker', StopAfterOne()), patch.dict(jobs.JOBS, {'report_assist': fail}): jobs._work()
    assert conn.execute("SELECT output FROM tasks WHERE id='ai-failed'").fetchone()[0].endswith('AI step failed. Continue manually.')
    stuck = next(g for g in lifecycle.attention(conn)['groups'] if g['key'] == 'stuck')['items']; assert next(x for x in stuck if x.get('task_id') == 'ai-failed')['manual'] is True
    conn.close()
print('manual workflow checks passed')
