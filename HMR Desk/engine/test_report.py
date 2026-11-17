"""Report checks use only synthetic records and temporary folders."""
import json
import os
from pathlib import Path
import tempfile
import pytest
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import api
import agents
import db
import interview
import jobs
import records
import report
import suggest
import steps

def test_report_workflow(monkeypatch):
    # Keep all temporary process configuration scoped to this collected test.
    for module, names in ((db, ('BASE', 'DATA_DIR')), (jobs, ('SKILL', 'BUILD_SCRIPT')), (api, ('MIMS_PATH',))):
        for name in names:
            monkeypatch.setattr(module, name, getattr(module, name))
    monkeypatch.setattr(api, 'MIMS_PATH', Path(__file__))  # list-code fixture only, not a real licensed helper
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; monkeypatch.setenv('HMR_DB', str(root / 'test.db'))
        folder = root / 'patient'; folder.mkdir()
        skill = root / 'skill'; (skill / 'scripts').mkdir(parents=True); (skill / 'references').mkdir()
        example = {k: 'Mr Firstname Surname Dr Firstname Surname' for k in report.REVIEW}
        (skill / 'scripts' / 'example-spec.json').write_text(json.dumps(example), encoding='utf-8')
        (skill / 'references' / 'finding-library.md').write_text('# Library\n## Aspirin diabetes\nReview aspirin for diabetes.\n## Other\nInsulin.\n', encoding='utf-8')
        cases = [{'Current Conditions':'diabetes', 'meds':[{'row':['aspirin']}], 'pathology':[], 'findings':[{'title':'Bleeding', 'rec':'Review aspirin', 'rationale':'Synthetic rationale'}]}]
        (skill / 'references' / 'case-index.jsonl').write_text('\n'.join(map(json.dumps, cases)), encoding='utf-8')
        old_skill, old_builder = jobs.SKILL, jobs.BUILD_SCRIPT
        jobs.SKILL = skill
        conn = None; first = second = None; release = None
        try:
            conn = db.connect(); conn.execute("INSERT INTO patients(key,name,state,folder,gp,visit_date) VALUES ('test person','Test Person','visited','patient','Dr Example','2026-01-02')"); conn.commit()
            p = conn.execute('SELECT * FROM patients').fetchone()
            assert not steps.ready('report_start', conn, p)[0]
            try: report.start(conn,p); assert False
            except ValueError as exc: assert 'confirm the medicine list first' in str(exc)
            records.put(conn, p['id'], 'report_spec.json', json.dumps({'out': str(root / 'old' / 'REPORT.DOCX')}).encode('utf-8'))
            (folder / 'report.docx').write_text('report', encoding='utf-8')
            assert steps.built(conn, p) and steps.done('report_build', conn, p)
            # Bare sign-off must be refused by the report-auth gate.
            try: api.action(conn, p, {'action': 'signed_off'}); assert False
            except ValueError as exc: assert 'review' in str(exc)
            assert not conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='state'", (p['id'],)).fetchone()
            conn.execute("UPDATE patients SET state='visited' WHERE id=?", (p['id'],)); conn.commit()
            records.delete(conn, p['id'], 'report_spec.json'); (folder / 'report.docx').unlink()
            with patch.object(interview, 'referral_text', return_value=('DOMICILIARY MEDICATION MANAGEMENT\nReason for referral\nReview medicine safety\nConditions\nDiabetes', [])):
                record = interview.load(conn,p)
            assert record['details']['reason'] == 'Review medicine safety'
            record['obs'][0][1:] = ['old','new']; record['meds'] = [['zinc','old','1 in the morning','','Clinical note'], ['aspirin','old','2 twice daily','',''], ['lisinopril','Once daily','Prior directions','','Note']]; record['details']['meds'] = [{'packed': '', 'as_instructed': False, 'checked': True, 'priority': 2}, {'packed': '', 'as_instructed': False, 'checked': False, 'priority': 0}, {'packed': '', 'as_instructed': False, 'checked': True, 'priority': 4, 'use_status': 'not_using', 'use_reason': 'side_effects', 'use_details': 'Cough'}]; record['other_meds'] = [['vitamin','daily','',''],['drug','daily','','stopped']]; record['details']['other_meds'] = [{'checked': True, 'priority': 1}, {'checked': False, 'priority': 0, 'use_status': 'not_using', 'use_reason': 'stopped_gp', 'use_details': 'Stopped'}]; record['pathology'] = [['FBC','normal','2026-01-01','comment']]
            record['details']['meds'][1].update(use_status='taking', use_reason='', use_details=''); record['details']['meds'][0]['packed'] = 'packed'; record['meds'][2][3] = 'Ceased AI point'; record['other_meds'][0][2:] = ['For wellbeing', 'Human found note']
            record['details']['meds'][0].update(use_status='unknown', use_reason='', use_details=''); record['details']['other_meds'][0].update(use_status='unknown', use_reason='', use_details='')
            record['notes'] = 'Human note'; record['concerns'] = 'Patient goal'; record['allergies'] = 'Allergy'; record['conditions'] = 'Condition'; record['meds'][0][3] = 'AI point to check'
            interview.save(conn,p,record); conn.commit()
            assert any(x['name'] == 'drug' and x['status'] == 'not_using' and 'Stopped by GP' in x['detail'] for x in api.interview_usage(conn, p))
            # A saved interview outranks AI proposals; a confirmed list outranks both (392159d).
            original = records.get(conn, p['id'], 'interview.json')
            form = json.loads(original); form['meds'].append(['legacy', '', 'daily', '', '']); form['details']['meds'].append({'packed': '', 'as_instructed': False})
            form['other_meds'].append(['found', 'daily', '', '']); form['details']['other_meds'].append({'checked': False, 'priority': 0})
            form['allergies'] = 'Penicillin\n\n Latex '
            records.put(conn, p['id'], 'interview.json', json.dumps(form).encode('utf-8'))
            ai_path = root / 'proposal.json'
            with patch.object(jobs, 'interview_spec_path', return_value=ai_path), patch.object(api.mims, 'ingredients', side_effect=lambda x: [x.lower()]):
                proposed = api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]
                assert proposed['meds'] == [['aspirin', ''], ['legacy', ''], ['found', '']] and proposed['allergies'] == ['Penicillin', 'Latex']
                ai_path.write_text(json.dumps({'meds': [['ai medicine']], 'allergies': ''}), encoding='utf-8')
                # Snapshot change 392159d explicitly puts saved interview data before the AI spec.
                assert api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]['meds'] == [['aspirin', ''], ['legacy', ''], ['found', '']]
                confirmed = {'meds': [['confirmed', 'brand']], 'allergies': ['other']}
                records.put(conn, p['id'], 'confirmed_meds.json', json.dumps(confirmed).encode('utf-8'))
                result = api.handle(conn, 'GET', '/api/patients/1/meds', {}, None)[1]
                assert all(result[k] == v for k, v in confirmed.items())
                records.delete(conn, p['id'], 'confirmed_meds.json')
            records.put(conn, p['id'], 'interview.json', original)
            with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower()]):
                assert api.conflicting_medicines(conn, p, [['drug', '']]) == ['drug']
                assert api.conflicting_medicines(conn, p, [['vitamin', '']]) == []
            stopped = {'name': 'drug 10mg tablet', 'status': 'not_using', 'detail': 'Not using', 'source': 'Referral medicine', 'directions': ['daily', '']}
            taking = {'name': 'drug 5mg', 'status': 'taking', 'detail': 'Taking', 'source': 'Found during interview', 'directions': ['daily', '']}
            with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower().split()[0]]), patch.object(api, 'interview_usage', return_value=[stopped, taking]) as usage:
                path = '/api/patients/1/meds'
                payload = {'meds': [['drug', '']], 'allergies': [], 'interview_usage': [stopped, taking]}
                # The handler requires the current interview medicine snapshot digest (freshness guard);
                # include it so each 400 below fails for its stated reconciliation reason, not the snapshot gate.
                _cur = api.current_medicine_snapshot(conn, p)
                payload['medicine_snapshot_sha256'] = api.medicine_snapshot.digest(_cur) if _cur is not None else 'missing'
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
                records.put(conn, p['id'], 'MIMS interactions old.txt', b'old')
                assert steps.interactions_done(conn, p)
                usage.return_value = [stopped, dict(taking, status='unknown', detail='Not yet confirmed')]
                assert not steps.interactions_done(conn, p) and not steps.ready('report_start', conn, p)[0]
                try: report.start(conn, p); assert False
                except ValueError: pass
                assert records.get(conn, p['id'], 'MIMS interactions old.txt') == b'old'
                records.delete(conn, p['id'], 'MIMS interactions old.txt')

                for changed in ([stopped, dict(taking, status='unknown', detail='Not yet confirmed')],
                                [dict(stopped, status='unknown', detail='Not yet confirmed'), taking], [taking], []):
                    usage.return_value = changed
                    try: api.mims_lists(conn); assert False
                    except ValueError as exc: assert 'reconciliation' in str(exc)
                # A legacy confirmation without overlapping stopped use remains usable.
                records.put_json(conn, p['id'], 'confirmed_meds.json', {'meds': [['other', '']], 'allergies': []})
                usage.return_value = [stopped, taking]
                assert api.mims_lists(conn)[0]['meds']
                records.delete(conn, p['id'], 'confirmed_meds.json')
            import local_referral_extraction
            with patch.object(local_referral_extraction, 'extract', return_value='Synthetic extraction'):
                extracted = jobs.report_extract(p['id'])
            assert 'Previously recorded directions (not yet confirmed): 1 in the morning' in extracted and 'Previously recorded directions (not yet confirmed): daily' in extracted
            assert all(value in extracted for value in ['Synthetic extraction', 'Human interview notes: Human note', 'Patient concerns / goals: Patient goal', 'Allergies / adverse reactions: Allergy', 'Conditions: Condition', 'Observation: Height / weight / BMI | Referral: old | At interview: new', 'Pathology: FBC | normal | 2026-01-01 | comment', 'Points to check: AI point to check | Notes: Clinical note', 'Referral medicine:', 'Medicine found during interview:'])
            assert '1 in the morning' in extracted and '2 twice daily' in extracted and 'Clinical note' in extracted and 'Not using — Stopped by GP' in extracted
            (folder / 'case.txt').unlink()
            records.put_json(conn, p['id'], 'confirmed_meds.json', {'meds': [['zinc',''], ['aspirin','']], 'allergies': []})
            assert 'eMIMS' in steps.ready('report_start',conn,p)[1]
            records.put(conn, p['id'], 'MIMS interactions.txt', b'synthetic')
            assert steps.ready('report_start',conn,p)[0]
            spec = report.start(conn,p); conn.commit()
            assert [r[0] for r in spec['meds']] == ['zinc', 'aspirin', 'vitamin'] and 'new' in spec['obs'] and len(spec['ceased']) == 2 and not spec['otc']
            assert records.get_json(conn, p['id'], 'confirmed_meds.json')['meds'] == [['zinc', ''], ['aspirin', '']]
            assert all(len(row) == 3 for row in spec['ceased'])
            assert spec['ceased'][0][0] == 'lisinopril' and 'Referral medicine' in spec['ceased'][0][2] and 'Side effects: Cough' in spec['ceased'][0][2]
            assert spec['ceased'][1][0] == 'drug' and 'Found during interview' in spec['ceased'][1][2] and 'Stopped by GP' in spec['ceased'][1][2]
            assert spec['meds'][0][1] == 'Not yet confirmed; previously recorded directions: 1 in the morning' and spec['meds'][0][2:] == ['Clinical note\nDAA: packed', ''] and spec['meds'][1][1] == '2 twice daily'
            assert spec['meds'][2][1:] == ['Not yet confirmed; previously recorded directions: daily', 'For wellbeing | Human found note', '']
            # medicine_snapshot is a provenance mirror of the saved interview record (freshness/tamper
            # detection), not rendered report content; the no-unreviewed-AI-content guard scopes to rendered fields.
            rendered = {k: v for k, v in spec.items() if k != 'medicine_snapshot'}
            assert all(not row[3] for row in spec['meds']) and 'AI point' not in json.dumps(rendered) and 'Taking' not in str(spec['meds'])
            assert spec['ceased'][0][2] == 'Referral medicine | Prior directions | Note\nNot using \u2014 Side effects: Cough'
            assert spec['reason'] == 'Review medicine safety' and 'reason' not in spec['needs_review']
            # PATH-01 (a415543): interview-entered pathology is explicitly labeled unverified.
            assert spec['path'][0] == ['FBC','normal','','','UNVERIFIED legacy interview entry — confirm against original source | comment Date: 2026-01-01'] and spec['needs_review'] == [x for x in report.REVIEW if x != 'reason']
            try: report.start(conn,p); assert False
            except FileExistsError: pass
            assert api.next_step(p, conn) == 'add findings' and 'finding' in steps.ready('report_build',conn,p)[1]
            try: jobs.report_build(p['id']); assert False
            except ValueError as exc: assert 'add at least one finding' in str(exc)
            bad = dict(spec, meds=[['bad']])
            try: report.save(conn,p,bad); assert False
            except ValueError: pass
            assert api.handle(conn,'POST','/api/patients/1/report',{},dict(spec, issues=[{'title':'', 'rec':'x','rationale':'x'}]))[0] == 400
            spec['issues'] = [{'title':'Finding','rec':'Review','rationale':'Reason'}]
            assert api.handle(conn,'POST','/api/patients/1/report',{},spec)[0] == 200
            assert records.exists(conn, p['id'], 'report_spec.json.bak') and api.next_step(p, conn) == 'build report'
            assert report.placeholders(spec) == ['intro', 'followup_decision']
            try: jobs.report_build(p['id']); assert False
            except ValueError as exc: assert 'intro' in str(exc) and 'followup_decision' in str(exc) and 'thanks' not in str(exc)
            # Placeholder semantics (a4c195f): a needs_review field is unresolved while its text is empty.
            spec['reason'] = ''; spec['needs_review'].append('reason')
            assert 'reason' in report.placeholders(spec)
            for k in spec['needs_review']: spec[k] = 'Edited ' + k
            spec['followup_decision'] = 'required'
            assert report.placeholders(spec) == []
            report.save(conn, p, spec); conn.commit()
            hits = report.library('aspirin diabetes'); assert [x['source'] for x in hits] == ['library','past case'] and not report.library('aspirin nonexistent')
            assert api.handle(conn,'GET','/api/library',{'q':['aspirin diabetes']},None)[1] == {'results': hits}
            before = records.get(conn, p['id'], 'report_spec.json')
            import settings
            settings.update(conn, {'clinical_ai_privacy_ack': True}); conn.commit()  # synthetic fixture only: opens the AI gate so the assist flow is exercised
            # Current assist flow: privacy-ack + restricted API agent + de-identified clinical JSON.
            # The synthetic reply cites a real evidence id from the prompt's clinical payload.
            def ai_reply(name, prompt):
                payload = json.loads(prompt.split('Clinical JSON: ', 1)[1])
                ev = payload['medicines'][0]['id']
                return json.dumps({'findings': [{'title': 'Finding', 'recommendation': 'Review', 'rationale': 'Reason', 'evidence_ids': [ev]}]})
            api_agent = {'name': 'stub-api', 'type': 'api', 'enabled': True}
            with patch('agents.selected', return_value='stub-api'), patch('agents.get', return_value=api_agent), patch('agents.run', side_effect=ai_reply):
                jobs.report_assist(p['id'])
                assert records.get(conn, p['id'], 'report_spec.json') == before
                records.delete(conn, p['id'], 'report_spec.ai.json')
                records.delete(conn, p['id'], 'report_spec.json'); conn.commit()  # jobs use their own connection
                jobs.report_assist(p['id'])
                try: jobs.report_assist(p['id']); assert False
                except FileExistsError: pass  # an existing AI draft must be reviewed or removed before rerunning
            candidate = records.get_json(conn, p['id'], 'report_spec.ai.json')
            assert candidate['issues'] == [{'title': 'Finding', 'rec': 'Review', 'rationale': 'Reason'}]
            # Assist composes the manual spec via start (findings stay in the AI draft only).
            assert records.get_json(conn, p['id'], 'report_spec.json') == dict(candidate, issues=[])
            assert api.handle(conn,'GET','/api/patients/1/report',{'ai':['1']},None)[1]['issues'] == candidate['issues']
            records.delete(conn, p['id'], 'report_spec.ai.json')
            records.delete(conn, p['id'], 'report_spec.json'); records.put(conn, p['id'], 'report_spec.json', before); conn.commit()  # jobs use their own connection
            builder = root / 'builder.py'; builder.write_text('import json,pathlib,sys\ns=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))\npathlib.Path(s["out"]).write_text("built",encoding="utf-8")\n',encoding='utf-8'); jobs.BUILD_SCRIPT = builder
            # MOCKED converter: this test covers the workflow around PDF creation only. Real conversion is
            # exercised separately by test_real_pdf_converter_when_available (skipped, not passed, without a converter).
            MOCK_PDF = b'MOCKED CONVERTER OUTPUT - NOT A REAL PDF'
            def fake_convert(docx, pdf, timeout=120):
                Path(pdf).write_bytes(MOCK_PDF); return {'created': True, 'bytes': len(MOCK_PDF)}
            with patch('pdf_export.convert', side_effect=fake_convert) as converter: jobs.report_build(p['id'], pdf=True)
            assert converter.call_count == 1 and Path(spec['out']).with_suffix('.pdf').read_bytes() == MOCK_PDF
            assert Path(spec['out']).is_file() and Path(spec['out']).with_suffix('.pdf').is_file()
            assert [s.name for s in steps.FLOW][-6:] == ['confirm_medicines','interactions','report_assist','report_start','report_build','claim']
            spec = report.load(conn, p); spec['issues'] = [{'title': 'Hand edited', 'rec': 'Review', 'rationale': 'Reason'}]; spec['intro'] = 'Intro ?'; spec['thanks'] = 'Thanks ?'; spec['reason'] = 'Edited reason'; spec['needs_review'] = [x for x in spec['needs_review'] if x != 'reason']
            report.save(conn, p, spec)
            old_spec = records.get(conn, p['id'], 'report_spec.json')
            record = interview.load(conn, p); record['meds'][1][2] = 'Changed use'; record['allergies'] += '\nLatex'; record['details']['reason'] = 'New reason'; interview.save(conn, p, record)
            assert api.handle(conn, 'GET', '/api/patients/1/report', {}, None)[1]['interview_newer'] is True
            confirmed_bytes = records.get(conn, p['id'], 'confirmed_meds.json'); records.delete(conn, p['id'], 'confirmed_meds.json')
            status, error = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
            assert status == 400 and error['error'] == 'confirm the medicine list first'
            records.put_json(conn, p['id'], 'confirmed_meds.json', {'meds': [['aspirin', '']], 'allergies': [], 'interview_usage': []})
            status, error = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
            assert status == 400 and error['error'] == 'Medicine use changed; review and confirm medicines first'
            records.put(conn, p['id'], 'confirmed_meds.json', confirmed_bytes)
            status, refreshed = api.handle(conn, 'POST', '/api/patients/1/report/refresh', {}, {})
            assert status == 200 and refreshed['meds'][1][1] == 'Changed use' and refreshed['allergies'].endswith('Latex')
            assert all(refreshed[k] == spec[k] for k in ('issues', 'intro', 'thanks', 'reason'))
            assert records.get(conn, p['id'], 'report_spec.json.bak') == old_spec
            assert api.handle(conn, 'GET', '/api/patients/1/report', {}, None)[1]['interview_newer'] is False
            assert conn.execute("SELECT 1 FROM events WHERE type='report_refreshed'").fetchone()
            refreshed['reason'] = 'New reason'; report.save(conn, p, refreshed)
            record = interview.load(conn, p); record['details']['reason'] = 'Latest reason'; interview.save(conn, p, record)
            refreshed = report.refresh(conn, p); assert refreshed['reason'] == 'New reason'
            legacy = dict(refreshed); legacy.pop('interview_revision'); legacy.pop('interview_reason'); report.validate(legacy); report.save(conn, p, legacy)
            assert report.load(conn, p)['interview_newer'] is False
            records.delete(conn, p['id'], 'report_spec.json')
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
            before = records.get(conn, p['id'], 'report_spec.json')
            with patch.object(interview, 'record_lock', side_effect=changed_before_lock):
                try: report.refresh(conn, p); raise AssertionError('stale confirmation accepted')
                except ValueError as exc: assert 'review and confirm medicines first' in str(exc)
            assert records.get(conn, p['id'], 'report_spec.json') == before
            from threading import Event, Thread
            entered = Event(); release = Event(); saved = Event(); derived = None
            def paused_derived(*args):
                entered.set(); assert release.wait(5); return derived
            edited = report.load(conn, p); edited['reason'] = 'Concurrent edit'
            errors = []
            # Engine connections are thread-bound (sqlcipher check_same_thread); each thread gets its own.
            def run_refresh():
                try:
                    c2 = db.connect()
                    try: report.refresh(c2, p)
                    finally: c2.close()
                except Exception as exc: errors.append(exc)
            def run_save():
                try:
                    c3 = db.connect()
                    try: report.save(c3, p, edited); saved.set()
                    finally: c3.close()
                except Exception as exc: errors.append(exc)
            # The changed medicine is restored below; bypass only the confirmation check here.
            with patch.object(api, 'confirmed_medicines_current', return_value=True): derived = report._derived(conn, p)
            conn.commit()  # release the main connection's write transaction so the thread connections can write (WAL: one writer)
            with patch.object(report, '_derived', side_effect=paused_derived), patch.object(db, 'log'):
                try:
                    first = Thread(target=run_refresh); first.start(); assert entered.wait(5)
                    second = Thread(target=run_save); second.start(); assert not saved.wait(0.1)
                finally:
                    release.set()  # never leave a worker blocked holding a database connection
                    for worker in (first, second):
                        if worker is not None and worker.is_alive(): worker.join(5)
            assert not first.is_alive() and not second.is_alive() and not errors and saved.is_set()
            assert report.load(conn, p)['reason'] == 'Concurrent edit'
            record = interview.load(conn, p); record['details']['meds'][1].update(use_status='taking', use_reason='', use_details=''); interview.save(conn, p, record)
            record = interview.load(conn, p); d = record['details']
            record['obs'] = [['Height / weight / BMI', 'old height', ''], ['BP', '120/80', ''], ['Pulse', '', '72']]; record['mobility'] = 'Walks independently'
            d.update(height_referral='170 cm', weight_actual='70 kg', home_bp='130/80', home_bgl='6', smoking='current', smoking_details='5 daily', alcohol='no', missed_doses='sometimes', missed_doses_details='weekly', device_technique='issues', device_technique_details='inhaler', swallowing='yes', swallowing_details='tablets', sx_falls='yes', sx_falls_details='one fall', sx_dizziness='no', sx_pain='not_asked', recent_change='yes', recent_change_details='specialist', present='with_other', present_details='daughter', lives='alone', manager='other', manager_details='daughter', daa='yes', daa_type='webster', daa_pharmacy='Local pharmacy')
            record['meds'][1][2] = 'When required'; d['meds'][1]['prn_use'] = 'twice weekly'; d['other_meds'][0]['kind'] = 'otc'
            interview.save(conn, p, record)
            with patch.object(api, 'confirmed_medicines_current', return_value=True):
                records.delete(conn, p['id'], 'report_spec.json'); mapped = report.start(conn, p)
                assert mapped['obs'].splitlines() == ['BP: 120/80 (referral)', 'Pulse: 72', 'Height / weight / BMI: Height: 170 cm (referral); Weight: 70 kg', 'Home BP readings: 130/80', 'Home blood glucose readings: 6', 'Smoking: Current smoker — 5 daily', 'Alcohol: No alcohol', 'Mobility: Walks independently', 'Missed doses: sometimes — weekly', 'Device technique: issues — inhaler', 'Swallowing problems reported: tablets', 'Reports falls in the last 12 months: one fall', 'Recent hospital or specialist change: specialist']
                assert 'Reports falls in the last 12 months: one fall' in suggest.context_for(conn, p)['obs']
                assert mapped['intro'] == 'Test Person was interviewed at home on 2026-01-02, with daughter present. Test Person lives alone. Medicines are managed by daughter, using a dose administration aid (Webster pack) packed by Local pharmacy.'
                assert 'intro' in mapped['needs_review'] and 'intro' not in report.placeholders(mapped)
                assert mapped['otc'][0][0] == 'vitamin' and mapped['meds'][1][1] == 'When required; used twice weekly'
                assert not any(code in json.dumps(mapped) for code in ('with_other', 'webster', 'not_asked', 'sx_'))
                record = interview.load(conn, p); record['details']['sx_falls_details'] = 'two falls'; interview.save(conn, p, record)
                mapped['intro'] = 'Edited intro'; report.save(conn, p, mapped); refreshed = report.refresh(conn, p)
                assert refreshed['intro'] == 'Edited intro' and 'two falls' in refreshed['obs']
                record = interview.load(conn, p); record['details'] = interview.empty_details(); record['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in record['meds']]; record['details']['other_meds'] = [{'checked': False, 'priority': 0} for _ in record['other_meds']]; record['obs'] = [['Height / weight / BMI', 'height', ''], ['BP', '', '']]; record['mobility'] = ''; interview.save(conn, p, record)
                records.delete(conn, p['id'], 'report_spec.json'); empty = report.start(conn, p)
                assert empty['obs'] == 'Height / weight / BMI: height (referral)' and 'intro' in report.placeholders(empty)
        finally:
            jobs.SKILL, jobs.BUILD_SCRIPT = old_skill, old_builder
            if conn is not None: conn.close()  # always release test.db so Windows can delete the temp folder
    print('report self-check ok')


def test_real_pdf_converter_when_available(tmp_path):
    import pdf_export
    if not pdf_export.available():
        pytest.skip('No PDF converter (HMR_PDF_CONVERTER or soffice on PATH): REAL DOCX->PDF conversion NOT tested here')
    import docx, fitz
    source = tmp_path / 'report.docx'; document = docx.Document(); document.add_paragraph('Synthetic converter check'); document.save(source)
    target = tmp_path / 'report.pdf'
    result = pdf_export.convert(source, target)
    assert result['created'] and target.read_bytes()[:5] == b'%PDF-'
    with fitz.open(target) as rendered: assert rendered.page_count >= 1 and 'Synthetic converter check' in rendered[0].get_text()


def test_followup_review_binding_and_key_validation(tmp_path):
    import manual_defaults
    base = {'followup_decision': 'not_required', 'followup': 'x'}
    old = {**base, 'followup': manual_defaults.not_required_followup('A B'), 'followup_reviewed_sha256': manual_defaults.text_sha(manual_defaults.not_required_followup('A B'))}
    same = report._bind_followup_review({**old, 'followup_text_reviewed': True}, old)
    assert same['followup_reviewed_sha256'] == old['followup_reviewed_sha256'] and 'followup_text_reviewed' not in same
    edited = report._bind_followup_review({**old, 'followup': old['followup'] + ' more', 'followup_text_reviewed': True}, old)
    assert edited['followup_reviewed_sha256'] == ''
    switched = report._bind_followup_review({**old, 'followup_decision': 'required', 'followup_text_reviewed': True}, old)
    assert switched['followup_reviewed_sha256'] == ''
    fresh = report._bind_followup_review({**old, 'followup_reviewed_sha256': '', 'followup_text_reviewed': True}, {})
    assert fresh['followup_reviewed_sha256'] == ''  # a first save cannot claim a prior review
