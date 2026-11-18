"""Patient status, list, detail and action routes.

Moved verbatim from api.handle. handle_list covers /api/status and the patient list; handle_detail covers
/api/patients/<id> and /api/patients/<id>/action. Each returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import followup_schedule
import lifecycle
import steps
from followup_schedule import meta, patient_followups
from patient_actions import action, files, folder, referral_expiry, undo_event
from routes_work import recent_tasks


def _next_step(p, conn):
    return lifecycle.next_step(conn, p)


def handle_list(conn, method, path, query, body):
    if method == 'GET' and path == '/api/status':
        return 200, {'patients': dict(conn.execute('SELECT state,count(*) FROM patients WHERE is_test=0 GROUP BY state')),
                     'messages': dict(conn.execute('SELECT m.state,count(*) FROM messages m LEFT JOIN patients p ON p.id=m.patient_id WHERE COALESCE(p.is_test,0)=0 GROUP BY m.state')),
                     'outbox_mode': meta(conn, 'outbox_mode', 'test'), 'gateway_online': {'true': True, 'false': False}.get(meta(conn, 'gateway_online', '')),
                     'sending_window': meta(conn, 'sending_window', 'on')}
    if method == 'GET' and path == '/api/patients':
        state = query.get('state', '')
        q = query.get('q', '')
        state = state[0] if isinstance(state, list) and state else state
        q = q[0] if isinstance(q, list) and q else q
        archived = query.get('archived', '')
        archived = archived[0] if isinstance(archived, list) and archived else archived
        q = q.strip()
        rows = conn.execute("SELECT * FROM patients WHERE is_test=0 AND (? OR archived_at IS NULL) AND (?='' OR state=?) AND (?='' OR name LIKE ? OR suburb LIKE ? OR gp LIKE ? OR phone LIKE ?) ORDER BY name", (archived == '1' or bool(q),state,state,q,*(['%'+q+'%']*4)))
        patients = []
        for p in rows:
            follow = patient_followups(conn, p['id'])
            expiry = referral_expiry(conn, p['referral_date'])
            life = lifecycle.stage(conn, p)
            patients.append({**{k: p[k] for k in ('id','key','name','suburb','gp','phone','state','status_text','visit_date','visit_time','folder','has_pathology','has_sheet','referral_date')}, 'archived': bool(p['archived_at']), 'stage': life['stage'], 'stage_step': life['step'], 'flags': lifecycle.flags(conn, p), 'referral_expiry': expiry.isoformat() if expiry else None, 'next_step': 'follow-up due' if follow and follow['due'] else _next_step(p, conn)})
        return 200, {'patients': patients}
    return None


def handle_detail(conn, method, path, query, body):
    match = re.fullmatch(r'/api/patients/(\d+)(/action)?', path)
    if match:
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p:
            return 404, {'error': 'patient not found'}
        if method == 'GET' and not match[2]:
            result = dict(p)
            life = lifecycle.stage(conn, p)
            undo = undo_event(conn, p)
            labels = {'visited': 'Visit recorded', 'report_drafted': 'Report drafted', 'signed_off': 'Signed off', 'sent': 'Report sent', 'claimed': 'Claimed'}
            result.update(stage=life['stage'], stage_step=life['step'], flags=lifecycle.flags(conn, p),
                          folder_check=lifecycle.folder_check(p), can_undo=bool(undo),
                          undo_label='Undo: ' + labels[undo['to']] if undo else '')
            result['suggested_kind'] = 'change' if p['visit_date'] and p['visit_time'] else 'offer'
            result['change_kinds'] = ['change_request', 'change'] if p['visit_date'] and p['visit_time'] else []
            expiry = referral_expiry(conn, p['referral_date'])
            result['referral_expiry'] = expiry.isoformat() if expiry else None
            result.update(events=[dict(x) for x in conn.execute('SELECT * FROM events WHERE patient_id=? ORDER BY id DESC', (p['id'],))],
                          messages=[dict(x) for x in conn.execute('SELECT * FROM messages WHERE patient_id=? ORDER BY created_at DESC', (p['id'],))],
                          files=files(folder(p)), followups=patient_followups(conn, p['id']),
                          visits=[dict(x) for x in conn.execute('SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date IS NULL,visit_date DESC,id DESC', (p['id'],))])
            result['tasks'] = recent_tasks(conn, p['id'], 30)
            result['steps'] = []   # per-step readiness, so the app can disable a button and say why
            for step in steps.FLOW + [steps.BY_NAME['interview_assist'], steps.BY_NAME['report_draft']]:
                ok, reason = step.ready(conn, p)
                result['steps'].append({'name': step.name, 'runs_in': step.runs_in, 'ready': bool(ok),
                                        'reason': reason or '', 'done': bool(step.done(conn, p)), 'ai_off': steps.ai_off(step.name, conn)})
            return 200, result
        if method == 'POST' and match[2] and isinstance(body, dict):
            return 200, action(conn, p, body)
    return None
