"""Local JSON API; all mutations are recorded in the engine database."""
import ast
import builtins
import io
import hashlib
import types
import importlib.util
from pathlib import Path
import calendar
from contextlib import nullcontext
import datetime as dt
import json
import os
import re

import db
import settings
import proda_sms
import inbox
import messaging
import jobs
import agents
import records
import medicine_reference
import medicine_snapshot
import steps
import app_paths
import manual_medicine_names
import routes_clinical_records
import routes_followup
import routes_medicines
import routes_messages
import routes_pathology
import routes_reference
import routes_report
import routes_schedule
import routes_system
import routes_work
from routes_work import fill_referral_fields, recent_tasks  # re-exported: tests and callers use api.<name>



import external_helpers
from external_helpers import helper, MIMS_PATH, claims_helper, mims, record  # noqa: F401  re-exported: tests and callers use api.<name>
import medicine_review
from medicine_review import (report_data, proposal, interview_usage, conflicting_medicines, relevant_usage, valid_alternatives,  # noqa: F401  re-exported
                             same_name_as_stopped, current_medicine_snapshot, confirmed_medicines_current)


def mims_lists(conn):
    if not MIMS_PATH.is_file(): return []  # licensed portal integration unavailable
    result = []
    for p in conn.execute("SELECT * FROM patients WHERE archived_at IS NULL AND state IN ('visited','report_drafted') ORDER BY name"):
        folder = jobs.patient_folder(p)
        if steps.interactions_done(conn, p): continue
        confirmed_bytes = records.get(conn, p['id'], 'confirmed_meds.json')
        if confirmed_bytes is not None:
            data = json.loads(confirmed_bytes)
            if not confirmed_medicines_current(conn, p): raise ValueError('Medicine use changed or needs reconciliation; review and confirm medicines before running interactions for ' + p['name'])
            names = []
            for generic, brand in data['meds']:
                for name in mims.ingredients(generic):
                    if name not in [x[0] for x in names]:
                        names.append([name] + list(dict.fromkeys(a for a in [brand.lower().strip()] + mims.ALIASES.get(name, []) if a and a != name)))
            entry = {'meds': [x if len(x) > 1 else x[0] for x in names], 'allergies': data['allergies'], 'meds_revision': hashlib.sha256(confirmed_bytes).hexdigest()}
        else:
            spec = report_data(conn, p)
            if spec is None: continue
            candidates = [[row[0] if isinstance(row, list) else row, ''] for row in spec.get('meds', []) + spec.get('otc', []) if row]
            if conflicting_medicines(conn, p, candidates): raise ValueError('Medicine use changed to not using; review medicines before running interactions for ' + p['name'])
            names = []
            for row in spec.get('meds', []) + spec.get('otc', []):
                text = row[0] if isinstance(row, list) else row
                if text and not mims.SKIP.match(text.strip()):
                    for name in mims.ingredients(text):
                        if name not in [x[0] for x in names]: names.append([name] + [a for a in [mims.brand(text)] + mims.ALIASES.get(name, []) if a and a != name])
            entry = {'meds': [x if len(x) > 1 else x[0] for x in names], 'allergies': mims.allergies(spec.get('allergies', ''))}
        entry.update(folder=str(folder), id=p['id'], folder_path=str(folder))
        result.append(entry)
    return result



def consent_evidence(conn, p):
    import consent_evidence as evidence
    return evidence.consent_evidence(conn, p)


def consent_held(conn, p):
    return consent_evidence(conn, p) != ''


def claim_list(conn):
    if claims_helper is None or record is None: return []  # PPA integration unavailable
    result = []
    for p in conn.execute("SELECT * FROM patients WHERE state='sent' AND is_test=0 AND archived_at IS NULL ORDER BY name"):
        spec = report_data(conn, p) or {}
        dates = {name: steps.event_date(conn, p, name) or '' for name in ('visited', 'report_sent')}
        given, family = claims_helper.split_name(p['name']); gp_given, gp_family = claims_helper.split_name(p['gp'])
        suburb = p['suburb'] or ''; match = re.match(r'(\d{4})\s+(.*)', suburb)
        provider = re.search(r'(?im)^\s*Provider No:\s*(.+)$', spec.get('doctor', ''))
        outcomes, other = record.outcomes(spec) if spec else ([], '')
        result.append({'given': given, 'family': family, 'dob': claims_helper.iso(p['dob']),
            'medicare': re.sub(r'\D', '', p['medicare'] or '') + re.sub(r'\D', '', p['irn'] or ''),
            'interview': claims_helper.iso(dates.get('visited')), 'reportSent': claims_helper.iso(dates.get('report_sent')),
            'referral': claims_helper.iso(p['referral_date']), 'gpProvider': provider.group(1).strip() if provider else '',
            'gpGiven': gp_given, 'gpFamily': gp_family, 'suburb': match.group(2) if match else suburb,
            'postcode': p['postcode'] or (match.group(1) if match else ''),
            'reasons': record.reasons(spec) if spec.get('reason') else [], 'consentHeld': consent_held(conn, p), 'consentEvidence': consent_evidence(conn, p), 'reasonOther': '', 'outcomes': outcomes, 'outcomeOther': other})
    return result

from followup_schedule import (LEGACY_FIRST_DAYS, LEGACY_END_DAYS, RULE_SOURCE, add_months, claim_deadline, followup_overrides,  # noqa: F401  re-exported
                               followups, meta, patient_followups, second_followup_due)



def _next_step(p, conn=None):
    state = p['state']
    if state in ('confirmed', 'pathology_ready', 'sheet_ready'):
        name = 'pathology' if not steps.done('pathology', conn, p) else 'interview_sheet' if not steps.done('interview_sheet', None, p) else None
        return steps.BY_NAME[name].label if name else 'visit'
    if state == 'visited':
        if not confirmed_medicines_current(conn, p): return 'confirm medicines'
        if report_data(conn, p) is not None: return 'build report' if report_data(conn, p).get('issues') else 'add findings'
        if not steps.interactions_done(conn, p): return 'check interactions'
        return 'start report'
    if state == 'sent': return steps.BY_NAME['claim'].label
    return {'new': steps.BY_NAME['intake_dry'].label, 'pooled': 'offer a time', 'offered': 'wait for reply', 'report_drafted': 'sign off', 'signed_off': 'send report'}.get(state, '')


def next_step(p, conn=None):
    import lifecycle
    return lifecycle.next_step(conn, p)


from patient_actions import (_action, action, anydate, clock, date, files, folder, move_patient_item, referral_expiry, undo_event)  # noqa: F401  re-exported








def approved_layout_available():
    try:
        import template_report_builder
        template_report_builder.approved_template(template_report_builder.active_template_root())
        return True
    except (FileNotFoundError, ValueError, OSError, KeyError, TypeError):
        return False


def handle(conn, method, path, query, body):
    try:
        if method == 'GET' and path == '/api/health':
            import pdf_export
            return 200, {'ready': True, 'engine_version': '0.1.0', 'schema_version': db.SCHEMA_VERSION,
                         'capabilities': {'manual_hmr': True, 'clinical_ai_optional': True,
                                          'mims_helper_available': MIMS_PATH.is_file(),
                                          'ppa_helper_available': bool(claims_helper and record),
                                          'pdf_converter_available': pdf_export.available(),
                                          'ocr_component_bundled': (app_paths.resource_root() / 'scripts' / 'intake' / 'ocr_pdf.ps1').is_file(),
                                          'approved_template_available': approved_layout_available()}}
        if method == 'POST' and path == '/api/auth/proda/start': return 200, proda_sms.start(settings.get(conn, 'proda_auto_sms_login'), body)
        if method == 'POST' and path == '/api/auth/proda/poll': return 200, proda_sms.poll(settings.get(conn, 'proda_auto_sms_login'), body)
        if method == 'POST' and path == '/api/auth/proda/finish': return 200, proda_sms.finish(body)
        import scenarios
        if path == '/api/test/patient' and method == 'POST': return 200, scenarios.patient(conn)
        if path == '/api/test/scenario' and method == 'POST': return 200, scenarios.start(conn, body)
        match = re.fullmatch(r'/api/test/scenario/([0-9a-f]+)', path)
        if match and method == 'GET':
            result = scenarios.report(conn, match[1])
            return (200, result) if result else (404, {'error': 'run not found'})
        routed = routes_messages.handle(conn, method, path, query, body)
        if routed is not None: return routed
        routed = routes_system.handle(conn, method, path, query, body)
        if routed is not None: return routed
        routed = routes_work.handle(conn, method, path, query, body)
        if routed is not None: return routed
        if method == 'GET' and path == '/api/mims/lists':
            return 200, {'lists': mims_lists(conn)}
        if method == 'GET' and path == '/api/claims':
            return 200, {'claims': claim_list(conn)}
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
                import lifecycle
                life = lifecycle.stage(conn, p)
                patients.append({**{k: p[k] for k in ('id','key','name','suburb','gp','phone','state','status_text','visit_date','visit_time','folder','has_pathology','has_sheet','referral_date')}, 'archived': bool(p['archived_at']), 'stage': life['stage'], 'stage_step': life['step'], 'flags': lifecycle.flags(conn, p), 'referral_expiry': expiry.isoformat() if expiry else None, 'next_step': 'follow-up due' if follow and follow['due'] else next_step(p, conn)})
            return 200, {'patients': patients}
        routed = routes_reference.handle(conn, method, path, query, body)
        if routed is not None: return routed
        for module in (routes_report, routes_clinical_records):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        for module in (routes_followup, routes_medicines):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        match = re.fullmatch(r'/api/patients/(\d+)(/action)?', path)
        if match:
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p:
                return 404, {'error': 'patient not found'}
            if method == 'GET' and not match[2]:
                import lifecycle
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
        for module in (routes_schedule, routes_pathology):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        return 404, {'error': 'not found'}
    except (ValueError, TypeError) as exc:
        conn.rollback()
        return 400, {'error': str(exc)}
