"""Report routes: refresh, demographic resolution, load and save, consent preview and signing, report versions.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import records


def handle(conn, method, path, query, body):
    match = re.fullmatch(r'/api/patients/(\d+)/report/refresh', path)
    if method == 'POST' and match:
        import report
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        replace = body.get('replace_demographics', []) if isinstance(body, dict) else []
        try: result = report.refresh(conn, p, replace)
        except ValueError as exc: conn.rollback(); return 400, {'error': str(exc)}
        conn.commit(); return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/report/held-actions', path)
    if method == 'POST' and match:
        import report
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if not isinstance(body, dict) or set(body) != {'id', 'action'} or body['action'] != 'resolve' or not isinstance(body['id'], str): return 400, {'error': 'invalid body'}
        try: return 200, report.resolve_held_action(conn, p, body['id'])
        except ValueError as exc: conn.rollback(); return 400, {'error': str(exc)}
    match = re.fullmatch(r'/api/patients/(\d+)/report/demographics', path)
    if method == 'POST' and match:
        import report
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if not isinstance(body, dict) or set(body) != {'action', 'keys'}: return 400, {'error': 'invalid body'}
        try: return 200, report.resolve_demographics(conn, p, body['action'], body['keys'])
        except ValueError as exc: conn.rollback(); return 400, {'error': str(exc)}
    match = re.fullmatch(r'/api/patients/(\d+)/report', path)
    if match:
        import report
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET':
            ai = query.get('ai', '')
            return 200, report.load(conn, p, (ai[0] if isinstance(ai, list) and ai else ai) == '1')
        if method == 'POST':
            try: result = report.save(conn, p, body)
            except records.Conflict:
                conn.rollback(); return 409, {'error': 'report changed since it was read; reload before saving', 'revision': records.revision(conn, p['id'], 'report_spec.json')}
            conn.commit(); return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/consent/(preview|sign)', path)
    if match:
        import consent_sign
        import interview
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET' and match[2] == 'preview': return 200, consent_sign.preview(conn, p)
        if method == 'POST' and match[2] == 'sign':
            if not isinstance(body, dict) or set(body) != {'png', 'revision'}: raise ValueError('invalid body')
            try: result = consent_sign.sign(conn, p, body['png'], body['revision'])
            except interview.Conflict:
                conn.rollback(); return 409, {'error': 'interview conflict'}
            return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/report-versions', path)
    if match and method == 'GET':
        import report_auth
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        return 200, {'versions': report_auth.generated_versions(conn, p)}
    match = re.fullmatch(r'/api/patients/(\d+)/report-status', path)
    if match and method == 'GET':
        import report_status
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        return 200, report_status.report_status(conn, p)
    return None
