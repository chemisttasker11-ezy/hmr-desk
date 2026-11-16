"""Report checks use only synthetic records and temporary folders."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import api
import agents
import db
import interview
import jobs
import report
import suggest
import steps

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    folder = root / 'patient'; folder.mkdir()
    skill = root / 'skill'; (skill / 'scripts').mkdir(parents=True); (skill / 'references').mkdir()
    example = {k: 'Mr Firstname Surname Dr Firstname Surname' for k in report.REVIEW}
    (skill / 'scripts' / 'example-spec.json').write_text(json.dumps(example), encoding='utf-8')
    (skill / 'references' / 'finding-library.md').write_text('# Library\n## Aspirin diabetes\nReview aspirin for diabetes.\n## Other\nInsulin.\n', encoding='utf-8')
    cases = [{'Current Conditions':'diabetes', 'meds':[{'row':['aspirin']}], 'pathology':[], 'findings':[{'title':'Bleeding', 'rec':'Review aspirin', 'rationale':'Synthetic rationale'}]}]
    (skill / 'references' / 'case-index.jsonl').write_text('\n'.join(map(json.dumps, cases)), encoding='utf-8')
    old_skill, old_builder = jobs.SKILL, jobs.BUILD_SCRIPT
    jobs.SKILL = skill
    try:
        conn = db.connect(); conn.execute("INSERT INTO patients(key,name,state,folder,gp,visit_date) VALUES ('test person','Test Person','visited','patient','Dr Example','2026-01-02')"); conn.commit()
        p = conn.execute('SELECT * FROM patients').fetchone()
        assert not steps.ready('report_start', conn, p)[0]
        try: report.start(conn,p); assert False
        except ValueError as exc: assert 'confirm the medicine list first' in str(exc)
        (folder / 'report_spec.json').write_text(json.dumps({'out': str(root / 'old' / 'REPORT.DOCX')}), encoding='utf-8')
        (folder / 'report.docx').write_text('report', encoding='utf-8')
        assert steps.built(p) and steps.done('report_build', conn, p)
        api.action(conn, p, {'action': 'signed_off'})
        states = [json.loads(r[0])['to'] for r in conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='state' ORDER BY id", (p['id'],))]
        assert states == ['report_drafted', 'signed_off']
        conn.execute("UPDATE patients SET state='visited' WHERE id=?", (p['id'],)); conn.commit()
        (folder / 'report_spec.json').unlink(); (folder / 'report.docx').unlink()
        with patch.object(interview, 'referral_text', return_value=('DOMICILIARY MEDICATION MANAGEMENT\nReason for referral\nReview medicine safety\nConditions\nDiabetes', [])):
            record = interview.load(conn,p)
        assert record['details']['reason'] == 'Review medicine safety'
        record['obs'][0][1:] = ['old','new']; record['meds'] = [['zinc','old','1 in the morning','','Clinical note'], ['aspirin','old','2 twice daily','',''], ['lisinopril','Once daily','Prior directions','','Note']]; record['details']['meds'] = [{'packed': '', 'as_instructed': False, 'checked': True, 'priority': 2}, {'packed': '', 'as_instructed': False, 'checked': False, 'priority': 0}, {'packed': '', 'as_instructed': False, 'checked': True, 'priority': 4, 'use_status': 'not_using', 'use_reason': 'side_effects', 'use_details': 'Cough'}]; record['other_meds'] = [['vitamin','daily','',''],['drug','daily','','stopped']]; record['details']['other_meds'] = [{'checked': True, 'priority': 1}, {'checked': False, 'priority': 0, 'use_status': 'not_using', 'use_reason': 'stopped_gp', 'use_details': 'Stopped'}]; record['pathology'] = [['FBC','normal','2026-01-01','comment']]
        record['details']['meds'][1].update(use_status='taking', use_reason='', use_details=''); record['details']['meds'][0]['packed'] = 'packed'; record['meds'][2][3] = 'Ceased AI point'; record['other_meds'][0][2:] = ['For wellbeing', 'Human found note']
        record['details']['meds'][0].update(use_status='unknown', use_reason='', use_details=''); record['details']['other_meds'][0].update(use_status='unknown', use_reason='', use_details='')
        record['notes'] = 'Human note'; record['concerns'] = 'Patient goal'; record['allergies'] = 'Allergy'; record['conditions'] = 'Condition'; record['meds'][0][3] = 'AI point to check'
        interview.save(conn,p,record); conn.commit()
        assert any(x['name'] == 'drug' and x['status'] == 'not_using' and 'Stopped by GP' in x['detail'] for x in api.interview_usage(p))
        # Proposals use saved form data only when no AI spec or confirmed list exists.
        original = (folder / 'interview.json').read_bytes()
        form = json.loads(original); form['meds'].append(['legacy', '', 'daily', '', '']); form['details']['meds'].append({'packed': '', 'as_instructed': False})
        form['other_meds'].append(['found', 'daily', '', '']); form['details']['other_meds'].append({'checked': False, 'priority': 0})
        form['allergies'] = 'Penicillin\n\n Latex '
        (folder / 'interview.json').write_text(json.dumps(form), encoding='utf-8')
        ai_path = root / 'proposal.json'
        with patch.object(jobs, 'interview_spec_path', return_value=ai_path), patch.object(api.mims, 'ingredients', side_effect=lambda x: [x.lower()]):
            proposed = api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]
            assert proposed['meds'] == [['aspirin', ''], ['legacy', ''], ['found', '']] and proposed['allergies'] == ['Penicillin', 'Latex']
            ai_path.write_text(json.dumps({'meds': [['ai medicine']], 'allergies': ''}), encoding='utf-8')
            assert api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]['meds'] == [['ai medicine', '']]
            confirmed = {'meds': [['confirmed', 'brand']], 'allergies': ['other']}
            (folder / 'confirmed_meds.json').write_text(json.dumps(confirmed), encoding='utf-8')
            result = api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]
            assert all(result[k] == v for k, v in confirmed.items())
            (folder / 'confirmed_meds.json').unlink()
        (folder / 'interview.json').write_bytes(original)
        with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower()]):
            assert api.conflicting_medicines(p, [['drug', '']]) == ['drug']
            assert api.conflicting_medicines(p, [['vitamin', '']]) == []
        stopped = {'name': 'drug 10mg tablet', 'status': 'not_using', 'detail': 'Not using', 'source': 'Referral medicine', 'directions': ['daily', '']}
        taking = {'name': 'drug 5mg', 'status': 'taking', 'detail': 'Taking', 'source': 'Found during interview', 'directions': ['daily', '']}
        with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower().split()[0]]), patch.object(api, 'interview_usage', return_value=[stopped, taking]) as usage:
            path = '/api/patients/1/meds'
            payload = {'meds': [['drug', '']], 'allergies': [], 'interview_usage': [stopped, taking]}
            assert api.handle(conn, 'POST', path, {}, payload)[0] == 400  # Echoing the snapshot is not reconciliation.
            payload['alternatives'] = [stopped]
            assert api.handle(conn, 'POST', path, {}, payload)[0] == 400
            payload['alternatives'] = [taking]
            payload['meds'] = [['drug 10mg', '']]
            assert api.handle(conn, 'POST', path, {}, payload)[0] == 400  # The stopped product itself stays stopped.
            payload['meds'] = [['drug', '']]
            assert api.handle(conn, 'POST', path, {}, payload)[0] == 400  # Ingredient alone does not identify the selected product.
            payload['meds'] = [['drug 5mg', '']]
            assert api.handle(conn, 'POST', path, {}, payload)[0] == 200
            assert api.mims_lists(conn)[0]['meds']
            interaction = folder / 'MIMS interactions old.txt'; interaction.write_text('old', encoding='utf-8')
            assert steps.interactions_done(p)
            usage.return_value = [stopped, dict(taking, status='unknown', detail='Not yet confirmed')]
            assert not steps.interactions_done(p) and not steps.ready('report_start', conn, p)[0]
            try: report.start(conn, p); assert False
            except ValueError: pass
            assert interaction.read_text(encoding='utf-8') == 'old'
            interaction.unlink()

            for changed in ([stopped, dict(taking, status='unknown', detail='Not yet confirmed')],
                            [dict(stopped, status='unknown', detail='Not yet confirmed'), taking], [taking], []):
                usage.return_value = changed
                try: api.mims_lists(conn); assert False
                except ValueError as exc: assert 'reconciliation' in str(exc)
            # A legacy confirmation without overlapping stopped use remains usable.
            (folder / 'confirmed_meds.json').write_text(json.dumps({'meds': [['other', '']], 'allergies': []}), encoding='utf-8')
            usage.return_value = [stopped, taking]
            assert api.mims_lists(conn)[0]['meds']
            (folder / 'confirmed_meds.json').unlink()
        with patch.object(jobs, 'run_script', return_value='Synthetic extraction'):
            extracted = jobs.report_extract(p['id'])
        assert 'Previously recorded directions (not yet confirmed): 1 in the morning' in extracted and 'Previously recorded directions (not yet confirmed): daily' in extracted
        assert all(value in extracted for value in ['Synthetic extraction', 'Human interview notes: Human note', 'Patient concerns / goals: Patient goal', 'Allergies / adverse reactions: Allergy', 'Conditions: Condition', 'Observation: Height / weight / BMI | Referral: old | At interview: new', 'Pathology: FBC | normal | 2026-01-01 | comment', 'Points to check: AI point to check | Notes: Clinical note', 'Referral medicine:', 'Medicine found during interview:'])
        assert '1 in the morning' in extracted and '2 twice daily' in extracted and 'Clinical note' in extracted and 'Not using — Stopped by GP' in extracted
        (folder / 'case.txt').unlink()
        (folder / 'confirmed_meds.json').write_text(json.dumps({'meds': [['zinc',''], ['aspirin','']], 'allergies': []}), encoding='utf-8')
        assert 'eMIMS' in steps.ready('report_start',conn,p)[1]
        (folder / 'MIMS interactions.txt').write_text('synthetic',encoding='utf-8')
        assert steps.ready('report_start',conn,p)[0]
        spec = report.start(conn,p); conn.commit()
        assert [r[0] for r in spec['meds']] == ['zinc', 'aspirin', 'vitamin'] and 'new' in spec['obs'] and len(spec['ceased']) == 2 and not spec['otc']
        assert json.loads((folder / 'confirmed_meds.json').read_text(encoding='utf-8'))['meds'] == [['zinc', ''], ['aspirin', '']]
        assert all(len(row) == 3 for row in spec['ceased'])
        assert spec['ceased'][0][0] == 'lisinopril' and 'Referral medicine' in spec['ceased'][0][2] and 'Side effects: Cough' in spec['ceased'][0][2]
        assert spec['ceased'][1][0] == 'drug' and 'Found during interview' in spec['ceased'][1][2] and 'Stopped by GP' in spec['ceased'][1][2]
        assert spec['meds'][0][1] == 'Not yet confirmed; previously recorded directions: 1 in the morning' and spec['meds'][0][2:] == ['Clinical note\nDAA: packed', ''] and spec['meds'][1][1] == '2 twice daily'
        assert spec['meds'][2][1:] == ['Not yet confirmed; previously recorded directions: daily', 'For wellbeing | Human found note', '']
        assert all(not row[3] for row in spec['meds']) and 'AI point' not in json.dumps(spec) and 'Taking' not in str(spec['meds'])
        assert spec['ceased'][0][2] == 'Referral medicine | Prior directions | Note\nNot using \u2014 Side effects: Cough'
        assert spec['reason'] == 'Review medicine safety' and 'reason' not in spec['needs_review']
        assert spec['path'][0] == ['FBC','normal','','','comment Date: 2026-01-01'] and spec['needs_review'] == [x for x in report.REVIEW if x != 'reason']
        try: report.start(conn,p); assert False
        except FileExistsError: pass
        assert api.next_step(p) == 'add findings' and 'finding' in steps.ready('report_build',conn,p)[1]
        try: jobs.report_build(p['id']); assert False
        except ValueError as exc: assert 'add at least one finding' in str(exc)
        bad = dict(spec, meds=[['bad']])
        try: report.save(conn,p,bad); assert False
        except ValueError: pass
        assert api.handle(conn,'POST','/api/patients/1/report',{},dict(spec, issues=[{'title':'', 'rec':'x','rationale':'x'}]))[0] == 400
        spec['issues'] = [{'title':'Finding','rec':'Review','rationale':'Reason'}]
        assert api.handle(conn,'POST','/api/patients/1/report',{},spec)[0] == 200
        assert (folder / 'report_spec.json.bak').is_file() and api.next_step(p) == 'build report'
        assert report.placeholders(spec) == ['intro']
        try: jobs.report_build(p['id']); assert False
        except ValueError as exc: assert 'intro' in str(exc) and 'thanks' not in str(exc) and 'followup' not in str(exc)
        spec['reason'] = example['reason'].replace('Mr Firstname Surname', spec['name']).replace('Dr Firstname Surname', 'Dr Example'); spec['needs_review'].append('reason')
        assert 'reason' in report.placeholders(spec)
        for k in spec['needs_review']: spec[k] = 'Edited ' + k
        assert report.placeholders(spec) == []
        report.save(conn, p, spec); conn.commit()
        hits = report.library('aspirin diabetes'); assert [x['source'] for x in hits] == ['library','past case'] and not report.library('aspirin nonexistent')
        assert api.handle(conn,'GET','/api/library',{'q':['aspirin diabetes']},None)[1] == {'results': hits}
        def draft(pid, name, output):
            output.write_text(json.dumps(spec), encoding='utf-8'); return 'ok'
        before = (folder / 'report_spec.json').read_bytes()
        with patch('jobs.agent_step', side_effect=draft): jobs.report_assist(p['id']); jobs.report_assist(p['id'])
        assert (folder / 'report_spec.json').read_bytes() == before and api.handle(conn,'GET','/api/patients/1/report',{'ai':['1']},None)[1] == spec
        (folder / 'case.txt').write_text('', encoding='utf-8')
        (skill / 'SKILL.md').write_text('Synthetic', encoding='utf-8')
        (skill / 'references' / 'report-runbook.md').write_text('Synthetic', encoding='utf-8')
        def skill_stub(selected, prompt, cwd):
            output = prompt.split('Write only this one new JSON output file: ')[1].splitlines()[0]
            Path(output).write_text(json.dumps(spec), encoding='utf-8')
            return 'HMR-STATUS: success'
        with patch('agents.selected', return_value='stub'), patch('agents.get', return_value={'route':'skill'}), patch('agents.skill_run', side_effect=skill_stub): jobs.report_assist(p['id'])
        with patch('agents.selected', return_value='stub'), patch('agents.get', return_value={'route':'prompt'}), patch('agents.run', return_value=json.dumps(spec)): jobs.report_assist(p['id'])
        assert (folder / 'report_spec.json').read_bytes() == before and json.loads((folder / 'report_spec.ai.json').read_text(encoding='utf-8')) == spec
        builder = root / 'builder.py'; builder.write_text('import json,pathlib,sys\ns=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))\npathlib.Path(s["out"]).write_text("built",encoding="utf-8")\n',encoding='utf-8'); jobs.BUILD_SCRIPT = builder
        real_run = subprocess.run
        def run_stub(args, **kwargs):
            if args[0] == 'powershell':
                Path(args[-1]).write_text('synthetic PDF', encoding='utf-8')
                return SimpleNamespace(returncode=0)
            return real_run(args, **kwargs)
        with patch('jobs.subprocess.run', side_effect=run_stub): jobs.report_build(p['id'], pdf=True)
        assert Path(spec['out']).is_file() and Path(spec['out']).with_suffix('.pdf').is_file()
        assert [s.name for s in steps.FLOW][-6:] == ['confirm_medicines','interactions','report_assist','report_start','report_build','claim']
        spec = report.load(conn, p); spec['issues'] = [{'title': 'Hand edited', 'rec': 'Review', 'rationale': 'Reason'}]; spec['intro'] = 'Intro ?'; spec['thanks'] = 'Thanks ?'; spec['reason'] = 'Edited reason'; spec['needs_review'] = [x for x in spec['needs_review'] if x != 'reason']
        report.save(conn, p, spec)
        old_spec = (folder / 'report_spec.json').read_bytes()
        record = interview.load(conn, p); record['meds'][1][2] = 'Changed use'; record['allergies'] += '\nLatex'; record['details']['reason'] = 'New reason'; interview.save(conn, p, record)
        assert api.handle(conn, 'GET', '/api/patients/1/report', {}, None)[1]['interview_newer'] is True
        confirmed_path = folder / 'confirmed_meds.json'; confirmed_bytes = confirmed_path.read_bytes(); confirmed_path.unlink()
        status, error = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
        assert status == 400 and error['error'] == 'confirm the medicine list first'
        confirmed_path.write_text(json.dumps({'meds': [['aspirin', '']], 'allergies': [], 'interview_usage': []}), encoding='utf-8')
        status, error = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
        assert status == 400 and error['error'] == 'Medicine use changed; review and confirm medicines first'
        confirmed_path.write_bytes(confirmed_bytes)
        status, refreshed = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
        assert status == 200 and refreshed['meds'][1][1] == 'Changed use' and refreshed['allergies'].endswith('Latex')
        assert all(refreshed[k] == spec[k] for k in ('issues', 'intro', 'thanks', 'reason'))
        assert (folder / 'report_spec.json.bak').read_bytes() == old_spec
        assert api.handle(conn, 'GET', '/api/patients/1/report', {}, None)[1]['interview_newer'] is False
        assert conn.execute("SELECT 1 FROM events WHERE type='report_refreshed'").fetchone()
        refreshed['reason'] = 'New reason'; report.save(conn, p, refreshed)
        record = interview.load(conn, p); record['details']['reason'] = 'Latest reason'; interview.save(conn, p, record)
        refreshed = report.refresh(conn, p); assert refreshed['reason'] == 'New reason'
        legacy = dict(refreshed); legacy.pop('interview_revision'); legacy.pop('interview_reason'); report.validate(legacy); report.save(conn, p, legacy)
        assert report.load(conn, p)['interview_newer'] is False
        (folder / 'report_spec.json').unlink()
        record = interview.load(conn, p); record['details']['reason'] = ''; interview.save(conn, p, record)
        empty_reason = report.start(conn, p); assert 'reason' in empty_reason['needs_review'] and 'reason' in report.placeholders(empty_reason)
        empty_reason['reason'] = 'Pharmacist rewrite'; report.save(conn, p, empty_reason)
        original_fields = json.dumps([empty_reason['reason'], empty_reason['needs_review']], ensure_ascii=False).encode('utf-8')
        record = interview.load(conn, p); record['details']['reason'] = 'Referral changed'; interview.save(conn, p, record)
        refreshed = report.refresh(conn, p)
        assert json.dumps([refreshed['reason'], refreshed['needs_review']], ensure_ascii=False).encode('utf-8') == original_fields
        # A save completed immediately before lock acquisition must be included in the check.
        from contextlib import contextmanager
        real_lock = interview.record_lock
        @contextmanager
        def changed_before_lock(patient):
            with real_lock(patient):
                changed = interview.load(conn, patient); changed['details']['meds'][1].update(use_status='not_using', use_reason='', use_details=''); interview.save(conn, patient, changed, locked=True)
            with real_lock(patient): yield
        before = (folder / 'report_spec.json').read_bytes()
        with patch.object(interview, 'record_lock', side_effect=changed_before_lock):
            try: report.refresh(conn, p); raise AssertionError('stale confirmation accepted')
            except ValueError as exc: assert 'review and confirm medicines first' in str(exc)
        assert (folder / 'report_spec.json').read_bytes() == before
        from threading import Event, Thread
        entered = Event(); release = Event(); saved = Event(); derived = None
        def paused_derived(*args):
            entered.set(); assert release.wait(5); return derived
        edited = report.load(conn, p); edited['reason'] = 'Concurrent edit'
        errors = []
        def run_refresh():
            try: report.refresh(conn, p)
            except Exception as exc: errors.append(exc)
        def run_save():
            try: report.save(conn, p, edited); saved.set()
            except Exception as exc: errors.append(exc)
        # The changed medicine is restored below; bypass only the confirmation check here.
        with patch.object(api, 'confirmed_medicines_current', return_value=True): derived = report._derived(conn, p)
        with patch.object(report, '_derived', side_effect=paused_derived), patch.object(db, 'log'):
            first = Thread(target=run_refresh); first.start(); assert entered.wait(5)
            second = Thread(target=run_save); second.start(); assert not saved.wait(0.1)
            release.set(); first.join(5); second.join(5)
        assert not first.is_alive() and not second.is_alive() and not errors and saved.is_set()
        assert report.load(conn, p)['reason'] == 'Concurrent edit'
        record = interview.load(conn, p); record['details']['meds'][1].update(use_status='taking', use_reason='', use_details=''); interview.save(conn, p, record)
        record = interview.load(conn, p); d = record['details']
        record['obs'] = [['Height / weight / BMI', 'old height', ''], ['BP', '120/80', ''], ['Pulse', '', '72']]; record['mobility'] = 'Walks independently'
        d.update(height_referral='170 cm', weight_actual='70 kg', home_bp='130/80', home_bgl='6', smoking='current', smoking_details='5 daily', alcohol='no', missed_doses='sometimes', missed_doses_details='weekly', device_technique='issues', device_technique_details='inhaler', swallowing='yes', swallowing_details='tablets', sx_falls='yes', sx_falls_details='one fall', sx_dizziness='no', sx_pain='not_asked', recent_change='yes', recent_change_details='specialist', present='with_other', present_details='daughter', lives='alone', manager='other', manager_details='daughter', daa='yes', daa_type='webster', daa_pharmacy='Local pharmacy')
        record['meds'][1][2] = 'When required'; d['meds'][1]['prn_use'] = 'twice weekly'; d['other_meds'][0]['kind'] = 'otc'
        interview.save(conn, p, record)
        with patch.object(api, 'confirmed_medicines_current', return_value=True):
            (folder / 'report_spec.json').unlink(); mapped = report.start(conn, p)
            assert mapped['obs'].splitlines() == ['BP: 120/80 (referral)', 'Pulse: 72', 'Height / weight / BMI: Height: 170 cm (referral); Weight: 70 kg', 'Home BP readings: 130/80', 'Home blood glucose readings: 6', 'Smoking: Current smoker — 5 daily', 'Alcohol: No alcohol', 'Mobility: Walks independently', 'Missed doses: sometimes — weekly', 'Device technique: issues — inhaler', 'Swallowing problems reported: tablets', 'Reports falls in the last 12 months: one fall', 'Recent hospital or specialist change: specialist']
            assert 'Reports falls in the last 12 months: one fall' in suggest.context_for(conn, p)['obs']
            assert mapped['intro'] == 'I visited Test Person on 2026-01-02, with daughter present. Test Person lives alone. Medicines are managed by daughter, using a dose administration aid (Webster pack) packed by Local pharmacy.'
            assert 'intro' in mapped['needs_review'] and 'intro' not in report.placeholders(mapped)
            assert mapped['otc'][0][0] == 'vitamin' and mapped['meds'][1][1] == 'When required; used twice weekly'
            assert not any(code in json.dumps(mapped) for code in ('with_other', 'webster', 'not_asked', 'sx_'))
            record = interview.load(conn, p); record['details']['sx_falls_details'] = 'two falls'; interview.save(conn, p, record)
            mapped['intro'] = 'Edited intro'; report.save(conn, p, mapped); refreshed = report.refresh(conn, p)
            assert refreshed['intro'] == 'Edited intro' and 'two falls' in refreshed['obs']
            record = interview.load(conn, p); record['details'] = interview.empty_details(); record['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in record['meds']]; record['details']['other_meds'] = [{'checked': False, 'priority': 0} for _ in record['other_meds']]; record['obs'] = [['Height / weight / BMI', 'height', ''], ['BP', '', '']]; record['mobility'] = ''; interview.save(conn, p, record)
            (folder / 'report_spec.json').unlink(); empty = report.start(conn, p)
            assert empty['obs'] == 'Height / weight / BMI: height (referral)' and 'intro' in report.placeholders(empty)
        conn.close()
    finally: jobs.SKILL, jobs.BUILD_SCRIPT = old_skill, old_builder
print('report self-check ok')
