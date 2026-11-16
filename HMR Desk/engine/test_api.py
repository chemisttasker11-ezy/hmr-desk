"""Offline API checks using synthetic patients and a temporary database."""
import csv
import datetime as dt
import functools
import http.server
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

import api
import db
import service
import jobs
import steps
from openpyxl import load_workbook

with tempfile.TemporaryDirectory() as tmp:
    os.environ['HMR_DB'] = os.path.join(tmp, 'test.db')
    db.BASE = tmp
    db.DATA_DIR = tmp
    conn = db.connect()
    conn.execute("INSERT INTO tasks(id,step,state,created) VALUES ('dead','intake_dry','running','now')")
    conn.commit()
    jobs.ensure_worker(recover=True)
    assert jobs.get('dead')['state'] == 'failed' and jobs.get('dead')['output'] == 'interrupted'
    os.makedirs(os.path.join(tmp, 'Scheduled', 'Alex Example', 'Pathology'))
    conn.execute("INSERT INTO patients (key,name,state,folder,dob,sex) VALUES ('alex example','Alex Example','offered',?,'1943-06-25','F')", (os.path.join('Scheduled','Alex Example'),))
    conn.commit()
    def call(method, path, body=None, query=None):
        return api.handle(conn, method, path, query or {}, body)
    def act(name, **fields):
        return call('POST', '/api/patients/1/action', {'action': name, **fields})
    today = dt.date.today()
    for age, expected in [(59, None), (60, 'referral expires'), (90, 'referral expires'), (91, 'referral expired')]:
        referral = (today - dt.timedelta(days=age)).isoformat()
        conn.execute('UPDATE patients SET referral_date=? WHERE id=1', (referral,)); conn.commit()
        alerts = [a for a in call('GET', '/api/today')[1]['alerts'] if a['type'].startswith('referral')]
        assert (alerts[0]['type'] if alerts else None) == expected
        if alerts: assert alerts[0]['days_left'] == 90 - age
        expiry = (today + dt.timedelta(days=90-age)).isoformat()
        assert call('GET', '/api/patients/1')[1]['referral_expiry'] == expiry
        assert call('GET', '/api/patients')[1]['patients'][0]['referral_expiry'] == expiry
    conn.execute("INSERT INTO meta(key,value) VALUES ('referral_valid_days','120')")
    assert api.referral_expiry(conn, '2026-01-01') == dt.date(2026, 5, 1)
    conn.execute("DELETE FROM meta WHERE key='referral_valid_days'")
    conn.execute('UPDATE patients SET referral_date=NULL WHERE id=1'); conn.commit()
    assert len(call('GET','/api/patients',query={'q':'Example'})[1]['patients']) == 1
    assert not call('GET','/api/patients',query={'state':'new'})[1]['patients']
    assert call('GET','/api/patients/1')[1]['files'] == {'folder': [], 'pathology': []}
    assert act('claimed', date='2026-01-01')[0] == 400
    assert act('move', date='2026-12-01', time='09:00', end='10:00') == (400, {'error': 'move needs a booked visit'})
    assert act('book_phone', date='2026-12-01', time='08:00', end='09:00')[0] == 400
    assert act('book_phone', date='bad', time='09:00', end='10:00')[0] == 400
    assert act('book_phone', date='2026-12-01', time='09:00', end='10:00')[0] == 200
    assert act('move', date='2026-12-02', time='10:00', end='11:00')[0] == 200
    queue = call('GET','/api/pathology/queue')[1]['patients']
    assert len(queue) == 1 and queue[0]['last'] == 'Example' and queue[0]['dob'] == '25-Jun-1943' and queue[0]['medicare'] is None
    assert call('POST','/api/pathology/result', {'id':1,'status':'saved','saved':['x.pdf'],'irn':'1','medicare10':''})[0] == 200
    assert not call('GET','/api/pathology/queue')[1]['patients']
    assert act('update', fields={'phone':'0400000000'})[0] == 200
    assert act('update', fields={'state':'claimed'})[0] == 400
    assert act('note', text='hello')[0] == 200
    assert call('GET','/api/patients/1')[1]['note'] == 'hello'
    assert act('visited', date='2026-01-01')[0] == 200
    for action in ('report_drafted','signed_off'):
        assert act(action)[0] == 200
    for action in ('report_sent','claimed'):
        assert act(action, date='2026-01-02')[0] == 200
    visits = call('GET','/api/patients/1')[1]['visits']
    assert len(visits) == 1 and (visits[0]['visit_date'],visits[0]['report_sent'],visits[0]['claimed']) == ('2026-01-01','2026-01-02','2026-01-02')
    assert act('followup_done', date='2026-02-01', kind='bad')[0] == 400
    for day, kind in [('2026-01-30', []), ('2026-01-31', ['follow-up 1 due']), ('2026-09-28', ['follow-up 1 due']), ('2026-09-29', [])]:
        assert api.patient_followups(conn,1,dt.date.fromisoformat(day))['alerts'] == kind
    conn.execute("UPDATE visits SET visit_date=? WHERE patient_id=1 AND kind='hmr'", ((today-dt.timedelta(days=30)).isoformat(),))
    assert any(a['type']=='follow-up 1 due' and a['window_end'] for a in call('GET','/api/today')[1]['alerts'] if a['id']==1)
    assert call('GET','/api/patients')[1]['patients'][0]['next_step']=='follow-up due'
    conn.execute("UPDATE visits SET visit_date='2026-01-01' WHERE patient_id=1 AND kind='hmr'")
    assert act('followup_done',date='2026-02-01',kind='followup1')[0] == 200
    assert api.patient_followups(conn,1,dt.date(2026,3,2))['alerts'] == ['follow-up 1 to claim']
    assert api.patient_followups(conn,1,dt.date(2026,3,3))['alerts'] == ['follow-up 1 to claim', 'follow-up 2 due']
    assert act('followup_done',date='2026-03-03',kind='followup2')[0] == 200
    assert api.patient_followups(conn,1,dt.date(2026,3,3))['alerts'] == ['follow-up 1 to claim', 'follow-up 2 to claim']
    assert api.patient_followups(conn,1,dt.date(2028,1,1))['alerts'] == ['follow-up 1 to claim', 'follow-up 2 to claim', 'new HMR possible']
    f = api.followups('2024-02-29', 30, 270, 24, dt.date(2024,4,1))
    assert f['first_due'] == '2024-03-30' and f['window_end'] == '2024-11-25' and f['new_hmr'] == '2026-02-28' and f['due']
    assert call('GET','/api/patients/1')[1]['followups']['visit_date'] == '2026-01-01'
    conn.execute("INSERT INTO patients(key,name,state) VALUES ('b','Bea Example','new')")
    os.makedirs(os.path.join(tmp, 'on Excel'), exist_ok=True)
    with open(os.path.join(tmp, 'on Excel', 'Cal Example.pdf'), 'w') as f: f.write('referral')
    conn.execute("INSERT INTO patients(key,name,state,folder) VALUES ('c','Cal Example','new',?)", (os.path.join('on Excel', 'Cal Example.pdf'),))
    conn.commit()
    assert call('POST','/api/patients/2/action',{'action':'hold','note':'wait'})[0] == 200
    assert call('POST','/api/patients/3/action',{'action':'decline_phone','reason':'no'})[0] == 200
    with open(os.path.join(tmp,'Declined-Exp','Declines register.csv'), encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]['Patient'] == 'Cal Example' and rows[0]['How'] == 'Phone'
    assert call('GET','/api/status')[0] == 200 and call('GET','/api/today')[0] == 200
    assert call('GET','/api/jobs/1')[0] == 404
    assert call('POST','/api/jobs', {'job':'unknown'})[0] == 400
    sorting = os.path.join(tmp, 'TO SORT'); os.makedirs(sorting)
    assert call('POST', '/api/intake/correction', {'file':'a.pdf','fields':{'name':'New Example'}})[0] == 200
    assert call('POST', '/api/intake/correction', {'file':'a.pdf','fields':{'phone':'123'}})[0] == 200
    assert call('POST', '/api/intake/correction', {'file':'../a.pdf','fields':{'name':'x'}})[0] == 400
    assert call('POST', '/api/intake/correction', {'file':'a.pdf','fields':{'state':'claimed'}})[0] == 400
    with open(os.path.join(sorting, 'intake_corrections.json'), encoding='utf-8') as f:
        assert json.load(f) == {'a.pdf': {'name':'New Example','phone':'123'}}
    stub = os.path.join(tmp, 'intake_stub.py')
    with open(stub, 'w', encoding='utf-8') as f:
        f.write('import json, pathlib, sys\np=pathlib.Path(sys.argv[1])\nrows=[{"kind":"referral","file":"a.pdf","planned":str(p / "New Example_ AB.pdf"),"applied":"moved","fields":{"name":"New Example","phone":"123","address":"1 Road 4216","gp":"A Doctor"},"flags":[]},{"kind":"referral","file":"b.pdf","applied":"left in place","fields":{"name":"Alex Example","phone":"changed"},"flags":[]}]\n(p / "intake_report_01-01-2026.json").write_text(json.dumps(rows), encoding="utf-8")\nprint("stub complete")\n')
    jobs.INTAKE_SCRIPT = stub
    def run_job(name, **kw):
        status, result = call('POST', '/api/jobs', {'job':name, **kw})
        assert status == 200, result
        for _ in range(500):
            state = call('GET', '/api/jobs/' + result['id'])[1]
            if state['state'] not in ('queued', 'running'): return state
            time.sleep(.01)
        raise AssertionError('job timed out')
    assert call('POST', '/api/jobs', {'job':'intake_dry'})[0] == 400
    before = dict(conn.execute('SELECT * FROM patients WHERE id=1').fetchone())
    assert call('POST', '/api/jobs', {'job':'intake_apply'})[0] == 400
    assert dict(conn.execute('SELECT * FROM patients WHERE id=1').fetchone()) == before
    conn.execute("INSERT INTO patients (key, name, state) VALUES ('new example', 'New Example', 'new')"); conn.commit()
    assert run_job('register_xlsx')['state'] == 'done'
    book = load_workbook(os.path.join(tmp, 'Booking_Register.xlsx'))
    assert book.sheetnames == list(jobs.GROUPS)
    assert [c.value for c in book['Current'][1]] == jobs.HEADERS
    assert any(row[0] == 'New Example' for row in book['Current'].iter_rows(min_row=2, values_only=True))
    book.close()
    specs = os.path.join(tmp, 'Scheduled', '_interview specs'); os.makedirs(specs)
    conn.execute("UPDATE patients SET state='confirmed' WHERE id=1"); conn.commit()
    assert run_job('interview_pack', patient_id=1)['state'] == 'done'
    assert tuple(conn.execute('SELECT state,has_sheet FROM patients WHERE id=1').fetchone()) == ('sheet_ready', 1)
    assert call('GET', '/api/patients/1/interview')[1]['saved'] is True
    interview_record = call('GET', '/api/patients/1/interview')[1]
    interview_record['notes'] = 'Synthetic notes'
    assert call('POST', '/api/patients/1/interview', interview_record)[1]['notes'] == 'Synthetic notes'
    assert call('POST', '/api/patients/1/interview', {'notes':'invalid'})[0] == 400
    assert call('POST', '/api/jobs', {'job':'interview_pack', 'patient_id':1, 'format':'bad'})[0] == 400
    # Step 4 uses only synthetic folders and stub executables.
    folder = os.path.join(tmp, 'Scheduled', 'Alex Example')
    specpath = os.path.join(folder, 'report_spec.json')
    target = os.path.join(folder, 'HMR Alex.docx')
    conn.execute("UPDATE patients SET state='visited',medicare='1234567890',irn='1',gp='Dr Amy Doctor',postcode='4000',referral_date='2026-01-01' WHERE id=1"); conn.commit()
    assert api.next_step(conn.execute('SELECT * FROM patients WHERE id=1').fetchone()) == 'confirm medicines'
    spec = {'out': target, 'reason':'polypharmacy', 'doctor':'Provider No: 123456AB', 'meds':[['Aspirin 100 mg (Cartia)', '', '', 'Reduce dose']], 'otc':[], 'allergies':'codeine: rash', 'issues':[]}
    with open(specpath,'w',encoding='utf-8') as f: json.dump(spec,f)
    assert api.next_step(conn.execute('SELECT * FROM patients WHERE id=1').fetchone()) == 'add findings'
    lists = call('GET','/api/mims/lists')[1]['lists']
    assert len(lists) == 1 and lists[0]['meds'] == [['aspirin','cartia']] and lists[0]['allergies'] == ['codeine'] and lists[0]['id'] == 1
    interactions = os.path.join(folder, 'MIMS interactions 2.txt')
    with open(interactions, 'w', encoding='utf-8') as f: f.write('done')
    assert not call('GET','/api/mims/lists')[1]['lists']
    os.unlink(interactions)
    os.unlink(specpath)
    assert call('GET','/api/patients/1/meds')[1]['proposed'] is True
    with open(os.path.join(specs,'alex_example.json'),'w',encoding='utf-8') as f: json.dump({'meds':[['Aspirin 100 mg (Cartia)']], 'allergies':'codeine: rash'},f)
    assert call('GET','/api/patients/1/meds')[1] == {'meds':[['aspirin','cartia']], 'allergies':['codeine'], 'proposed':True, 'interview_usage':[]}
    patient = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert steps.ready('interactions',conn,patient)[1] == 'confirm the medicine list first'
    assert call('POST','/api/patients/1/meds',{'meds':[['aspirin']], 'allergies':[]})[0] == 400
    assert call('POST','/api/patients/1/meds',{'meds':[['x','']]*61, 'allergies':[]})[0] == 400
    assert call('POST','/api/patients/1/meds',{'meds':[['aspirin','cartia']], 'allergies':['codeine']})[0] == 200
    assert call('GET','/api/patients/1/meds')[1]['meds'] == [['aspirin','cartia']]
    assert api.next_step(patient) == 'check interactions'
    assert call('GET','/api/mims/lists')[1]['lists'][0]['meds'] == [['aspirin','cartia']]
    assert steps.ready('interactions',conn,patient)[0]
    with open(os.path.join(folder,'case.txt'),'w',encoding='utf-8') as f: f.write('synthetic')
    assert steps.ready('report_draft',conn,patient)[1] == 'run the eMIMS interaction check first'
    with open(interactions,'w',encoding='utf-8') as f: f.write('done')
    assert api.next_step(patient) == 'start report' and steps.ready('report_draft',conn,patient)[0]
    assert call('POST','/api/patients/1/meds',{'meds':[], 'allergies':[]})[0] == 200
    assert conn.execute("SELECT count(*) FROM events WHERE type='meds_confirmed'").fetchone()[0] == 2
    spec = {**{k: '' for k in jobs.REPORT_KEYS}, **spec, 'ceased': [], 'path': [], 'issues': [{'title':'Example', 'rec':'Review', 'rationale':'Synthetic'}]}
    with open(specpath,'w',encoding='utf-8') as f: json.dump(spec,f)
    builder = os.path.join(tmp,'builder.py')
    with open(builder,'w',encoding='utf-8') as f: f.write('import json,pathlib,sys\ns=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))\npathlib.Path(s["out"]).write_text("built",encoding="utf-8")\n')
    jobs.BUILD_SCRIPT = builder
    assert run_job('report_build',patient_id=1)['state'] == 'done'
    assert conn.execute('SELECT state FROM patients WHERE id=1').fetchone()[0] == 'report_drafted'
    assert 'already exists' in run_job('report_build',patient_id=1)['output']
    spec['issues'] = []
    with open(specpath,'w',encoding='utf-8') as f: json.dump(spec,f)
    conn.execute("UPDATE patients SET state='sent' WHERE id=1"); db.log(conn,1,'report_sent',{'date':'2026-01-02'}); conn.commit()
    claim = call('GET','/api/claims')[1]['claims'][0]
    assert claim['medicare'] == '12345678901' and claim['gpProvider'] == '123456AB' and claim['reasons'] == ['polypharmacy'] and claim['outcomes'] == ['decrease'] and claim['interview'] == '2026-01-01'
    os.unlink(specpath)
    empty_claim = call('GET','/api/claims')[1]['claims'][0]
    assert empty_claim['gpProvider'] == '' and empty_claim['reasons'] == [] and empty_claim['outcomes'] == []
    with open(specpath,'w',encoding='utf-8') as f: json.dump(spec,f)
    conn.execute("UPDATE patients SET state='confirmed',has_pathology=1,has_sheet=0 WHERE id=1"); conn.commit()
    assert api.next_step(conn.execute('SELECT * FROM patients WHERE id=1').fetchone()) == 'visit'
    os.unlink(os.path.join(specs,'alex_example.json'))
    assert api.next_step(conn.execute('SELECT * FROM patients WHERE id=1').fetchone()) == 'visit'
    import sys, agents
    stub = os.path.join(tmp, 'agent_stub.py')
    with open(stub, 'w', encoding='utf-8') as f:
        f.write('import os,sys\np=sys.stdin.read()\nprint("OK" if p.startswith("Reply with") else os.environ.get("REPLY", "bad"))\n')
    agent = {'name':'stub', 'type':'cli', 'enabled':True, 'command':[sys.executable,stub], 'env':{}, 'stdin':True}
    assert call('GET','/api/agents')[1]['default'] == 'Claude B'
    assert call('POST','/api/agents',agent)[0] == 200
    assert call('POST','/api/agents/select',{'default':'stub','per_step':{'report_draft':'stub'}})[0] == 200
    assert call('POST','/api/agents/test',{'name':'stub'}) == (200, {'reply':'OK\n'})
    assert call('POST','/api/agents',{**agent,'command':'bad'})[0] == 400
    assert call('POST','/api/agents',{'name':'bad','type':'api','enabled':True,'url':'http://example.com','model':'x','style':'openai'})[0] == 400
    class AgentHTTP(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert payload['messages'][0]['content'] == 'hello'
            result = {'choices':[{'message':{'content':'world'}}]} if payload['model'] == 'open' else {'content':[{'text':'world'}]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        def log_message(self, *args): pass
    server_agent = http.server.ThreadingHTTPServer(('127.0.0.1',0), AgentHTTP)
    thread_agent = threading.Thread(target=server_agent.serve_forever); thread_agent.start()
    try:
        for style, model in [('openai','open'), ('anthropic','anthropic')]:
            a = {'name':'http','type':'api','enabled':True,'url':'http://127.0.0.1:%s/' % server_agent.server_port,'model':model,'style':style,'key':'synthetic-secret'}
            assert call('POST','/api/agents',a)[0] == 200
            assert agents.run('http','hello') == 'world'
            assert 'synthetic-secret' not in json.dumps(call('GET','/api/agents')[1])
            assert 'synthetic-secret' not in open(os.path.join(tmp,'agents.json'),encoding='utf-8').read()
            assert agents.crypt(agents.crypt(b'synthetic-secret'),True) == b'synthetic-secret'
        assert call('POST','/api/agents/delete',{'name':'http'})[0] == 200
    finally:
        server_agent.shutdown(); thread_agent.join(); server_agent.server_close()
    with open(os.path.join(folder,'referral.txt'),'w',encoding='utf-8') as f: f.write('Synthetic referral text')
    with open(os.path.join(folder,'case.txt'),'w',encoding='utf-8') as f: f.write('Synthetic case text')
    for name, keys, out in [('report_draft',jobs.REPORT_KEYS,specpath)]:
        if os.path.exists(out): os.unlink(out)
        agent['env']['REPLY'] = json.dumps({key:'' for key in keys})
        assert call('POST','/api/agents',agent)[0] == 200
        assert run_job(name,patient_id=1)['state'] == 'done'
        assert set(json.load(open(out,encoding='utf-8'))) == keys
        assert 'already exists' in run_job(name,patient_id=1)['output']
        os.unlink(out)
        for bad in ('not JSON','{}'):
            agent['env']['REPLY'] = bad
            assert call('POST','/api/agents',agent)[0] == 200
            assert run_job(name,patient_id=1)['state'] == 'failed'
    assert len(os.listdir(os.path.join(tmp,'agent-replies'))) == 2
    assert conn.execute("SELECT count(*) FROM events WHERE type IN ('interview_spec','report_draft') AND detail LIKE '%stub%'").fetchone()[0] == 1
    from unittest.mock import patch
    from types import SimpleNamespace
    with patch('agents.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='OK')) as mocked:
        agents.skill_run(agents.defaults()['agents'][0], 'test prompt', tmp)
        args, kwargs = mocked.call_args
        assert os.path.basename(args[0][0]).lower() in ('claude','claude.cmd','claude.exe') and args[0][1:4] == ['-p','--permission-mode','acceptEdits'] and 'test prompt' not in args[0] and kwargs['input'] == 'test prompt'
        assert kwargs['cwd'] == tmp and kwargs['timeout'] == 1800
        agents.skill_run(agents.defaults()['agents'][1], 'test prompt', tmp)
        args, kwargs = mocked.call_args
        assert os.path.basename(args[0][0]).lower() in ('codex','codex.cmd','codex.exe') and args[0][1:] == ['exec','--skip-git-repo-check','-s','workspace-write','-C',tmp,'-m','gpt-6.1-terra','-c','model_reasoning_effort="high"','-']
        assert kwargs['input'] == 'test prompt' and kwargs['cwd'] == tmp
    with patch('agents.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='\n'.join(map(str, range(250))))):
        try: agents.skill_run(agents.defaults()['agents'][0], 'test', tmp); assert False
        except RuntimeError as exc:
            assert len(str(exc).splitlines()) == 200 and str(exc).splitlines()[-1] == '249'
    seeded = agents.defaults()
    assert [(a['name'], a['route']) for a in seeded['agents']] == [('Claude B','skill'),('Codex A','skill'),('Codex B','skill')] + [('agy g'+str(i),'prompt') for i in range(1,5)]
    assert seeded['agents'][1]['model'] == 'gpt-6.1-terra' and seeded['agents'][1]['effort'] == 'high'
    assert all(a['enabled'] and a['command'][-3:] == ['--model','gemini-3.8-flash-high','--print'] for a in seeded['agents'][3:])
    assert 'Shares quota with g1' in seeded['agents'][-1]['note']
    original_agents = agents.load()
    legacy_agents = agents.load()
    legacy_agents['agents'] = [a for a in legacy_agents['agents'] if a['name'] != 'agy g2']
    for a in legacy_agents['agents']:
        if a['name'] == 'agy g1': a.update(enabled=False, command=[])
        if a['name'] == 'agy g3': a['command'] = ['custom']
    agents.save(legacy_agents)
    migrated_agents = {a['name']:a for a in agents.load()['agents']}
    assert migrated_agents['agy g1']['command'] == seeded['agents'][3]['command']
    assert migrated_agents['agy g2']['command'] == seeded['agents'][4]['command']
    assert migrated_agents['agy g3']['command'] == ['custom']
    assert any(a['name'] == 'agy g2' for a in json.load(open(os.path.join(tmp,'agents.json'),encoding='utf-8'))['agents'])
    enabled = dict(seeded['agents'][3], enabled=True)
    with patch('agents.get', return_value=enabled), patch('agents.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='OK', stderr='')) as mocked:
        assert agents.run('agy g1', 'x' * 9000) == 'OK'   # long prompts go through a temp file, not the command line
        last = mocked.call_args.args[0][-1]
        assert last.startswith('Read the file ') and 'input' not in mocked.call_args.kwargs
        assert not os.path.exists(last.split(' ')[3])    # the prompt file is removed afterwards
    agents.save(original_agents)
    for program, route in [('claude','skill'), ('C:/bin/codex.cmd','skill'), ('other','prompt')]:
        assert agents.default_route({'type':'cli','command':[program]}) == route
    old = agents.load()
    old['agents'].append({'name':'legacy','type':'cli','enabled':True,'command':['codex','exec','-'],'env':{},'stdin':True})
    old['agents'].append({'name':'legacy api','type':'api','enabled':True,'url':'https://example.com','model':'x','style':'openai'})
    agents.save(old)
    migrated = {a['name']:a['route'] for a in call('GET','/api/agents')[1]['agents']}
    assert migrated['legacy'] == 'skill' and migrated['legacy api'] == 'prompt'
    assert call('POST','/api/agents',{'name':'api skill','type':'api','enabled':True,'url':'https://example.com','model':'x','style':'openai','route':'skill'})[0] == 400
    assert call('POST','/api/agents',{**agent,'route':'wrong'})[0] == 400
    skill_stub = os.path.join(tmp, 'skill_stub.py')
    with open(skill_stub, 'w', encoding='utf-8') as f:
        f.write('import os,sys,json\np=sys.stdin.read()\nif p.startswith("Reply with"):\n print("OK")\nelif os.environ["MODE"] != "missing":\n target=p.split("Write only this one new JSON output file: ")[1].splitlines()[0]\n open(target,"x",encoding="utf-8").write(os.environ["REPLY"])\nprint("cwd="+os.getcwd())\nprint(os.environ.get("STATUS", "HMR-STATUS: success"))\n')
    skill_agent = {'name':'skill stub','type':'cli','route':'skill','enabled':True,'command':[sys.executable,skill_stub],'env':{'MODE':'ok'},'stdin':True}
    assert call('POST','/api/agents',skill_agent)[0] == 200
    assert call('POST','/api/agents/test',{'name':'skill stub'})[1]['reply'].startswith('OK\n')
    assert call('POST','/api/agents/select',{'default':'skill stub','per_step':{'report_draft':'skill stub'}})[0] == 200
    for name, keys, out in [('report_draft',jobs.REPORT_KEYS,specpath)]:
        if os.path.exists(out): os.unlink(out)
        skill_agent['env'].update(MODE='ok', REPLY=json.dumps({key:'' for key in keys}))
        assert call('POST','/api/agents',skill_agent)[0] == 200
        assert run_job(name,patient_id=1)['state'] == 'done'
        assert set(json.load(open(out,encoding='utf-8'))) == keys
        original = open(out,encoding='utf-8').read()
        assert 'already exists' in run_job(name,patient_id=1)['output']
        assert open(out,encoding='utf-8').read() == original
        os.unlink(out)
        for mode, reply in [('missing',''),('ok','invalid JSON'),('ok','{}')]:
            skill_agent['env'].update(MODE=mode, REPLY=reply)
            assert call('POST','/api/agents',skill_agent)[0] == 200
            result = run_job(name,patient_id=1)
            assert result['state'] == 'failed' and 'Invalid or missing spec' in result['output']
            assert 'cwd=' + (tmp if name == 'interview_spec' else folder) in result['output']
            if os.path.exists(out): os.unlink(out)
    for status, expected in [('HMR-STATUS: blocked - missing evidence','missing evidence'), ('no status','agent gave no status')]:
        skill_agent['env'].update(MODE='ok', REPLY=json.dumps({key:'' for key in jobs.REPORT_KEYS}), STATUS=status)
        assert call('POST','/api/agents',skill_agent)[0] == 200
        result = run_job('report_draft',patient_id=1)
        assert result['state'] == 'failed' and result['output'].startswith(expected) and not os.path.exists(specpath)
    assert conn.execute("SELECT count(*) FROM events WHERE type IN ('interview_spec','report_draft') AND detail LIKE '%skill stub%' AND detail LIKE '%skill%'").fetchone()[0] == 1
    entered, release = threading.Event(), threading.Event()
    original = jobs.JOBS['register_xlsx']
    def slow(pid):
        entered.set(); release.wait(5); return '\n'.join(str(i) for i in range(250))
    jobs.JOBS['register_xlsx'] = slow
    try:
        status, running = call('POST', '/api/jobs', {'job':'register_xlsx'})
        assert status == 200 and entered.wait(2)
        assert call('GET', '/api/jobs/' + running['id'])[1]['state'] == 'running'
        queued = call('POST', '/api/jobs', {'job':'import_history'})
        assert queued[0] == 200
        assert call('POST', '/api/jobs', {'job':'import_history'})[0] == 400
        assert call('POST', '/api/run/' + queued[1]['id'] + '/cancel')[0] == 200
        release.set()
        for _ in range(500):
            finished = jobs.get(running['id'])
            if finished['state'] != 'running': break
            time.sleep(.01)
        assert finished['state'] == 'done' and len(finished['output'].splitlines()) == 200 and finished['output'].startswith('50\n')
    finally:
        release.set(); jobs.JOBS['register_xlsx'] = original
    # Queue readiness and browser results use synthetic data only.
    conn.execute("UPDATE patients SET state='confirmed',has_pathology=0,has_sheet=0,medicare=NULL,ihi=NULL WHERE id=1"); conn.commit()
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert not steps.BY_NAME['pathology'].ready(conn, p)[0]
    assert call('POST','/api/run', {'steps':['pathology'], 'patient_ids':[1]})[1]['skipped'][0]['reason']
    conn.execute("UPDATE patients SET medicare='1234567890' WHERE id=1"); conn.commit()
    result = call('POST','/api/run', {'steps':['pathology'], 'patient_ids':[1,2]})[1]
    assert len(result['enqueued']) == 1 and result['skipped'][0]['patient_id'] == 2
    tid = result['enqueued'][0]
    for _ in range(500):
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone()
        if row['state'] == 'waiting': break
        time.sleep(.01)
    assert row['state'] == 'waiting' and row['waiting_for'] == 'mhr'
    assert call('POST','/api/run', {'steps':['pathology'], 'patient_ids':[1]})[1]['skipped'][0]['reason'].startswith('task already')
    assert call('POST','/api/run/' + tid + '/result', {'state':'done','output':'finished'})[0] == 200
    assert call('POST','/api/run/' + tid + '/result', {'state':'done'})[0] == 400
    assert call('POST','/api/run', {'steps':['pathology'], 'patient_ids':[1]})[1]['enqueued']
    tid = call('GET','/api/run')[1]['tasks'][0]['id']
    for _ in range(500):
        if conn.execute('SELECT state FROM tasks WHERE id=?', (tid,)).fetchone()[0] == 'waiting': break
        time.sleep(.01)
    assert call('POST','/api/run/' + tid + '/cancel')[0] == 200
    assert call('GET','/api/run')[1]['tasks'][0]['patient_name'] == 'Alex Example'
    failed = call('POST','/api/run', {'steps':['pathology'], 'patient_ids':'ready'})[1]['enqueued'][0]
    for _ in range(500):
        if conn.execute('SELECT state FROM tasks WHERE id=?', (failed,)).fetchone()[0] == 'waiting': break
        time.sleep(.01)
    assert call('POST','/api/run/' + failed + '/result', {'state':'failed','output':'login needed'})[0] == 200
    assert conn.execute('SELECT output FROM tasks WHERE id=?',(failed,)).fetchone()[0] == 'login needed'
    token = service.api_token(conn)
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0), functools.partial(service.QuietStatic, directory=tmp))
    thread = threading.Thread(target=server.serve_forever); thread.start()
    def request(token_value=None, data=None, content_type=None):
        headers = {}
        if token_value is not None: headers['X-HMR-Token'] = token_value
        if content_type: headers['Content-Type'] = content_type
        req = urllib.request.Request('http://127.0.0.1:%d/api/status' % server.server_port, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as response: return response.status
        except urllib.error.HTTPError as e: return e.code
    try:
        assert request() == 403 and request('wrong') == 403 and request(token) == 200
        assert request(token, b'{}', 'text/plain') == 400
        assert request(token, b'[]', 'application/json') == 400
    finally:
        server.shutdown(); thread.join(); server.server_close()
        jobs._stop_worker.set(); jobs._wakeup.set(); jobs._worker.join(timeout=5)
        assert not jobs._worker.is_alive()
        conn.close()
print('api self-check ok')

assert api.anydate('25/06/1943').strftime('%d-%b-%Y') == '25-Jun-1943' and str(api.anydate('02/11/2026 (signed)')) == '2026-11-02'
print('date formats ok')

# Synthetic history trees stay untouched during both planning and apply.
import history
from pathlib import Path
from openpyxl import Workbook
with tempfile.TemporaryDirectory() as root:
    base = Path(root)/'base'; base.mkdir(); db.BASE = str(base)
    for folder in ['Visited/Jan/Amy Active_ AA','Visited/Jan/Bob Book_ BB', 'Visited/Jan/Cam Copy_ CC', 'Visited/Feb/Cam Copy_ DD', 'To CLAIM/Dee File_ DD', 'Completed & Claimed/Eve Unknown_ EE']:
        (base/folder).mkdir(parents=True)
    doc = base/'To CLAIM/Dee File_ DD/Report.docx'; doc.write_text('synthetic',encoding='utf-8')
    books = base/'old booking excel'; books.mkdir(); book = Workbook(); sheet=book.active
    sheet.append(['Name','Interview Date','Report Sent Date','Claimed'])
    sheet.append(['Bob Book',dt.date(2024,1,1),dt.date(2024,1,3),None]); book.save(books/'register.xlsx')
    before = {str(p.relative_to(base)): (p.stat().st_mtime_ns, p.stat().st_size) for p in base.rglob('*')}
    conn = db.connect(str(Path(root)/'history.db'))
    conn.execute("INSERT INTO patients(key,name,state,plan_order) VALUES ('amy active','Amy Active','confirmed',4)"); conn.commit()
    records=history.plan(conn); stats=history.summary(records)
    assert len(records)==6 and len(stats['ambiguous_names'])==1
    sources={r['name']:r['date_source'] for r in records}
    assert sources['Bob Book']=='workbook' and sources['Dee File']=='file date' and sources['Eve Unknown']=='unknown'
    assert history.apply(conn,records)==4 and history.apply(conn,records)==0
    assert tuple(conn.execute("SELECT state,plan_order FROM patients WHERE key='amy active'").fetchone()) == ('confirmed',4)
    assert tuple(conn.execute("SELECT state,plan_order FROM patients WHERE key='eve unknown'").fetchone()) == ('claimed',None)
    assert not conn.execute("SELECT 1 FROM patients WHERE key='cam copy'").fetchone()
    assert before == {str(p.relative_to(base)): (p.stat().st_mtime_ns, p.stat().st_size) for p in base.rglob('*')}
    conn.close()
print('history self-check ok')


import test_interview
import test_report
