"""Work routes: jobs, runs (step workflow tasks) and referral intake.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None
otherwise. ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re
from contextlib import nullcontext

import db
import jobs
import settings
import steps


def fill_referral_fields(conn, patient):
    if patient['dob'] and patient['sex'] and (patient['medicare'] or patient['ihi']) and patient['clinic']: return patient
    try:
        import interview
        text, _ = interview.referral_text(jobs.patient_folder(patient))
        if text is None: return patient
        spec = importlib.util.spec_from_file_location('hmr_intake', Path(db.BASE) / 'scripts' / 'intake' / 'intake.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        fields, _ = module.extract_fields(text)
        values = {k: fields[k] for k in ('dob', 'sex', 'medicare', 'irn', 'clinic') if not patient[k] and fields.get(k)}
        if not values: return patient
        conn.execute('SAVEPOINT referral_fields')
        try:
            conn.execute('UPDATE patients SET ' + ','.join(k + '=?' for k in values) + ',updated_at=? WHERE id=?', [*values.values(), db.now(), patient['id']])
            db.log(conn, patient['id'], 'referral_fields', values, 'engine')
            conn.execute('RELEASE referral_fields')
        except Exception:
            conn.execute('ROLLBACK TO referral_fields'); conn.execute('RELEASE referral_fields')
            raise
        conn.commit()
        return conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
    except Exception:
        return patient


def recent_tasks(conn, patient_id=None, limit=200):
    return [dict(row) for row in conn.execute(
        "SELECT tasks.*,patients.name AS patient_name FROM tasks LEFT JOIN patients ON patients.id=tasks.patient_id WHERE (? IS NULL OR tasks.patient_id=?) ORDER BY tasks.rowid DESC LIMIT ?",
        (patient_id, patient_id, limit))]


def handle(conn, method, path, query, body):
    if method == 'POST' and path == '/api/jobs' and isinstance(body, dict):
        if body.get('job') in ('intake_dry', 'intake_apply'): raise ValueError('Use New referrals to review PDFs before adding patients')
        if 'pdf' in body and (body.get('job') != 'report_build' or not isinstance(body['pdf'], bool)): raise ValueError('invalid pdf')
        fmt = ('pdf' if body['pdf'] else 'docx') if 'pdf' in body else body.get('format', settings.get(conn, 'interview_export_format') if body.get('job') in ('interview_pack', 'interview_sheet') else 'docx')
        return 200, {'id': jobs.start(body.get('job'), body.get('patient_id'), conn, fmt)}
    match = re.fullmatch(r'/api/jobs/([0-9a-f]+)', path)
    if method == 'GET' and match:
        result = jobs.get(match[1])
        if result and result['state'] == 'queued': result['state'] = 'running'
        return (200, result) if result else (404, {'error': 'job not found'})
    if method == 'GET' and path == '/api/run':
        patient_id = query.get('patient_id')
        if isinstance(patient_id, list):
            if len(patient_id) != 1: raise ValueError('invalid patient_id')
            patient_id = patient_id[0]
        if patient_id is not None:
            if not isinstance(patient_id, str) or not re.fullmatch(r'[1-9][0-9]*', patient_id): raise ValueError('invalid patient_id')
            patient_id = int(patient_id)
            if patient_id > 9223372036854775807: raise ValueError('invalid patient_id')
            if not conn.execute('SELECT 1 FROM patients WHERE id=?', (patient_id,)).fetchone(): return 404, {'error': 'patient not found'}
        return 200, {'tasks': recent_tasks(conn, patient_id),
                     'steps': [{'name': step.name, 'label': step.label, 'runs_in': step.runs_in, 'ai_off': steps.ai_off(step.name, conn)} for step in steps.STEPS if step.name not in ('intake_dry', 'intake_apply')]}
    if method == 'POST' and path == '/api/run' and isinstance(body, dict):
        names, ids = body.get('steps'), body.get('patient_ids')
        fmt = body.get('format', settings.get(conn, 'interview_export_format'))
        if fmt not in ('docx', 'pdf', 'both'): raise ValueError('invalid format')
        if names != 'auto':
            if not isinstance(names, list) or not names: raise ValueError('invalid steps')
            invalid = [n for n in names if not isinstance(n, str) or n not in steps.BY_NAME]
            if invalid: raise ValueError('invalid steps: ' + ', '.join(str(n) for n in invalid))
        if 'format' in body and names != 'auto' and not any(n in ('interview_pack', 'interview_sheet') for n in names): raise ValueError('invalid format')
        if ids == 'ready': ids = [r[0] for r in conn.execute('SELECT id FROM patients WHERE is_test=0 AND archived_at IS NULL ORDER BY id')]
        elif not isinstance(ids, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in ids): raise ValueError('invalid patient_ids')
        ids = list(dict.fromkeys(ids))
        if any(not conn.execute('SELECT 1 FROM patients WHERE id=?', (pid,)).fetchone() for pid in ids): raise ValueError('patient not found')
        added, skipped = [], []
        if names == 'auto':
            for pid in ids:
                patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
                for step in steps.FLOW:
                    if steps.ai_off(step.name, conn) or (step.name == 'report_assist' and not settings.get(conn, 'flow_includes_ai_assist')): continue
                    if step.done(conn, patient): continue
                    if step.name == 'pathology': patient = fill_referral_fields(conn, patient)
                    ok, reason = step.ready(conn, patient)
                    if not ok: skipped.append({'patient_id': pid, 'step': step.name, 'reason': reason})
                task_id = jobs.advance(conn, pid, fmt=fmt)
                if task_id: added.append(task_id)
                else: skipped.append({'patient_id': pid, 'step': 'auto', 'reason': 'no ready step or task already active'})
        else:
            for name in dict.fromkeys(names):
                step = steps.BY_NAME[name]
                batch = name in ('intake_dry', 'intake_apply', 'register_xlsx', 'sheet_sync', 'import_history', 'import_history_apply')
                for pid in [None] if batch else ids:
                    p = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone() if pid else None
                    if name == 'pathology': p = fill_referral_fields(conn, p)
                    ok, reason = step.ready(conn, p)
                    if name == 'sheet_sync': ok, reason = False, 'sheet sync job unavailable'
                    task_id = jobs.enqueue(conn, name, pid, fmt=fmt) if ok else None
                    if task_id: added.append(task_id)
                    else: skipped.append({'patient_id': pid, 'step': name, 'reason': reason if not ok else 'task already queued, running or waiting'})
        if added: jobs.ensure_worker()
        return 200, {'enqueued': added, 'skipped': skipped}
    match = re.fullmatch(r'/api/run/([0-9a-f]+)/(cancel|result)', path)
    if method == 'POST' and match:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (match[1],)).fetchone()
        if not row: return 404, {'error': 'task not found'}
        if match[2] == 'cancel':
            if row['state'] not in ('queued', 'waiting'): raise ValueError('only queued or waiting tasks can be cancelled')
            changed = conn.execute("UPDATE tasks SET state='cancelled',finished=? WHERE id=? AND state IN ('queued','waiting')", (db.now(), row['id'])).rowcount
            conn.commit()
            if not changed: raise ValueError('only queued or waiting tasks can be cancelled')
            return 200, {'ok': True}
        if row['state'] == 'done' and row['step'] == 'pathology' and row['output'] == 'No pathology reports in My Health Record': return 200, {'ok': True}
        if row['state'] != 'waiting': raise ValueError('task is not waiting')
        if not isinstance(body, dict) or body.get('state') not in ('done', 'failed') or not isinstance(body.get('output', ''), str): raise ValueError('invalid result')
        import interview
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (row['patient_id'],)).fetchone() if row['step'] == 'interactions' and body['state'] == 'done' else None
        with interview.record_lock(patient) if patient else nullcontext():
            if row['step'] == 'interactions' and body['state'] == 'done':
                if patient: steps.ingest_generated(conn, patient, body.get('mims_result'))
                if not patient or not steps.interactions_result_current(conn, patient, body.get('mims_result')):
                    body = {**body, 'state': 'failed', 'output': 'Medicine list changed or result could not be verified; run the interaction check again.'}
            if row['step'] == 'pathology' and body.get('output', '').strip().lower() == 'no report to read':
                body = {**body, 'state': 'done', 'output': 'No pathology reports in My Health Record'}
                db.log(conn, row['patient_id'], 'pathology_result', {'status': 'no report to read', 'saved': []}, 'app')
            changed = conn.execute("UPDATE tasks SET state=?,output=?,finished=? WHERE id=? AND state='waiting'", (body['state'], '\n'.join(body.get('output', '').splitlines()[-200:]), db.now(), row['id'])).rowcount
            conn.commit()
        if not changed: raise ValueError('task is not waiting')
        if row['flow'] and body['state'] == 'done':
            index = next(i for i, step in enumerate(steps.FLOW) if step.name == row['step'])
            jobs.advance(conn, row['patient_id'], index, row['format'])
        return 200, {'ok': True, 'state': body['state'], 'output': body.get('output', '')}
    if method == 'GET' and path == '/api/intake':
        return 200, {'rows': jobs.intake_rows()}
    if method == 'POST' and path == '/api/referrals/review':
        import referral_entry
        return 200, referral_entry.review(conn, body.get('paths') if isinstance(body, dict) else None)
    if method == 'POST' and path == '/api/referrals/commit':
        import referral_entry
        return 200, referral_entry.commit(conn, body.get('token'), body.get('fields'),
                                         body.get('distinct_person', False),
                                         body.get('manual_referral', False),
                                         clinical=body.get('clinical'))
    if method == 'POST' and path == '/api/intake/correction' and isinstance(body, dict):
        jobs.correction(body.get('file'), body.get('fields'))
        return 200, {'ok': True}
    return None
