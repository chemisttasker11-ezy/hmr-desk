"""Workflow steps and their prerequisites; no patient data is inferred."""
import re
import hashlib
from dataclasses import dataclass
import json
from pathlib import Path
import db
import jobs
import settings

PRE = ('confirmed', 'pathology_ready', 'sheet_ready')
POST = ('visited', 'report_drafted', 'signed_off', 'sent', 'claimed')

def folder(p):
    try: return jobs.patient_folder(p)
    except (ValueError, OSError): return None

def event_date(conn, p, name):
    field = {'visited': 'visit_date', 'report_sent': 'report_sent', 'claimed': 'claimed'}.get(name)
    if field:
        target = {'visited': 'visited', 'report_sent': 'sent', 'claimed': 'claimed'}[name]
        for event in conn.execute("SELECT type,detail FROM events WHERE patient_id=? AND type IN (?, 'visited', 'undo_stage', 'not_visited') ORDER BY id DESC", (p['id'], name)):
            try: detail = json.loads(event['detail'] or '{}')
            except (ValueError, TypeError): continue
            if event['type'] == 'undo_stage' and detail.get('to') == target: return None
            if event['type'] == 'not_visited' and name in ('visited', 'report_sent', 'claimed'): return None
            if event['type'] == name and detail.get('date'): return detail['date']
            if event['type'] == 'visited' and name != 'visited':
                row = conn.execute("SELECT visit_date," + field + " FROM visits WHERE patient_id=? AND kind='hmr' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
                return row[field] if row and row['visit_date'] == detail.get('date') else None
        row = conn.execute("SELECT " + field + " FROM visits WHERE patient_id=? AND kind='hmr' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
        return row[0] if row else None
    for row in conn.execute('SELECT detail FROM events WHERE patient_id=? AND type=? ORDER BY id DESC', (p['id'], name)):
        try:
            value = json.loads(row[0] or '{}').get('date')
            if value: return value
        except (ValueError, TypeError, AttributeError): pass
    return None

def exists(p, name):
    f = folder(p)
    return bool(f and (f / name).is_file())

def interactions_result_current(p, name):
    f = folder(p)
    if not f or not isinstance(name, str): return False
    match = re.fullmatch(r'MIMS interactions generated ([0-9a-f]{64}) ([0-9a-f]{64})\.txt', name)
    if not match: return False
    try:
        confirmed = f / 'confirmed_meds.json'
        import api
        return (confirmed.is_file() and api.confirmed_medicines_current(p)
                and hashlib.sha256(confirmed.read_bytes()).hexdigest() == match[1]
                and hashlib.sha256((f / name).read_bytes()).hexdigest() == match[2]
                and hashlib.sha256(confirmed.read_bytes()).hexdigest() == match[1])
    except OSError: return False

def interactions_done(p):
    f = folder(p)
    if not f: return False
    confirmed = f / 'confirmed_meds.json'
    if confirmed.is_file():
        import api
        if not api.confirmed_medicines_current(p): return False
    for x in f.iterdir():
        if not x.is_file() or not x.name.lower().startswith('mims interactions') or x.suffix.lower() != '.txt': continue
        if x.name.lower().startswith('mims interactions generated'):
            if interactions_result_current(p, x.name): return True
        elif not confirmed.is_file() or x.stat().st_mtime_ns >= confirmed.stat().st_mtime_ns:
            return True
    return False

def built(p):
    f = folder(p)
    if not f: return False
    try:
        spec = json.loads((f / 'report_spec.json').read_text(encoding='utf-8'))
        target = Path(spec['out'])
        name = target.name
        expected = (f / name).resolve()
        return any(x.is_file() and str(x.resolve()).casefold() == str(expected).casefold() for x in f.iterdir())
    except (ValueError, OSError, KeyError, TypeError): return False

def ai_off(name, conn):
    key = {'interview_assist': 'ai_interview_assist', 'report_draft': 'ai_report_assist', 'report_assist': 'ai_report_assist'}.get(name)
    return bool(key and conn and not settings.get(conn, key))

def ready(name, conn, p):
    if ai_off(name, conn): return (False, 'AI assist is off in Settings')
    if name in ('intake_dry', 'intake_apply'):
        return (False, 'Use New referrals to review PDFs before adding patients')
    if name in ('register_xlsx', 'sheet_sync', 'import_history', 'import_history_apply'): return (True, '')
    if p is None: return (False, 'patient required')
    if done(name, conn, p): return (False, 'already done')
    if name == 'pathology':
        if p['state'] not in PRE: return (False, 'patient is not scheduled')
        if not folder(p): return (False, 'patient folder missing')
        if not all((p['name'] and len(p['name'].split()) >= 2, p['dob'], p['sex'], p['medicare'] or p['ihi'])): return (False, 'surname, DOB, sex and Medicare or IHI required')
    elif name in ('interview_sheet', 'interview_pack', 'interview_assist'):
        if p['state'] not in PRE: return (False, 'patient is not scheduled')
        if not folder(p): return (False, 'patient folder missing')
    elif name == 'report_extract':
        if p['state'] not in POST: return (False, 'visit not recorded')
        f = folder(p)
        if not f: return (False, 'patient folder missing')
        # The referral PDF ("Name_ XX.pdf") may carry the handwritten blue notes itself.
        referral = any(x.is_file() and ('referral' in x.name.lower() or re.search(r'_ [A-Z]{2,4}\.pdf$', x.name)) for x in f.iterdir())
        if not referral: return (False, 'referral document missing')
        if (f / 'case-images').exists(): return (False, 'extraction output already exists')
    elif name == 'report_draft':
        if p['state'] not in POST: return (False, 'visit not recorded')
        if not exists(p, 'case.txt'): return (False, 'extract output missing')
        if not interactions_done(p): return (False, 'run the eMIMS interaction check first')
    elif name == 'confirm_medicines':
        if p['state'] not in POST: return (False, 'visit not recorded')
        return (False, 'confirm the medicine list first')
    elif name == 'report_start':
        if p['state'] not in POST: return (False, 'visit not recorded')
        if not exists(p, 'confirmed_meds.json'): return (False, 'confirm the medicine list first')
        if not interactions_done(p): return (False, 'run the eMIMS interaction check first')
    elif name == 'report_assist':
        if p['state'] not in POST: return (False, 'visit not recorded')
        if not exists(p, 'case.txt'): return (False, 'extract output missing')
        if not interactions_done(p): return (False, 'run the eMIMS interaction check first')
    elif name == 'interactions':
        if p['state'] not in POST: return (False, 'visit not recorded')
        if not exists(p, 'confirmed_meds.json'): return (False, 'confirm the medicine list first')
    elif name == 'report_build':
        if p['state'] not in ('visited', 'report_drafted'): return (False, 'patient is not awaiting report')
        if not exists(p, 'report_spec.json'): return (False, 'report spec missing')
        try:
            if not json.loads((folder(p) / 'report_spec.json').read_text(encoding='utf-8')).get('issues'): return (False, 'add at least one finding')
        except (OSError, ValueError, TypeError): return (False, 'invalid report spec')
    elif name == 'claim':
        if p['state'] != 'sent': return (False, 'report not marked sent')
        try:
            consent = json.loads((folder(p) / 'interview.json').read_text(encoding='utf-8'))['consent']['signed'] is True
        except (OSError, ValueError, KeyError, TypeError): consent = False
        if not consent: return (False, 'PPA consent not recorded')
        if not event_date(conn, p, 'visited') or not event_date(conn, p, 'report_sent'): return (False, 'visit and report sent dates required')
    return (True, '')

def done(name, conn, p):
    if p is None: return False
    if name == 'pathology':
        row = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='pathology_result' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone() if conn else None
        status = json.loads(row[0] or '{}').get('status') if row else None
        return False if status == 'access code needed' else bool(p['has_pathology'] or status == 'no report to read')
    if name in ('interview_sheet', 'interview_pack'):
        f = folder(p)
        return bool(f and any(x.is_file() and x.name.lower().startswith('hmr interview') and x.suffix.lower() in ('.docx', '.pdf') for x in f.iterdir()))
    if name == 'report_extract': return exists(p, 'case.txt')
    if name == 'report_draft': return exists(p, 'report_spec.json')
    if name == 'confirm_medicines': return exists(p, 'confirmed_meds.json')
    if name == 'report_start': return exists(p, 'report_spec.json')
    if name == 'report_assist': return exists(p, 'report_spec.ai.json')
    if name == 'interactions': return interactions_done(p)
    if name == 'report_build': return built(p) or p['state'] in ('report_drafted', 'signed_off', 'sent', 'claimed')
    if name == 'claim': return p['state'] == 'claimed'
    return False

@dataclass(frozen=True)
class Step:
    name: str
    runs_in: str
    label: str
    def ready(self, conn, patient): return ready(self.name, conn, patient)
    def done(self, conn, patient): return done(self.name, conn, patient)

STEPS = [Step(*x) for x in [
    ('intake_dry','engine','review intake'), ('intake_apply','engine','review intake'),
    ('pathology','mhr','collect pathology'), ('interview_assist','ai','assist interview'), ('interview_pack','engine','make interview sheet'),
    ('interview_sheet','engine','make interview sheet'), ('report_extract','engine','extract report'),
    ('confirm_medicines','manual','confirm medicines'), ('interactions','emims','check interactions'), ('report_draft','ai','draft report'), ('report_start','engine','start report'), ('report_assist','ai','assist report'),
    ('report_build','engine','build report'), ('claim','ppa','claim'),
    ('import_history','engine','plan history import'), ('import_history_apply','engine','apply history import'),
    ('register_xlsx','engine','export register'), ('sheet_sync','engine','sync sheet')]]
BY_NAME = {s.name: s for s in STEPS}
# These are the patient flow; batch operations are explicit and sheet_sync has no existing job.
FLOW = [BY_NAME[n] for n in ('pathology','interview_sheet','confirm_medicines','interactions','report_assist','report_start','report_build','claim')]
