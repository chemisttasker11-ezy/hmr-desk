"""Pathology work-queue routes: patients waiting for a pathology search and the recorded result of that search.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import os

import db
import jobs
import steps
from patient_actions import anydate, folder


def handle(conn, method, path, query, body):
    if method == 'GET' and path == '/api/pathology/queue':
        result = []
        for p in conn.execute("SELECT * FROM patients WHERE archived_at IS NULL AND state IN ('confirmed','pathology_ready','sheet_ready') AND COALESCE(has_pathology,0)=0 AND folder IS NOT NULL AND folder!=''"):
            if steps.done('pathology', conn, p): continue
            dob = p['dob'] or ''
            try: dob = anydate(dob).strftime('%d-%b-%Y')
            except ValueError: pass
            result.append({'id': p['id'], 'folder': os.path.basename(folder(p)), 'folder_path': folder(p), 'last': p['name'].split()[-1], 'dob': dob, 'sex': p['sex'], 'medicare': p['medicare'], 'irn': p['irn'], 'ihi': p['ihi']})
        return 200, {'patients': result}
    if method == 'POST' and path == '/api/pathology/result' and isinstance(body, dict):
        if not isinstance(body.get('id'), int) or isinstance(body.get('id'), bool): raise ValueError('invalid id')
        if body.get('irn') is not None and not isinstance(body['irn'], str): raise ValueError('invalid irn')
        p = conn.execute('SELECT * FROM patients WHERE id=?', (body['id'],)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if not isinstance(body.get('saved'), list) or not isinstance(body.get('status'), str): raise ValueError('invalid result')
        if body['saved']:
            db.set_state(conn, p['id'], 'sheet_ready' if p['state'] == 'sheet_ready' else 'pathology_ready', source='app')
            conn.execute('UPDATE patients SET has_pathology=1,irn=COALESCE(?,irn),updated_at=? WHERE id=?', (body.get('irn'), db.now(), p['id']))
        db.log(conn, p['id'], 'pathology_result', body, 'app')
        waiting = None
        if body['status'] == 'no report to read' and not body['saved']:
            waiting = conn.execute("SELECT * FROM tasks WHERE patient_id=? AND step='pathology' AND state='waiting'", (p['id'],)).fetchone()
            if waiting:
                conn.execute("UPDATE tasks SET state='done',output=?,finished=? WHERE id=? AND state='waiting'", ('No pathology reports in My Health Record', db.now(), waiting['id']))
        conn.commit()
        if waiting and waiting['flow']:
            jobs.advance(conn, p['id'], 0, waiting['format'])
        return 200, {'ok': True}
    return None
