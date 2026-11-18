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
import routes_pathology
import routes_report
import routes_schedule
import routes_system
import routes_work
from routes_work import fill_referral_fields, recent_tasks  # re-exported: tests and callers use api.<name>



def helper(filename, stop):
    path = app_paths.resource_root() / filename
    if not path.is_file(): return None
    spec = importlib.util.spec_from_file_location('hmr_' + path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    tree.body = tree.body[:next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign) and any(isinstance(t, (ast.Name, ast.Tuple)) and (getattr(t, 'id', None) in stop or any(getattr(e, 'id', None) in stop for e in getattr(t, 'elts', []))) for t in node.targets))]
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


MIMS_PATH = app_paths.resource_root() / 'MIMS Interaction Helper' / 'make-lists.py'
claims_helper = helper('PPA Claim Helper/make-claims.py', {'claims'})
mims = helper('MIMS Interaction Helper/make-lists.py', {'lists'}) or manual_medicine_names
# External portal scripts are optional. A missing proprietary/unsupported
# helper must NEVER stop the entirely manual, offline clinical HMR application.
_record_path = app_paths.resource_root() / 'PPA Claim Helper' / 'record_report.py'
record = None
if _record_path.is_file():
    _record_spec = importlib.util.spec_from_file_location('hmr_record', _record_path)
    record = importlib.util.module_from_spec(_record_spec)
    _record_spec.loader.exec_module(record)


def report_data(conn, p):
    try:
        return records.get_json(conn, p['id'], 'report_spec.json')
    except ValueError:
        return None


def proposal(conn, p):
    saved = records.get_json(conn, p['id'], 'interview.json')
    if saved is not None:
        import interview
        data = saved; interview.validate(data)
        meds = []
        for key, actual in (('meds', 2), ('other_meds', 1)):
            rows = data.get(key, []); meta = data.get('details', {}).get(key, [{} for _ in rows])
            for row, detail in zip(rows, meta):
                status = detail.get('use_status', '')
                if row[0].strip() and (status == 'taking' or (not status and row[actual].strip())): meds.append([row[0], ''])
        usage = interview_usage(conn, p)
        stopped = {name for item in usage if item['status'] == 'not_using' for name in mims.ingredients(item['name'])}
        taking = {name for item in usage if item['status'] == 'taking' for name in mims.ingredients(item['name'])}
        meds = [row for row in meds if not stopped.intersection(mims.ingredients(row[0])) or set(mims.ingredients(row[0])) <= taking]
        return {'meds': meds, 'allergies': [x.strip() for x in data['allergies'].splitlines() if x.strip()], 'proposed': True}
    path = jobs.interview_spec_path(p)
    stored_spec = records.get_json(conn, p['id'], 'interview_spec.json')
    spec = stored_spec if stored_spec is not None else (json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {})
    meds = []
    for row in spec.get('meds', []):
        text = row[0] if isinstance(row, list) and row else row
        if not isinstance(text, str) or mims.SKIP.match(text.strip()): continue
        for name in mims.ingredients(text):
            if name not in [r[0] for r in meds]: meds.append([name, mims.brand(text) or ''])
    usage = interview_usage(conn, p)
    stopped = {name for item in usage if item['status'] == 'not_using' for name in mims.ingredients(item['name'])}
    taking = {name for item in usage if item['status'] == 'taking' for name in mims.ingredients(item['name'])}
    meds = [row for row in meds if row[0] not in stopped or row[0] in taking]
    allergy = spec.get('allergies', '')
    allergies = [item for text in allergy for item in mims.allergies(text) if isinstance(text, str)] if isinstance(allergy, list) else mims.allergies(allergy)
    return {'meds': meds, 'allergies': allergies, 'proposed': True}


def interview_usage(conn, p):
    data = records.get_json(conn, p['id'], 'interview.json')
    if data is None: return []
    import interview
    interview.validate(data)
    result = []
    details = data.get('details', {})
    for key in ('meds', 'other_meds'):
        for row, meta in zip(data.get(key, []), details.get(key, [])):
            if meta.get('use_status'):
                result.append({'name': row[0], 'status': meta['use_status'], 'detail': interview.use_text(meta), 'source': 'Referral medicine' if key == 'meds' else 'Found during interview', 'directions': row[1:3]})
    return result

def conflicting_medicines(conn, p, meds):
    stopped = {name for item in interview_usage(conn, p) if item['status'] == 'not_using' for name in mims.ingredients(item['name'])}
    return [row[0] for row in meds if stopped.intersection(mims.ingredients(row[0]))]

def relevant_usage(usage, meds):
    names = {name for row in meds for name in mims.ingredients(row[0])}
    return [item for item in usage if names.intersection(mims.ingredients(item['name']))]

def valid_alternatives(meds, usage, alternatives):
    stopped = [item for item in usage if item['status'] == 'not_using']
    if not isinstance(alternatives, list) or len(alternatives) != len(meds): return False
    def normal(value): return re.sub(r'[^a-z0-9]+', '', value.casefold())
    for row, choice in zip(meds, alternatives):
        names = set(mims.ingredients(row[0]))
        overlap = {name for item in stopped for name in mims.ingredients(item['name']) if name in names}
        if not overlap: continue
        if not isinstance(choice, dict) or choice not in usage or choice.get('status') != 'taking' or not overlap <= set(mims.ingredients(choice['name'])): return False
        # The exact recorded taking product must be selected; ingredient overlap alone is ambiguous.
        if normal(row[0]) != normal(choice['name']) or any(normal(choice['name']) == normal(item['name']) for item in stopped): return False
    return True

def same_name_as_stopped(meds, usage):
    """Listed medicines whose name equals a medicine recorded as not using in the interview. No alternative can resolve these."""
    def normal(value): return re.sub(r'[^a-z0-9]+', '', value.casefold())
    stopped = {normal(item['name']) for item in usage if item['status'] == 'not_using'}
    return [row[0] for row in meds if normal(row[0]) in stopped]


def current_medicine_snapshot(conn, p):
    data = records.get_json(conn, p['id'], 'interview.json')
    if data is None: return None
    import interview
    interview.validate(data)
    return medicine_snapshot.snapshot(data)


def confirmed_medicines_current(conn, p):
    data = records.get_json(conn, p['id'], 'confirmed_meds.json')
    if data is None: return False
    try:
        current_snapshot = current_medicine_snapshot(conn, p)
        if 'medicine_snapshot_sha256' in data:
            if current_snapshot is None or medicine_snapshot.digest(current_snapshot) != data['medicine_snapshot_sha256']: return False
        elif current_snapshot is not None and 'confirmed_at' in data:
            return False  # a real confirmation (always timestamped) made before any interview existed was never reviewed against these interview medicines
        meds = data['meds']
        if not isinstance(meds, list) or any(not isinstance(row, list) or len(row) != 2 or any(not isinstance(value, str) for value in row) for row in meds): return False
        current = relevant_usage(interview_usage(conn, p), meds)
        previous = data.get('interview_usage')
        if (previous is not None and previous != current) or (previous is None and any(item['status'] == 'not_using' for item in current)): return False
        return not any(item['status'] == 'not_using' for item in current) or valid_alternatives(meds, current, data.get('alternatives'))
    except (ValueError, KeyError, TypeError): return False

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
        if path == '/api/messages/board' and method == 'GET': return 200, messaging.board(conn)
        if path == '/api/messages/check' and method == 'POST': return 200, messaging.check_now(conn)
        match = re.fullmatch(r'/api/patients/(\d+)/messages', path)
        if match and method == 'POST':
            patient = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not patient: return 404, {'error': 'patient not found'}
            return 200, messaging.draft(conn, patient, body)
        match = re.fullmatch(r'/api/messages/([^/]+)/(approve|discard|resolve)', path)
        if match and method == 'POST':
            row = conn.execute('SELECT * FROM messages WHERE id=?', (match[1],)).fetchone()
            if not row: return 404, {'error': 'message not found'}
            if match[2] == 'resolve': return 200, inbox.resolve(conn, row, body)
            return 200, messaging.approve(conn, row, body) if match[2] == 'approve' else messaging.discard(conn, row)
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
        if path in ('/api/reference/local', '/api/reference/search', '/api/reference/open'):
            import reference_library
            try:
                if path == '/api/reference/local' and method == 'POST': return 200, reference_library.register(body)
                if path == '/api/reference/local' and method == 'GET': return 200, reference_library.public(reference_library.current())
                if path == '/api/reference/search' and method == 'GET':
                    q = (query.get('q') or [''])[0]
                    try:
                        return 200, reference_library.search(q)
                    except reference_library.ReferenceUnavailable:
                        # Packaged tier: serve the reviewed packaged tables, explicitly
                        # labelled as unverified extraction - never as the user's own PDF.
                        import brainstorm_tables_lookup
                        try:
                            return 200, brainstorm_tables_lookup.search(q)
                        except brainstorm_tables_lookup.TablesUnavailable as tables_exc:
                            if 'too long' in str(tables_exc):
                                raise reference_library.ReferenceUnavailable(str(tables_exc)) from None
                            # No usable PDF and no intact packaged tables: the same
                            # user-facing state as before packaged tables existed.
                            raise reference_library.ReferenceUnavailable('Local reference unavailable; choose the original PDF') from None
                if path == '/api/reference/open' and method == 'POST' and isinstance(body,dict) and set(body)=={'pdf_sha256','page'}:
                    return 200, reference_library.open_source(body['pdf_sha256'],body['page'])
            except reference_library.ReferenceUnavailable as exc: return 409, {'error':str(exc)}
            return 400, {'error':'Invalid local reference request'}
        if method == 'GET' and path == '/api/library':
            import report
            q = query.get('q', '')
            return 200, {'results': report.library(q[0] if isinstance(q, list) and q else q)}
        match = re.fullmatch(r'/api/patients/(\d+)/reference-matches', path)
        if method == 'GET' and match:
            import reference_matches, reference_library
            patient=conn.execute('SELECT * FROM patients WHERE id=?',(int(match[1]),)).fetchone()
            if not patient: return 404, {'error':'patient not found'}
            try: return 200, reference_matches.for_patient(conn,patient)
            except reference_library.ReferenceUnavailable as exc:
                return 409, {'error':str(exc),'matches':[], 'review_status':'reference_unavailable'}
        match = re.fullmatch(r'/api/patients/(\d+)/candidate-checks', path)
        if method == 'GET' and match:
            import candidate_checks
            patient=conn.execute('SELECT * FROM patients WHERE id=?',(int(match[1]),)).fetchone()
            if not patient: return 404, {'error':'patient not found'}
            try: return 200, candidate_checks.for_patient(conn,patient)
            except ValueError as exc:
                return 409, {'error':str(exc),'observations':[], 'review_status':'checks_unavailable'}
        match = re.fullmatch(r'/api/patients/(\d+)/suggestions(?:/context)?', path)
        if method == 'GET' and match:
            import suggest
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            context = suggest.context_for(conn, p)
            if path.endswith('/context'):
                return 200, {'context_snapshot_sha256': context['context_snapshot_sha256']}
            try:
                suggestions = suggest.suggest(context)
            except suggest.LibraryUnavailable:
                return 503, {'error': 'Offline suggestions unavailable: the reviewed reference library is not installed or cannot be read. Current interview evidence is retained; no suggestions were generated.'}
            return 200, {'suggestions': suggestions, 'context_gaps': suggest.context_gaps(context),
                         'context_snapshot_sha256': context['context_snapshot_sha256']}
        for module in (routes_report, routes_clinical_records):
            routed = module.handle(conn, method, path, query, body)
            if routed is not None: return routed
        match = re.fullmatch(r'/api/patients/(\d+)/(timeline|followup/([12])(/export)?)', path)
        if match:
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if match[2] == 'timeline' and method == 'GET':
                import timeline
                return 200, timeline.build(conn, p)
            if match[3]:
                import followup
                number = int(match[3])
                if method == 'GET' and not match[4]:
                    record = followup.load(conn, p, number)
                    return 200, {**record, 'review_issues': followup.review_issues(record)}
                if method == 'POST' and match[4]: return 200, {'file': followup.export(conn, p, number)}
                if method == 'POST':
                    followup.validate(body)
                    if body['date']: date(body['date'])
                    before = records.get_json(conn, p['id'], f'followup{number}.json')
                    result = followup.save(conn, p, number, body)
                    claimed = conn.execute("SELECT claimed FROM visits WHERE patient_id=? AND kind=? AND claimed IS NOT NULL LIMIT 1", (p['id'], 'followup' + str(number))).fetchone()
                    if claimed and before is not None and followup.normalize(before) != followup.normalize(body):
                        db.log(conn, p['id'], 'followup_record_changed_after_claim', {'kind': 'followup' + str(number)}, 'app')
                        result = {**result, 'changed_after_claim': True, 'review_issues': followup.review_issues(result)}
                    if body['date'] and not conn.execute("SELECT 1 FROM visits WHERE patient_id=? AND kind=? AND visit_date IS NOT NULL", (p['id'], 'followup' + str(number))).fetchone():
                        action(conn, p, {'action': 'followup_done', 'kind': 'followup' + str(number), 'date': body['date']})
                    return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/meds', path)
        if match:
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if method == 'GET':
                result = records.get_json(conn, p['id'], 'confirmed_meds.json') or proposal(conn, p)
                usage = interview_usage(conn, p)
                result['interview_usage'] = usage
                snapshot = current_medicine_snapshot(conn, p)
                current_digest = medicine_snapshot.digest(snapshot) if snapshot is not None else 'missing'
                result['medicine_snapshot_changed'] = (('medicine_snapshot_sha256' in result and result['medicine_snapshot_sha256'] != current_digest)
                                                       or ('medicine_snapshot_sha256' not in result and 'confirmed_at' in result and snapshot is not None))
                result['medicine_snapshot'] = snapshot
                result['medicine_snapshot_sha256'] = medicine_snapshot.digest(snapshot) if snapshot is not None else 'missing'
                return 200, result
            if method == 'POST':
                import interview
                with interview.record_lock(p):
                    if not isinstance(body, dict) or set(body) - {'medicine_snapshot_sha256'} not in ({'meds', 'allergies'}, {'meds', 'allergies', 'interview_usage'}, {'meds', 'allergies', 'interview_usage', 'alternatives'}): raise ValueError('invalid medicine list')
                    current_snapshot = current_medicine_snapshot(conn, p)
                    current_digest = medicine_snapshot.digest(current_snapshot) if current_snapshot is not None else 'missing'
                    if 'medicine_snapshot_sha256' in body and body['medicine_snapshot_sha256'] != current_digest: raise ValueError('Interview medicines or allergies changed; reload and review before confirming')
                    if current_snapshot is not None and any(item['item_id'] for item in current_snapshot['items']) and 'medicine_snapshot_sha256' not in body: raise ValueError('Reload and review the current medicine snapshot before confirming')
                    meds, allergies = body['meds'], body['allergies']
                    if not isinstance(meds, list) or len(meds) > 60 or any(not isinstance(row, list) or len(row) != 2 or any(not isinstance(x, str) for x in row) or not row[0].strip() for row in meds): raise ValueError('invalid medicines')
                    usage = interview_usage(conn, p)
                    relevant = relevant_usage(usage, meds)
                    snapshot = body.get('interview_usage')
                    if relevant and snapshot is None: raise ValueError('Review and reconcile interview medicine use before confirming')
                    if snapshot is not None and (not isinstance(snapshot, list) or any(not isinstance(item, dict) or not isinstance(item.get('name'), str) for item in snapshot) or relevant_usage(snapshot, meds) != relevant): raise ValueError('Interview medicine use changed; review before confirming')
                    alternatives = body.get('alternatives', [None] * len(meds))
                    if not valid_alternatives(meds, relevant, alternatives):
                        if same_name_as_stopped(meds, relevant): raise ValueError('A listed medicine has the same name as one recorded as not using in the interview. Remove it from the list, or correct its use in the interview.')
                        raise ValueError('Select the medicine actually taking for each stopped overlap')
                    if not isinstance(allergies, list) or len(allergies) > 60 or any(not isinstance(x, str) for x in allergies): raise ValueError('invalid allergies')
                    data = {'meds': meds, 'allergies': allergies, 'confirmed_at': db.now(), 'interview_usage': relevant, 'alternatives': alternatives}
                    if current_snapshot is not None:
                        data.update(medicine_snapshot=current_snapshot, medicine_snapshot_sha256=current_digest)
                    records.put_json(conn, p['id'], 'confirmed_meds.json', data)
                    db.log(conn, p['id'], 'meds_confirmed', {}, 'api'); conn.commit()
                    return 200, data
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
