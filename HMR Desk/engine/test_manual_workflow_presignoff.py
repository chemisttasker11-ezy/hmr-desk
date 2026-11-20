"""Pre-sign-off part of test_manual_workflow.py (pathology outcomes, manual interactions, report start and build).

The rest of that script calls signed_off and report_sent, which need an approved report pair; it stays excluded
from the runner (see test_legacy_scripts.py) and is not counted as passing."""
import datetime as dt, json, os, tempfile
from pathlib import Path
from unittest.mock import patch
import api, db, jobs, lifecycle, messaging, outbox, records, report, settings, steps

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); os.environ['HMR_DB'] = str(root / 'test.db'); db.BASE = tmp; db.DATA_DIR = tmp
    folder = root / 'patient'; folder.mkdir(); skill = root / 'skill'; (skill / 'scripts').mkdir(parents=True)
    (skill / 'scripts' / 'example-spec.json').write_text(json.dumps({k: 'Mr Firstname Surname Dr Firstname Surname' for k in report.REVIEW}), encoding='utf-8'); jobs.SKILL = skill
    conn = db.connect(); today = dt.date.today()
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
    # MIMS interaction results live in the records store now, not as files in the patient folder.
    files = records.names_like(conn, 1, 'mims interactions'); assert len(files) == 2 and {records.get(conn, 1, x).decode('utf-8').splitlines()[-1] for x in files} == {'first', 'second'}
    for bad in ('', ' ', 'x' * 20001):
        try: act('interactions_manual', text=bad); assert False
        except ValueError: pass
    # The confirmed list is saved after the interaction results, so it is newer and the results are out of date.
    records.put(conn, 1, 'confirmed_meds.json', json.dumps({'meds': [['aspirin', 'brand']], 'allergies': ['penicillin']}).encode('utf-8')); conn.commit()
    assert not steps.done('interactions', conn, patient())
    act('interactions_manual', text='Reviewed against confirmed medicines')
    for name in ('interview_assist', 'report_draft', 'report_assist'): assert steps.ready(name, conn, patient()) == (False, 'AI assist is off in Settings')
    payload = api.handle(conn, 'GET', '/api/patients/1', {}, None)[1]; assert all(next(x for x in payload['steps'] if x['name'] == name)['ai_off'] for name in ('interview_assist', 'report_draft', 'report_assist'))
    assert steps.done('interactions', conn, patient()) and steps.ready('report_start', conn, patient())[0]
    spec = report.start(conn, patient()); conn.commit(); assert spec['meds'][0][:2] == ['aspirin', 'Not yet confirmed'] and spec['meds'][0][2] == 'Brand: brand' and spec['meds'][0][3] == '' and spec['allergies'] == 'penicillin' and not spec['issues']
    # A build now needs the pharmacist's explicit follow-up decision (it is no longer blank), so the fixture chooses one.
    spec['issues'] = [{'title':'test', 'rec':'test', 'rationale':'test'}]; spec['reason'] = spec['intro'] = 'Written by the pharmacist'; spec['followup_decision'] = 'not_required'; records.put(conn, 1, 'report_spec.json', json.dumps(spec).encode('utf-8')); conn.commit(); assert steps.ready('report_build', conn, patient())[0]
    def fake_build(script, spec_path):
        Path(json.loads(Path(spec_path).read_text(encoding='utf-8'))['out']).write_text('report', encoding='utf-8')
        return 'built'
    with patch('jobs.run_script', side_effect=fake_build): jobs.report_build(1)
    assert patient()['state'] == 'report_drafted'
    conn.close()
print('manual workflow pre-sign-off checks passed')
