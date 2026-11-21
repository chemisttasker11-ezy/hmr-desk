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
import helper_status, steps
import app_paths
import manual_medicine_names
import claims_data
import routes_clinical_records
import routes_followup
import routes_patients
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
    return claims_data.claim_list(conn, claims_helper, record, report_data, consent_evidence)

from followup_schedule import (LEGACY_FIRST_DAYS, LEGACY_END_DAYS, RULE_SOURCE, add_months, claim_deadline, followup_overrides,  # noqa: F401  re-exported
                               followups, meta, patient_followups, second_followup_due)



def _next_step(p, conn=None):
    import lifecycle
    return lifecycle.workflow_step(p, conn)


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
            return 200, helper_status.respond('mims', 'lists', mims_lists(conn), MIMS_PATH.is_file())
        if method == 'GET' and path == '/api/claims':
            return 200, helper_status.respond('ppa', 'claims', claim_list(conn), bool(claims_helper and record))
        routed = routes_patients.handle_list(conn, method, path, query, body)
        if routed is not None: return routed
        routed = routes_reference.handle(conn, method, path, query, body)
        if routed is not None: return routed
        for module in (routes_report, routes_clinical_records):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        for module in (routes_followup, routes_medicines):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        routed = routes_patients.handle_detail(conn, method, path, query, body)
        if routed is not None: return routed
        for module in (routes_schedule, routes_pathology):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        return 404, {'error': 'not found'}
    except (ValueError, TypeError) as exc:
        conn.rollback()
        return 400, {'error': str(exc)}
