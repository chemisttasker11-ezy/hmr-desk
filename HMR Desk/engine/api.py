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
        if 'medicine_snapshot_sha256' in data:
            current_snapshot = current_medicine_snapshot(conn, p)
            if current_snapshot is None or medicine_snapshot.digest(current_snapshot) != data['medicine_snapshot_sha256']: return False
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
            'reasons': record.reasons(spec) if spec.get('reason') else [], 'reasonOther': '', 'outcomes': outcomes, 'outcomeOther': other})
    return result

def meta(conn, key, default):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def followups(visit, first=30, end=270, months=24, today=None):
    if not visit:
        return None
    day = dt.date.fromisoformat(visit[:10])
    n = day.month - 1 + int(months)
    year, month = day.year + n // 12, n % 12 + 1
    new = dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    start, finish = day + dt.timedelta(days=int(first)), day + dt.timedelta(days=int(end))
    today = today or dt.date.today()
    return {'visit_date': str(day), 'first_due': str(start), 'window_end': str(finish),
            'new_hmr': str(new), 'due': start <= today <= finish}


def patient_followups(conn, pid, today=None):
    row = conn.execute("SELECT * FROM visits WHERE patient_id=? AND kind='hmr' AND visit_date IS NOT NULL ORDER BY visit_date DESC,id DESC LIMIT 1", (pid,)).fetchone()
    if not row: return None
    today = today or dt.date.today()
    result = followups(row['visit_date'], meta(conn, 'followup_first_after_days', 30),
                       meta(conn, 'followup_window_end_days', 270), meta(conn, 'new_hmr_after_months', 24), today)
    done = list(conn.execute("SELECT kind,visit_date,claimed FROM visits WHERE patient_id=? AND kind IN ('followup1','followup2') AND visit_date>=? ORDER BY visit_date DESC,id DESC", (pid,row['visit_date'])))
    first = next((x for x in done if x['kind'] == 'followup1'), None)
    second = next((x for x in done if x['kind'] == 'followup2'), None)
    first_date = first['visit_date'] if first else None
    due2 = str(dt.date.fromisoformat(first_date) + dt.timedelta(days=int(meta(conn, 'followup_first_after_days', 30)))) if first else None
    alerts = []
    for number, visit in ((1, first), (2, second)):
        if visit and not visit['claimed']: alerts.append(f'follow-up {number} to claim')
    next_action = next_due = None
    if first and not first['claimed']: next_action = 'followup1_claimed'
    elif second and not second['claimed']: next_action = 'followup2_claimed'
    elif str(today) <= result['window_end']:
        if not first: next_action, next_due = 'followup1', result['first_due']
        elif not second: next_action, next_due = 'followup2', due2
    clinical_action, clinical_due = (('followup1', result['first_due']) if not first else ('followup2', due2) if not second else (None, None))
    if clinical_due and clinical_due <= str(today) <= result['window_end']:
        alerts.append('follow-up ' + clinical_action[-1] + ' due')
    if str(today) >= result['new_hmr']: alerts.append('new HMR possible')
    result.update(due=bool(alerts), alerts=alerts, followup1=first_date, followup2=bool(second),
                  followup1_claimed=first['claimed'] if first else None,
                  followup2_claimed=second['claimed'] if second else None,
                  next_action=next_action, next_due=next_due)
    return result


def _next_step(p, conn=None):
    state = p['state']
    if state in ('confirmed', 'pathology_ready', 'sheet_ready'):
        name = 'pathology' if not steps.done('pathology', conn, p) else 'interview_sheet' if not steps.done('interview_sheet', None, p) else None
        return steps.BY_NAME[name].label if name else 'visit'
    if state == 'visited':
        if report_data(conn, p) is not None: return 'build report' if report_data(conn, p).get('issues') else 'add findings'
        if not steps.exists(conn, p, 'confirmed_meds.json'): return 'confirm medicines'
        if not steps.interactions_done(conn, p): return 'check interactions'
        return 'start report'
    if state == 'sent': return steps.BY_NAME['claim'].label
    return {'new': steps.BY_NAME['intake_dry'].label, 'pooled': 'offer a time', 'offered': 'wait for reply', 'report_drafted': 'sign off', 'signed_off': 'send report'}.get(state, '')


def next_step(p, conn=None):
    import lifecycle
    return lifecycle.next_step(conn, p)


def folder(p):
    return os.path.abspath(os.path.join(db.BASE, p['folder'])) if p['folder'] else None


def move_patient_item(conn, p, destination, moved_items):
    source = folder(p)
    if not source:
        raise ValueError('patient folder missing')
    target_dir = os.path.join(db.BASE, 'Declined-Exp', destination)
    target = os.path.join(target_dir, os.path.basename(source))
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        return False
    if os.path.lexists(target):
        raise ValueError('target already exists')
    if not os.path.exists(source):
        raise ValueError('patient folder source missing: ' + source)
    try:
        os.makedirs(target_dir, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        raise ValueError('patient folder move failed: ' + str(exc)) from exc
    try:
        conn.execute('UPDATE patients SET folder=?,updated_at=? WHERE id=?',
                     (os.path.relpath(target, db.BASE), db.now(), p['id']))
    except Exception:
        os.rename(target, source)
        raise
    moved_items.append((source, target))
    return True


def files(path):
    def names(p):
        return sorted(x for x in os.listdir(p) if os.path.isfile(os.path.join(p, x))) if p and os.path.isdir(p) else []
    return {'folder': names(path), 'pathology': names(os.path.join(path, 'Pathology') if path else None)}


def date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid date')
    return dt.date.fromisoformat(value)


def anydate(value):
    """Stored referral dates and DOBs are DD/MM/YYYY (sometimes with a trailing note); newer ones may be ISO."""
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', value or '')
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else date((value or '')[:10])


def referral_expiry(conn, value):
    try:
        days = int(meta(conn, 'referral_valid_days', 90))
        if days <= 0: days = 90
        return anydate(value) + dt.timedelta(days=days)
    except (ValueError, TypeError, OverflowError):
        return None


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('invalid time')
    return dt.time.fromisoformat(value)



def undo_event(conn, p):
    event = conn.execute("SELECT * FROM events WHERE patient_id=? AND type='state' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
    if not event or event['source'] != 'app': return None
    try:
        age = dt.datetime.now() - dt.datetime.fromisoformat(event['ts'])
        detail = json.loads(event['detail'] or '{}')
        if (dt.timedelta(0) <= age < dt.timedelta(hours=24) and detail.get('to') == p['state']
                and detail.get('to') in ('visited', 'report_drafted', 'signed_off', 'sent', 'claimed')
                and detail.get('from') in db.STATES and detail['from'] != detail['to']):
            return detail
    except (ValueError, TypeError, AttributeError):
        pass
    return None

def action(conn, p, body):
    moved_items = []
    try:
        return _action(conn, p, body, moved_items)
    except Exception:
        conn.rollback()
        for source, target in reversed(moved_items):
            os.rename(target, source)
        raise


def _action(conn, p, body, moved_items):
    pid, name = p['id'], body.get('action')
    moved = False
    transitions = {'book_phone': 'confirmed', 'move': 'confirmed', 'decline_phone': 'declined', 'hold': 'hold',
                   'visited': 'visited', 'report_drafted': 'report_drafted', 'signed_off': 'signed_off',
                   'report_sent': 'sent', 'claimed': 'claimed', 'expired': 'expired'}
    if name in ('book_phone', 'move'):
        if name == 'move' and p['state'] not in ('confirmed', 'pathology_ready', 'sheet_ready'):
            raise ValueError('move needs a booked visit')
        date(body.get('date'))
        start, end = clock(body.get('time')), clock(body.get('end'))
        if start <= dt.time(8):
            raise ValueError('start must be after 08:00')
        if end <= start:
            raise ValueError('end must be after start')
    if name in ('visited', 'report_sent', 'claimed', 'followup_done', 'followup_claimed'):
        date(body.get('date'))
    if name in ('followup_done', 'followup_claimed') and body.get('kind') not in ('followup1', 'followup2'): raise ValueError('invalid follow-up kind')
    if name in transitions:
        target = p['state'] if name == 'move' and p['state'] in ('confirmed', 'pathology_ready', 'sheet_ready') else transitions[name]
        if name in ('decline_phone', 'hold', 'expired') and not isinstance(body.get('reason' if name == 'decline_phone' else 'note', ''), str):
            raise ValueError('reason or note must be a string')
        if name in ('decline_phone', 'expired'):
            if not db.can_move(p['state'], target):
                raise ValueError(f"{p['state']} -> {target} is not allowed")
            moved = move_patient_item(conn, p, 'Declined' if name == 'decline_phone' else 'Expired', moved_items)
        dated = {'visited': 'Visited', 'report_sent': 'Report sent', 'claimed': 'Claimed'}
        status = dated[name] + ' ' + dt.date.fromisoformat(body['date']).strftime('%d/%m/%Y') if name in dated else None
        if name == 'visited' and body.get('auto') is True: status += ' (auto)'
        authorisation = None
        if name == 'signed_off':
            import report_auth
            authorisation = report_auth.check_approval(conn, p, body)
        if name == 'report_sent':
            import report_auth
            report_auth.check_sent(conn, p)
        if name == 'signed_off' and p['state'] == 'visited' and steps.built(conn, p):
            db.set_state(conn, pid, 'report_drafted', source='app')
        db.set_state(conn, pid, target, status, source='app', force=name == 'book_phone' and p['state'] in ('new', 'pooled'))
        if name == 'visited':  # the list shows the real visit date, not the booked one
            conn.execute('UPDATE patients SET visit_date=?,updated_at=? WHERE id=?', (body['date'], db.now(), pid))
        if name in ('book_phone', 'move'):
            conn.execute('UPDATE patients SET visit_date=?,visit_time=?,visit_end=?,updated_at=? WHERE id=?',
                         (body['date'], body['time'], body['end'], db.now(), pid))
        if name == 'decline_phone':
            inbox.append_decline(p, dt.date.today(), 'Phone', body.get('reason', ''))
        if name in ('decline_phone', 'expired'):
            conn.execute('UPDATE patients SET offered_date=COALESCE(visit_date,offered_date),visit_date=NULL,visit_time=NULL,visit_end=NULL,visit_group=NULL WHERE id=?', (pid,))
        if name == 'expired' and 'note' in body:
            conn.execute('UPDATE patients SET note=?,updated_at=? WHERE id=?', (body['note'], db.now(), pid))
        if name == 'hold':
            conn.execute("UPDATE patients SET note=?,hold_from=CASE WHEN ? != 'hold' THEN ? ELSE hold_from END,updated_at=? WHERE id=?", (body.get('note', ''), p['state'], p['state'], db.now(), pid))
        if name in ('visited', 'report_sent', 'claimed'):
            row = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind='hmr' AND source='app' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
            if name == 'visited' and p['state'] != 'visited': row = None
            if not row:
                rowid = conn.execute("INSERT INTO visits(patient_id,kind,folder,source) VALUES (?,'hmr',?,'app')", (pid,p['folder'])).lastrowid
            else: rowid = row['id']
            field = {'visited':'visit_date','report_sent':'report_sent','claimed':'claimed'}[name]
            conn.execute('UPDATE visits SET '+field+'=? WHERE id=?', (body['date'],rowid))
        detail = {k: v for k, v in body.items() if k != 'action'}
        if authorisation is not None:
            detail = authorisation
        if name == 'visited': detail['prior_booking'] = {k: p[k] for k in ('visit_date','visit_time','visit_end','visit_group')}
        db.log(conn, pid, name, detail, 'app')
    elif name == 'pathology_outcome':
        if p['state'] not in (*steps.PRE, 'visited', 'report_drafted', 'signed_off'): raise ValueError('invalid patient state')
        outcome, note = body.get('outcome'), body.get('note', '')
        statuses = {'none': 'no report to read', 'access_code': 'access code needed', 'saved_by_hand': 'saved by hand'}
        if outcome not in statuses or not isinstance(note, str): raise ValueError('invalid pathology outcome')
        if outcome == 'saved_by_hand': conn.execute('UPDATE patients SET has_pathology=1,updated_at=? WHERE id=?', (db.now(), pid))
        db.log(conn, pid, 'pathology_result', {'status': statuses[outcome], 'note': note}, 'app')
        conn.execute("UPDATE tasks SET state=?,output=?,finished=? WHERE patient_id=? AND step='pathology' AND state IN ('queued','waiting')", ('cancelled' if outcome == 'access_code' else 'done', statuses[outcome], db.now(), pid))
    elif name == 'interactions_manual':
        if p['state'] not in ('visited', 'report_drafted', 'signed_off'): raise ValueError('invalid patient state')
        text = body.get('text')
        if not isinstance(text, str) or not 1 <= len(text) <= 20000 or not text.strip(): raise ValueError('invalid text')
        folder = jobs.patient_folder(p)
        today = dt.date.today()
        stem = 'MIMS interactions (manual) ' + today.isoformat()
        n = 1
        while records.exists(conn, pid, stem + (f' ({n})' if n > 1 else '') + '.txt'): n += 1
        rec_name = stem + (f' ({n})' if n > 1 else '') + '.txt'
        records.put(conn, pid, rec_name, ('Checked by hand by ' + settings.get(conn, 'pharmacist_name') + ' on ' + today.strftime('%d/%m/%Y') + '\n' + text).encode('utf-8'))
        db.log(conn, pid, name, {'file': rec_name}, 'app')
        conn.execute("UPDATE tasks SET state='done',output=?,finished=? WHERE patient_id=? AND step='interactions' AND state IN ('queued','waiting')", (rec_name, db.now(), pid))
    elif name in ('archive', 'unarchive'):
        if name == 'archive' and p['state'] not in ('claimed', 'declined', 'expired'):
            raise ValueError('Cannot archive this patient')
        if name == 'archive' and p['state'] == 'claimed' and patient_followups(conn, pid) and patient_followups(conn, pid)['next_action']:
            raise ValueError('Cannot archive while follow-up obligations are open')
        conn.execute('UPDATE patients SET archived_at=?,updated_at=? WHERE id=?', (db.now() if name == 'archive' else None, db.now(), pid))
        db.log(conn, pid, name, {}, 'app')
    elif name == 'resume':
        if p['state'] != 'hold': raise ValueError('Patient is not on hold')
        db.set_state(conn, pid, p['hold_from'] or 'pooled', source='app', force=True)
        conn.execute('UPDATE patients SET hold_from=NULL WHERE id=?', (pid,))
    elif name == 'undo_stage':
        event = undo_event(conn, p)
        if not event: raise ValueError('Nothing to undo')
        db.set_state(conn, pid, event['from'], source='app', force=True)
        field = {'visited': 'visit_date', 'sent': 'report_sent', 'claimed': 'claimed'}.get(event['to'])
        if field:
            conn.execute('UPDATE visits SET ' + field + "=NULL WHERE id=(SELECT id FROM visits WHERE patient_id=? AND source='app' ORDER BY id DESC LIMIT 1)", (pid,))
        if event['to'] == 'visited':
            prior = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='visited' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
            booking = json.loads(prior['detail'] or '{}').get('prior_booking', {}) if prior else {}
            if booking:
                conn.execute('UPDATE patients SET visit_date=?,visit_time=?,visit_end=?,visit_group=? WHERE id=?', (booking.get('visit_date'),booking.get('visit_time'),booking.get('visit_end'),booking.get('visit_group'),pid))
        db.log(conn, pid, 'undo_stage', event, 'app')
    elif name == 'not_visited':
        event = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='visited' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if p['state'] != 'visited' or not event or json.loads(event['detail'] or '{}').get('auto') is not True:
            raise ValueError('latest visit is not an automatic visit')
        visit_date = p['visit_date']
        db.set_state(conn, pid, 'pooled', 'Visit did not happen ' + date(visit_date).strftime('%d/%m/%Y'), source='app', force=True)
        conn.execute('UPDATE patients SET offered_date=visit_date,visit_date=NULL,visit_time=NULL,visit_end=NULL,updated_at=? WHERE id=?', (db.now(), pid))
        conn.execute("UPDATE visits SET visit_date=NULL,report_sent=NULL,claimed=NULL,note='auto-recorded, did not happen' WHERE id=(SELECT id FROM visits WHERE patient_id=? AND kind='hmr' AND source='app' ORDER BY id DESC LIMIT 1)", (pid,))
        db.log(conn, pid, name, {'date': visit_date}, 'app')
    elif name == 'move_declined':
        if p['state'] != 'declined':
            raise ValueError('patient is not declined')
        moved = move_patient_item(conn, p, 'Declined', moved_items)
        if moved: db.log(conn, pid, 'move_declined', {}, 'app')
    elif name == 'claim_now':
        visit, sent = date(body.get('visit_date')), date(body.get('report_sent'))
        if p['state'] in ('sent', 'claimed') or not visit <= sent <= dt.date.today():
            raise ValueError('invalid state or dates')
        db.log(conn, pid, 'visited', {'date': body['visit_date']}, 'app')
        db.log(conn, pid, 'report_sent', {'date': body['report_sent']}, 'app')
        conn.execute("INSERT INTO visits(patient_id,kind,visit_date,report_sent,folder,source) VALUES (?,'hmr',?,?,?,'app')",
                     (pid, body['visit_date'], body['report_sent'], p['folder']))
        db.set_state(conn, pid, 'sent', 'Visited outside the app', source='app', force=True)
    elif name == 'followup_done':
        existing = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind=? AND visit_date >= COALESCE((SELECT MAX(visit_date) FROM visits WHERE patient_id=? AND kind='hmr'), '') ORDER BY id DESC LIMIT 1", (pid,body['kind'],pid)).fetchone()
        if existing: return {'ok': True}
        conn.execute("INSERT INTO visits(patient_id,kind,visit_date,folder,source) VALUES (?,?,?,?,'app')", (pid,body['kind'],body['date'],p['folder']))
        db.log(conn, pid, name, {'kind':body['kind'],'date':body['date']}, 'app')
    elif name == 'followup_claimed':
        row = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind=? AND visit_date IS NOT NULL ORDER BY visit_date DESC,id DESC LIMIT 1", (pid, body['kind'])).fetchone()
        if not row: raise ValueError('follow-up is not done')
        conn.execute('UPDATE visits SET claimed=? WHERE id=?', (body['date'], row['id']))
        db.log(conn, pid, name, {'kind': body['kind'], 'date': body['date']}, 'app')
    elif name == 'call':
        if body.get('outcome') not in ('no_answer', 'left_message', 'spoke', 'booked', 'declined', 'other') or not isinstance(body.get('note', ''), str): raise ValueError('invalid call')
        db.log(conn, pid, name, {'outcome': body['outcome'], 'note': body.get('note', '')}, 'app')
    elif name == 'note':
        if not isinstance(body.get('text'), str):
            raise ValueError('text must be a string')
        conn.execute('UPDATE patients SET note=?,updated_at=? WHERE id=?', (body['text'], db.now(), pid))
        db.log(conn, pid, 'note', {'text': body['text']}, 'app')
    elif name == 'update':
        fields = body.get('fields')
        allowed = {'phone', 'address', 'suburb', 'postcode', 'medicare', 'irn', 'ihi', 'dob', 'sex'}
        if not isinstance(fields, dict) or not fields or not fields.keys() <= allowed or any(v is not None and not isinstance(v, str) for v in fields.values()):
            raise ValueError('invalid fields')
        conn.execute('UPDATE patients SET ' + ','.join(k+'=?' for k in fields) + ',updated_at=? WHERE id=?', [*fields.values(), db.now(), pid])
        db.log(conn, pid, 'update', fields, 'app')
    else:
        raise ValueError('unknown action')
    conn.commit()
    return {'ok': True, 'moved': moved} if name in ('decline_phone', 'move_declined', 'expired', 'claim_now') else {'ok': True}



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
        if path == '/api/agents' and method == 'GET': return 200, agents.public(agents.load())
        if path == '/api/templates/register' and method == 'POST':
            import template_report_builder
            if not isinstance(body, dict) or set(body) != {'source', 'version', 'approved_by', 'owner_authorised'}:
                raise ValueError('Invalid template registration request')
            result = template_report_builder.register(
                body['source'], body['version'], body['approved_by'], body['owner_authorised']
            )
            db.log(conn, None, 'template_registered',
                   {'version': result['version'], 'sha256': result['sha256'],
                    'approved_by': result['approved_by']}, 'app')
            conn.commit()
            return 200, result
        if path == '/api/medicines/status' and method == 'GET':
            return 200, medicine_reference.status()
        if path == '/api/medicines/suggest' and method == 'POST':
            if not isinstance(body, dict) or set(body) != {'queries'}: raise ValueError('Invalid suggestion request')
            return 200, medicine_reference.suggest_many(body['queries'])
        if path == '/api/medicines/search' and method == 'GET':
            q = query.get('q', ''); q = q[0] if isinstance(q, list) and q else q
            if not isinstance(q, str): raise ValueError('invalid search')
            return 200, medicine_reference.search(q)
        if path == '/api/records/status' and method == 'GET':
            return 200, records.status(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
        if path == '/api/records/migrate' and method == 'POST':
            return 200, records.migrate_all(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
        if path == '/api/records/retire' and method == 'POST':
            if body != {'confirmed': True}: raise ValueError('Confirmation required')
            result = records.retire_matching(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
            db.log(conn, None, 'record_plain_copies_removed', result, 'api')
            conn.commit()
            return 200, result
        if path == '/api/records/export' and method == 'POST':
            if not isinstance(body, dict) or set(body) != {'patient_id', 'destination'} or not isinstance(body['patient_id'], int): raise ValueError('invalid export input')
            row = conn.execute('SELECT * FROM patients WHERE id=?', (body['patient_id'],)).fetchone()
            if not row and body['patient_id'] != records.GLOBAL_PATIENT: raise ValueError('patient not found')
            dest = Path(body['destination']) if isinstance(body['destination'], str) else None
            if not dest or not dest.is_absolute() or dest.is_symlink(): raise ValueError('choose an export folder')
            resolved = dest.resolve()
            for guarded in (Path(db.DATA_DIR).resolve(), Path(db.BASE).resolve()):
                if resolved == guarded or guarded in resolved.parents: raise ValueError('export outside the app data and the patient workspace')
            result = records.export_folder(conn, body['patient_id'], resolved)
            db.log(conn, row['id'] if row else None, 'records_exported', {'count': len(result)}, 'api')
            conn.commit()
            return 200, {'files': result, 'folder': str(resolved), 'warning': 'This copy is outside the encryption HMR Desk applies to its own storage.'}
        if path == '/api/backups/create' and method == 'POST':
            import backup_bundle
            if not isinstance(body, dict) or set(body) != {'target', 'passphrase'}: raise ValueError('invalid backup input')
            return 200, backup_bundle.create(conn, db.BASE, body['target'], body['passphrase'])
        if path == '/api/backups/preview' and method == 'POST':
            import backup_bundle
            if not isinstance(body, dict) or set(body) != {'source', 'passphrase'}: raise ValueError('invalid backup preview')
            return 200, backup_bundle.restore(body['source'], None, body['passphrase'], preview_only=True)
        if path == '/api/backups/validate-isolated' and method == 'POST':
            import backup_bundle
            if not isinstance(body, dict) or set(body) != {'destination'} or not isinstance(body['destination'], str):
                raise ValueError('Invalid isolated recovery validation')
            return 200, backup_bundle.verify_isolated(body['destination'])
        if path == '/api/backups/restore' and method == 'POST':
            import backup_bundle
            if not isinstance(body, dict) or set(body) != {'source', 'destination', 'passphrase'}: raise ValueError('invalid restore input')
            # Restore into a new, isolated directory; NEVER replace an active database.
            return 200, backup_bundle.restore(body['source'], body['destination'], body['passphrase'])
        if path == '/api/storage/status' and method == 'GET':
            return 200, db.storage_status()
        if path == '/api/storage/recovery-key' and method == 'POST':
            import dbkey
            try:
                return 200, {'recovery_key': dbkey.reveal_recovery_key(db.db_path())}
            except dbkey.RecoveryKeyError as exc:
                return 409, {'error': str(exc)}
        if path == '/api/storage/recovery-key/confirm' and method == 'POST':
            import dbkey
            return 200, dbkey.acknowledge_recovery_key(db.db_path())
        if path == '/api/storage/rotate' and method == 'POST':
            recovery = db.rotate_key(conn)
            db.log(conn, None, 'storage_key_rotated', {}, 'app'); conn.commit()
            return 200, {'recovery_key': recovery}
        if path == '/api/settings' and method == 'GET': return 200, {'settings': settings.listing(conn)}
        if path == '/api/settings' and method == 'POST':
            settings.update(conn, body); db.log(conn, None, 'settings_updated', {'keys': list(body)}, 'api'); conn.commit()
            return 200, {'ok': True}
        if path == '/api/agents' and method == 'POST':
            agents.put(body); return 200, {'ok': True}
        if path == '/api/agents/delete' and method == 'POST':
            if not isinstance(body, dict): raise ValueError('invalid body')
            agents.delete(body.get('name')); return 200, {'ok': True}
        if path == '/api/agents/select' and method == 'POST':
            agents.select(body); return 200, {'ok': True}
        if path == '/api/agents/test' and method == 'POST':
            if not isinstance(body, dict): raise ValueError('invalid body')
            return 200, {'reply': agents.run(body.get('name'), 'Reply with the single word OK.', test=True)[:200]}
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
        if method == 'GET' and path == '/api/library':
            import report
            q = query.get('q', '')
            return 200, {'results': report.library(q[0] if isinstance(q, list) and q else q)}
        match = re.fullmatch(r'/api/patients/(\d+)/suggestions(?:/context)?', path)
        if method == 'GET' and match:
            import suggest
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            context = suggest.context_for(conn, p)
            if path.endswith('/context'):
                return 200, {'context_snapshot_sha256': context['context_snapshot_sha256']}
            return 200, {'suggestions': suggest.suggest(context), 'context_gaps': suggest.context_gaps(context),
                         'context_snapshot_sha256': context['context_snapshot_sha256']}
        match = re.fullmatch(r'/api/patients/(\d+)/report/refresh', path)
        if method == 'POST' and match:
            import report
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            result = report.refresh(conn, p); conn.commit(); return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/report', path)
        if match:
            import report
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if method == 'GET':
                ai = query.get('ai', '')
                return 200, report.load(conn, p, (ai[0] if isinstance(ai, list) and ai else ai) == '1')
            if method == 'POST':
                result = report.save(conn, p, body); conn.commit(); return 200, result
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
        match = re.fullmatch(r'/api/patients/(\d+)/pathology/sources', path)
        if match and method in ('GET', 'POST'):
            import pathology_import
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if method == 'GET':
                return 200, pathology_import.sources(conn, p)
            if not isinstance(body, dict) or set(body) != {'path'} or not isinstance(body['path'], str):
                raise ValueError('Invalid pathology import')
            result = pathology_import.import_pdf(conn, p, body['path'])
            db.log(conn, p['id'], 'pathology_source_imported',
                   {'sha256': result['sha256'], 'pages': result['page_count'], 'name': result['name']}, 'api')
            conn.commit()
            return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/pathology-records', path)
        if match and method in ('GET', 'POST'):
            import pathology_records
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if method == 'GET':
                return 200, pathology_records.load(conn, p)
            try:
                result = pathology_records.save(conn, p, body, reviewer=settings.get(conn, 'pharmacist_name'))
            except ValueError as exc:
                if 'changed; reload' in str(exc): return 409, {'error': str(exc)}
                raise
            db.log(conn, p['id'], 'pathology_records_saved',
                   {'count': len(result['records']), 'revision': result['revision']}, 'api')
            conn.commit()
            return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/reconciliation', path)
        if match and method in ('GET', 'POST'):
            import interview
            import reconciliation
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            record = interview.load(conn, p)
            saved_review = records.get_json(conn, p['id'], 'reconciliation_review.json') or {}
            if method == 'POST':
                if not isinstance(body, dict) or set(body) != {'source_hash', 'reviewed_by'}: raise ValueError('invalid reconciliation review')
                review = reconciliation.acknowledge(record, body['source_hash'], body['reviewed_by'])
                records.put_json(conn, p['id'], 'reconciliation_review.json', review)
                db.log(conn, p['id'], 'reconciliation_reviewed', {'source_hash': review['source_hash']}, 'api')
                conn.commit()
                return 200, reconciliation.review_status(record, review)
            result = reconciliation.audit(record)
            result.update(reconciliation.review_status(record, saved_review))
            return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/interview', path)
        if match:
            import interview
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            if method == 'GET': return 200, interview.load(conn, p)
            if method == 'POST':
                try: result = interview.save(conn, p, body)
                except interview.Conflict:
                    conn.rollback(); return 409, {'error': 'interview conflict'}
                return 200, result
        match = re.fullmatch(r'/api/patients/(\d+)/medicine-context', path)
        if match and method == 'GET':
            p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
            if not p: return 404, {'error': 'patient not found'}
            import followup
            return 200, followup.medicine_context(conn, p)
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
                if method == 'GET' and not match[4]: return 200, followup.load(conn, p, number)
                if method == 'POST' and match[4]: return 200, {'file': followup.export(conn, p, number)}
                if method == 'POST':
                    followup.validate(body)
                    if body['date']: date(body['date'])
                    result = followup.save(conn, p, number, body)
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
                result['medicine_snapshot_changed'] = 'medicine_snapshot_sha256' in result and result['medicine_snapshot_sha256'] != current_digest
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
                    if not valid_alternatives(meds, relevant, alternatives): raise ValueError('Select the medicine actually taking for each stopped overlap')
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
        if method == 'GET' and path in ('/api/summary', '/api/appointments'):
            def range_date(name):
                value = query.get(name)
                if isinstance(value, list):
                    if len(value) != 1: raise ValueError('invalid date')
                    value = value[0]
                return date(value)
            start, end = range_date('from'), range_date('to')
            if end < start or (path == '/api/summary' and (end - start).days >= 93): raise ValueError('invalid date range')
            if path == '/api/summary':
                import days
                return 200, days.period_summary(conn, str(start), str(end))
            return 200, {'appointments': [dict(row) for row in conn.execute('SELECT * FROM appointments WHERE date BETWEEN ? AND ? ORDER BY date,start,id', (str(start), str(end)))]}
        if method == 'POST' and path == '/api/appointments' and isinstance(body, dict):
            date(body.get('date'))
            start, end = clock(body.get('start')), clock(body.get('end'))
            if end <= start: raise ValueError('end must be after start')
            title = body.get('title')
            if not isinstance(title, str) or not title.strip(): raise ValueError('title required')
            place, note = body.get('place', ''), body.get('note', '')
            if not isinstance(place, str) or not isinstance(note, str): raise ValueError('invalid place or note')
            values = (body['date'], body['start'], body['end'], title.strip(), place.strip(), note)
            if 'id' in body:
                if type(body['id']) is not int or body['id'] <= 0: raise ValueError('invalid id')
                result = conn.execute('UPDATE appointments SET date=?,start=?,end=?,title=?,place=?,note=? WHERE id=?', (*values, body['id']))
                if not result.rowcount: return 404, {'error': 'appointment not found'}
                ident = body['id']
            else:
                ident = conn.execute('INSERT INTO appointments(date,start,end,title,place,note,created_at) VALUES (?,?,?,?,?,?,?)', (*values, db.now())).lastrowid
            conn.commit()
            return 200, dict(conn.execute('SELECT * FROM appointments WHERE id=?', (ident,)).fetchone())
        match = re.fullmatch(r'/api/appointments/(\d+)/delete', path)
        if method == 'POST' and match:
            result = conn.execute('DELETE FROM appointments WHERE id=?', (int(match[1]),))
            conn.commit()
            return (200, {'ok': True}) if result.rowcount else (404, {'error': 'appointment not found'})
        match = re.fullmatch(r'/api/days/([^/]+)/plan', path)
        if match and method in ('GET', 'POST'):
            import days
            day = date(match[1]).isoformat()
            if method == 'GET': return 200, days.plan(conn, day)
            result = days.save_plan(conn, day, body); conn.commit(); return 200, result
        match = re.fullmatch(r'/api/days/([^/]+)/route', path)
        if method == 'GET' and match:
            import days
            day = date(match[1]).isoformat()
            include = query.get('include', 'confirmed')
            if isinstance(include, list):
                if len(include) != 1: raise ValueError('invalid include')
                include = include[0]
            if include not in ('confirmed', 'all'): raise ValueError('invalid include')
            return 200, days.route(conn, day, include)
        if method == 'GET' and path == '/api/days':
            import days
            def parameter(name):
                value = query.get(name)
                if isinstance(value, list):
                    if len(value) != 1: raise ValueError('invalid date')
                    value = value[0]
                return date(value)
            start, end = parameter('from'), parameter('to')
            if end < start or (end - start).days >= 62: raise ValueError('invalid date range')
            return 200, days.listing(conn, start.isoformat(), end.isoformat())
        if method == 'GET' and path.startswith('/api/days/'):
            import days
            day = date(path[len('/api/days/'):]).isoformat()
            return 200, days.detail(conn, day)
        if method == 'GET' and path == '/api/attention':
            import lifecycle
            return 200, lifecycle.attention(conn)
        if method == 'GET' and path == '/api/today':
            today = dt.date.today()
            visits = [dict(p) for p in conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL AND visit_date IN (?,?) ORDER BY visit_date,visit_time', (str(today), str(today+dt.timedelta(days=1))))]
            alerts = []
            for p in conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL'):
                follow = patient_followups(conn, p['id'])
                if follow:
                    for kind in follow['alerts']:
                        alerts.append({'id': p['id'], 'name': p['name'], 'type': kind, 'date': follow['window_end'] if kind.startswith('follow-up') else follow['new_hmr'], 'window_end': follow['window_end'] if kind.startswith('follow-up') else None})
                if p['state'] in ('confirmed','pathology_ready','sheet_ready'):
                    for field, label in [('has_pathology','missing pathology'), ('has_sheet','missing interview sheet')]:
                        if not p[field] and (field != 'has_pathology' or not steps.done('pathology', conn, p)): alerts.append({'id': p['id'], 'name': p['name'], 'type': label})
                if p['referral_date'] and p['state'] in db._PRE:
                    expiry = referral_expiry(conn, p['referral_date'])
                    if expiry:
                        remaining = (expiry-today).days
                        if remaining <= settings.get(conn, 'referral_warn_days'):
                            alerts.append({'id': p['id'], 'name': p['name'], 'type': 'referral expired' if remaining < 0 else 'referral expires', 'date': str(expiry), 'days_left': remaining})
            return 200, {'visits': visits, 'alerts': alerts}
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
        return 404, {'error': 'not found'}
    except (ValueError, TypeError) as exc:
        conn.rollback()
        return 400, {'error': str(exc)}
