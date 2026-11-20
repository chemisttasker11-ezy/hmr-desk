"""Fixed, single-worker jobs for the local API."""
import datetime as dt
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

import db
import importer
import history
import records as record_store

INTAKE_SCRIPT = Path(db.BASE) / 'scripts' / 'intake' / 'intake.py'
# Application-owned assets: never depend on an individual developer's Claude profile.
APP_ASSETS = Path(__file__).resolve().parent / 'assets'
SKILL = APP_ASSETS
EXTRACT_SCRIPT = APP_ASSETS / 'scripts' / 'extract.py'
BUILD_SCRIPT = APP_ASSETS / 'scripts' / 'build.py'
INTERVIEW_SCRIPT = APP_ASSETS / 'scripts' / 'make_interview.py'
FIELDS = {'name', 'sex', 'dob', 'medicare', 'irn', 'address', 'suburb', 'phone', 'gp', 'gp_initials', 'gp_provider', 'clinic', 'referral_date', 'ihi', 'notes'}
_lock = threading.Lock()
_jobs = {}
_active = None


@contextmanager
def connection():
    conn = db.connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def intake_rows():
    report = importer.newest((Path(db.BASE) / 'TO SORT').glob('intake_report_*.json'))
    return importer.read(report) if report else []


def correction(file, fields):
    if not isinstance(file, str) or not file or Path(file).name != file or '/' in file or '\\' in file:
        raise ValueError('invalid file')
    if not isinstance(fields, dict) or not fields or not fields.keys() <= FIELDS or any(not isinstance(v, str) for v in fields.values()):
        raise ValueError('invalid fields')
    path = Path(db.BASE) / 'TO SORT' / 'intake_corrections.json'
    with _lock, connection() as conn:
        data = record_store.get_json(conn, record_store.GLOBAL_PATIENT, 'intake_corrections.json')
        if data is None:
            data = importer.read(path) if path.exists() else {}
        data.setdefault(file, {}).update(fields)
        record_store.put_json(conn, record_store.GLOBAL_PATIENT, 'intake_corrections.json', data)


def outside_files(conn):
    """Record files that are not in a patient folder: (patient id, record name, plain path)."""
    items = [(record_store.GLOBAL_PATIENT, 'intake_corrections.json', Path(db.BASE) / 'TO SORT' / 'intake_corrections.json'),
             (record_store.GLOBAL_PATIENT, 'history-import-plan.json', Path(db.DATA_DIR) / 'history-import-plan.json')]
    for p in conn.execute('SELECT * FROM patients').fetchall():
        items.append((p['id'], 'interview_spec.json', interview_spec_path(p)))
    return items


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def run_script(script, *args):
    if not Path(script).is_file():
        raise RuntimeError('Required application component is not bundled: ' + str(script))
    result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=1800,
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})  # cp1252 console crashes on PDF symbols
    output = '\n'.join(x for x in (result.stdout, result.stderr) if x)
    if result.returncode:
        raise RuntimeError(output or f'script exited {result.returncode}')
    return output


def intake_dry(patient_id):
    raise ValueError('Use New referrals to review PDFs before adding patients')


def intake_apply(patient_id):
    raise ValueError('Use New referrals to review PDFs before adding patients')


HEADERS = ['Name', 'Suburb', 'Address', 'Number', 'Appointment', 'Dr Name', 'Referral Date', 'Status', 'Notes', 'Interview Date', 'SMS', 'DOB', 'Sex', 'Medicare', 'IRN', 'IHI', 'Clinic', 'Report Sent Date', 'Claimed']
GROUPS = {'Current': ('new', 'pooled', 'offered', 'hold'), 'Scheduled': ('confirmed', 'pathology_ready', 'sheet_ready'),
          'Visited': ('visited', 'report_drafted', 'signed_off', 'sent'), 'Claimed': ('claimed',), 'Declined': ('declined',), 'Expired': ('expired',)}


def display_date(value):
    if not value: return ''
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try: return dt.datetime.strptime(value[:10], fmt).strftime('%d/%m/%Y')
        except ValueError: pass
    return value


def register_xlsx(patient_id):
    from openpyxl import Workbook
    book = Workbook(); book.remove(book.active)
    sheets = {name: book.create_sheet(name) for name in GROUPS}
    for sheet in sheets.values(): sheet.append(HEADERS)
    with connection() as conn:
        for p in conn.execute('SELECT * FROM patients ORDER BY name'):
            sheet = next(sheets[n] for n, states in GROUPS.items() if p['state'] in states)
            dates = {}
            for event in conn.execute("SELECT type, detail FROM events WHERE patient_id=? AND type IN ('visited','report_sent','claimed') ORDER BY id", (p['id'],)):
                dates[event['type']] = (json.loads(event['detail'] or '{}')).get('date')
            appointment = ' '.join(filter(None, (display_date(p['visit_date']), p['visit_time'])))
            sheet.append([p['name'], p['suburb'], p['address'], p['phone'], appointment, p['gp'], display_date(p['referral_date']), p['status_text'] or p['state'], p['note'], display_date(dates.get('visited')), '', display_date(p['dob']), p['sex'], p['medicare'], p['irn'], p['ihi'], p['clinic'], display_date(dates.get('report_sent')), display_date(dates.get('claimed'))])
    target = Path(db.DATA_DIR) / 'Booking_Register.xlsx'
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, suffix='.xlsx'); os.close(fd)
    try:
        book.save(temp); os.replace(temp, target)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return 'saved ' + str(target)


def interview_pack(patient_id, fmt='docx'):
    import interview
    with connection() as conn:
        p = get_patient(conn, patient_id)
        output = interview.pack(conn, p, fmt)
        if db.can_move(p['state'], 'sheet_ready'): db.set_state(conn, patient_id, 'sheet_ready', source='job')
        db.log(conn, patient_id, 'interview_pack', {}, 'job')
        return output


def interview_assist(patient_id):
    import agents, interview
    with connection() as conn:
        p = get_patient(conn, patient_id)
        record = interview.load(conn, p)
        import settings
        if not settings.get(conn, 'clinical_ai_privacy_ack'):
            raise ValueError('Clinical AI privacy approval is required in Settings')
    import clinical_privacy
    name = agents.selected('interview_assist')
    selected = agents.get(name)
    if selected['type'] != 'api':
        raise clinical_privacy.PrivacyBlocked('Clinical AI requires a restricted API agent; CLI agents are disabled for patient data')
    clinical = clinical_privacy.project(record, sex=p['sex'] or '')
    prompt = ('Use only this de-identified clinical JSON. Do not infer identities. '
              'Return JSON {"points": {medicine: text}, "clarify": [..]}. '
              'Suggestions are for pharmacist review only. Data: '
              + json.dumps(clinical, ensure_ascii=False))
    reply = json_object(agents.run(name, prompt))
    points, clarify = reply.get('points'), reply.get('clarify')
    if not isinstance(points, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in points.items()) or not isinstance(clarify, list) or any(not isinstance(x, str) for x in clarify): raise ValueError('invalid assist response')
    # Reload to preserve edits made while the agent was running.
    with connection() as conn:
        p = get_patient(conn, patient_id); record = interview.load(conn, p)
        for row in record['meds']:
            if not row[3] and row[0] in points: row[3] = points[row[0]]
        record['clarify'].extend(clarify)
        interview.save(conn, p, record)
        db.log(conn, patient_id, 'interview_assist', {'agent': name}, 'job')
    return 'Interview suggestions added'


def patient_folder(p):
    if not p['folder']: raise ValueError('patient folder missing')
    base = Path(db.BASE).resolve()
    path = (base / p['folder']).resolve()
    if path == base or not path.is_relative_to(base):
        raise ValueError('patient folder is not a directory within BASE')
    if not path.exists():
        matches = []
        for name in ('Scheduled', 'Visited', 'To CLAIM', 'Completed & Claimed', 'Declined-Exp'):
            root = base / name
            if root.is_dir():
                matches.extend(candidate.resolve() for candidate in root.rglob(path.name)
                               if candidate.name == path.name and candidate.is_dir() and candidate.resolve().is_relative_to(base))
        if len(matches) == 1: return matches[0]
        if len(matches) > 1: raise ValueError('patient folder has multiple matches')
    if not path.is_dir(): raise ValueError('patient folder is not a directory within BASE')
    return path


def interview_spec_path(p):
    return Path(db.BASE) / 'Scheduled' / '_interview specs' / (p['key'].replace(' ', '_') + '.json')


def report_spec_path(p):
    return patient_folder(p) / 'report_spec.json'


def get_patient(conn, patient_id):
    p = conn.execute('SELECT * FROM patients WHERE id=?', (patient_id,)).fetchone()
    if not p: raise ValueError('patient not found')
    patient_folder(p)
    return p


def report_extract(patient_id):
    with connection() as conn:
        folder = patient_folder(get_patient(conn, patient_id))
    case, images = folder / 'case.txt', folder / 'case-images'
    if case.exists() or images.exists(): raise FileExistsError('Extraction output already exists')
    import local_referral_extraction
    output = local_referral_extraction.extract(folder, images)
    with connection() as conn:
        has_record = record_store.exists(conn, get_patient(conn, patient_id)['id'], 'interview.json')
    if has_record:
        import interview
        with connection() as conn:
            record = interview.load(conn, get_patient(conn, patient_id))
        lines = []
        for key, label in [('notes', 'Human interview notes'), ('concerns', 'Patient concerns / goals'), ('social', 'Social'), ('mobility', 'Mobility'), ('exercise', 'Exercise'), ('alcohol_smoking', 'Alcohol / smoking'), ('manages_meds', 'Medicine management'), ('allergies', 'Allergies / adverse reactions'), ('conditions', 'Conditions')]:
            if record[key]: lines.append(label + ': ' + record[key])
        if interview.details_text(record): lines.append('Structured interview details:\n' + interview.details_text(record))
        for row in record['obs']:
            if any(row[1:]): lines.append('Observation: ' + row[0] + ' | Referral: ' + row[1] + ' | At interview: ' + row[2])
        for row, meta in zip(interview.medicine_rows(record), record['details']['meds']):
            use_label = 'Previously recorded directions (not yet confirmed): ' if meta.get('use_status') == 'unknown' else 'Actually taking: '
            if any(row): lines.append('Referral medicine: ' + row[0] + ' | Referral directions: ' + row[1] + ' | ' + use_label + row[2] + ' | Points to check: ' + row[3] + ' | Notes: ' + row[4])
        for row, meta in zip(record['other_meds'], record['details']['other_meds']):
            direction_label = 'Previously recorded directions (not yet confirmed): ' if meta.get('use_status') == 'unknown' else 'Directions: '
            if any(row): lines.append('Medicine found during interview: ' + row[0] + ' | ' + direction_label + row[1] + ' | Why / who: ' + row[2] + ' | Notes: ' + row[3] + ' | Use: ' + interview.use_text(meta))
        for row in record['pathology']:
            if any(row): lines.append('Pathology: ' + ' | '.join(row))
        if record['sources']: lines.append('Recorded source notes: ' + ' | '.join(record['sources']))
        if record['clarify']: lines.append('Points to clarify: ' + ' | '.join(record['clarify']))
        if lines: output += '\n\nSaved interview record (may include referral-derived information; review source notes):\n' + '\n'.join(lines)
    with case.open('x', encoding='utf-8') as f: f.write(output)
    return output


def report_start(patient_id):
    import report
    with connection() as conn:
        report.start(conn, get_patient(conn, patient_id))
        return 'Report started'

def report_build(patient_id, pdf=False):
    import report
    with connection() as conn:
        conn.execute('BEGIN')  # one read snapshot: the spec, the checks and the evidence below all see the same committed state
        p = get_patient(conn, patient_id)
        folder = patient_folder(p)
        spec_bytes = record_store.get(conn, p['id'], 'report_spec.json')
        if spec_bytes is None: raise FileNotFoundError('Report spec missing')
        data = report.with_trusted_policy(conn, p, json.loads(spec_bytes.decode('utf-8-sig')))
        report.validate(data)
        import interview, pathology_records
        if data.get('interview_revision') and data['interview_revision'] != interview.revision(conn, p):
            raise ValueError('Interview changed after report preparation; refresh and re-review the report before building')
        if data.get('pathology_revision') and data['pathology_revision'] != pathology_records.revision(conn, p):
            raise ValueError('Pathology changed after report preparation; refresh and re-review the report before building')
        if not data['issues']: raise ValueError('add at least one finding')
        pending = report.placeholders(data)
        if pending: raise ValueError('Review placeholder fields: ' + ', '.join(pending))
        unreviewed = report.template_reviews_pending(conn, p, data)
        if unreviewed: raise ValueError('Review imported template findings: ' + ', '.join(str(n) for n in unreviewed))
        import report_auth
        # One snapshot, taken before rendering: build evidence records the sources the document is built from,
        # so a source saved during rendering or PDF conversion leaves evidence that sign-off refuses.
        snapshot = {
            'interview_revision': interview.revision(conn, p),
            'pathology_revision': pathology_records.revision(conn, p),
            'source_files_sha256': report_auth.source_snapshot(conn, p),
            'clinical_snapshot_sha256': report_auth.clinical_snapshot_hash(conn, p),
            'demographics': report.demographic_status(conn, p, data),  # block name -> matches/kept/unresolved, no text
        }
        import interaction_scope
        data, interaction_scope_result = interaction_scope.apply_to_report(conn, p, data)
        import pharmacist_identity
        identity = pharmacist_identity.resolve(conn)
        data = dict(data, pharmacist_details=identity['text'])
        conn.rollback()  # end the read snapshot before rendering; later writes (events, state) must not be blocked by it
        from pathlib import PureWindowsPath
        raw = str(data['out'])
        if not (Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute()): raise ValueError('Report spec out must be an absolute path')
        # A restored or moved workspace keeps the old root in the stored path. The output always lands in this patient's
        # folder under the stored file name, whichever root the spec was written under.
        name = PureWindowsPath(raw).name
        target = (folder / name).resolve() if name not in ('', '.', '..') else folder
        if target.parent != folder or target.suffix.lower() != '.docx': raise ValueError('Report output must be a DOCX in patient folder')
        # Preserve every prior DOCX/PDF and any signed revision; never overwrite.
        original = target
        for revision in range(1, 1001):
            target = original if revision == 1 else original.with_name(original.stem + '-v' + str(revision) + original.suffix)
            pdf_target = target.with_suffix('.pdf')
            if not target.exists() and (not pdf or not pdf_target.exists()): break
        else: raise FileExistsError('Report revision limit exceeded')
        import local_report_builder
        import template_report_builder
        import pdf_export
        template_root = template_report_builder.active_template_root()
        approved = None
        try:
            approved = template_report_builder.approved_template(template_root)
        except FileNotFoundError:
            pass
        # Missing owner approval always means provisional, never a final layout.
        # An installed but invalid manifest must fail closed (do not downgrade).
        with tempfile.TemporaryDirectory(prefix='.hmr-docx-', dir=folder) as directory:
            draft = Path(directory) / target.name
            if approved:
                template_report_builder.render(data, draft, approved[0])
                placed = template_report_builder.has_marker(approved[0], 'PHARMACIST')
            else:
                local_report_builder.render(data, draft)
            if not draft.is_file(): raise RuntimeError('Draft Word report failed to render')
            if target.exists(): raise FileExistsError('Output appeared during report rendering')
            os.replace(draft, target)
        output = ('Built approved-layout Word draft ' + approved[1]['version']
                  if approved else 'Built a provisional local Word report (not owner-approved)')
        if identity['text'] and approved and not placed:
            output += '. Pharmacist details were not placed: the approved layout has no pharmacist placeholder.'
        if identity['name'] and identity['note']:
            output += '. ' + identity['note']
        if pdf:
            try:
                converted = pdf_export.convert(target, pdf_target)
            except (OSError, ValueError, RuntimeError) as exc:
                left = getattr(exc, 'cleanup_pending', None)
                if left:
                    db.log(conn, p['id'], 'pdf_cleanup_pending', {'folder': left, 'conversion': 'failed', 'error': exc.cleanup_error}, 'job'); conn.commit()
                why = pdf_export.failure_text(exc)
                db.log(conn, p['id'], 'pdf_conversion_failed', {'reason': why}, 'job'); conn.commit()
                raise RuntimeError('Local PDF conversion failed; prior Word draft preserved. Reason: ' + why + ('; ' + pdf_export.pending_note(left) if left else '')) from exc
            if isinstance(converted, dict) and converted.get('cleanup_pending'):
                left = Path(converted['cleanup_pending']).name
                db.log(conn, p['id'], 'pdf_cleanup_pending', {'folder': left, 'conversion': 'ok', 'error': converted.get('cleanup_error', '')}, 'job')
                output += '. PDF created. ' + pdf_export.pending_note(left)
        if p['state'] == 'visited' and db.can_move(p['state'], 'report_drafted'):
            db.set_state(conn, patient_id, 'report_drafted', source='job')
        import hashlib
        evidence = {
            'file': target.name,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'pdf_sha256': hashlib.sha256(pdf_target.read_bytes()).hexdigest() if pdf else '',
            'report_spec_sha256': hashlib.sha256(spec_bytes).hexdigest(),
            'interview_revision': snapshot['interview_revision'],
            'pathology_revision': snapshot['pathology_revision'],
            'template_version': approved[1]['version'] if approved else '',
            'template_sha256': approved[1]['sha256'] if approved else '',
            'template_approved': bool(approved),
            'source_files_sha256': snapshot['source_files_sha256'],
            'clinical_snapshot_sha256': snapshot['clinical_snapshot_sha256'],
            'demographics': snapshot['demographics'],
            'pharmacist_identity_sha256': pharmacist_identity.digest(identity),
        }
        db.log(conn, patient_id, 'report_build', evidence, 'job')
        return output


INTERVIEW_KEYS = {"out", "name", "dob", "age", "address", "phone", "gp", "visit", "referral_date", "obs_from_referral", "renal", "alcohol", "conditions", "allergies", "meds", "pathology", "clarify"}
REPORT_KEYS = {"out", "name", "assess_date", "report_date", "patient", "doctor", "dear", "thanks", "reason", "intro", "conditions", "allergies", "obs", "meds", "otc", "ceased", "issues", "path_date", "path", "followup"}

def referral_text(folder):
    files = sorted(x for x in folder.iterdir() if x.is_file() and 'referral' in x.name.lower())
    if not files: raise FileNotFoundError('Referral document missing')
    parts = []
    for file in files:
        if file.suffix.lower() == '.txt': parts.append(file.read_text(encoding='utf-8'))
        elif file.suffix.lower() == '.pdf':
            import fitz
            try:
                with fitz.open(file) as doc:
                    if doc.needs_pass: raise ValueError('Referral PDF is password-protected')
                    pages = [page.get_text('text', sort=True) for page in doc]
            except fitz.FileDataError as exc:
                raise ValueError('Referral PDF is unreadable') from exc
            if not any(page.strip() for page in pages):
                import referral_entry
                pages = referral_entry.parser().ocr_pdfs([file]).get(str(file), [])
            if not any(page.strip() for page in pages):
                raise ValueError('Referral PDF has no readable text; inspect the original')
            parts.append('\n'.join(pages))
        else: raise ValueError('Unsupported referral document: ' + file.name)
    return '\n\n'.join(parts)

def json_object(reply):
    decoder = json.JSONDecoder()
    for i, char in enumerate(reply):
        if char == '{':
            try:
                obj, _ = decoder.raw_decode(reply[i:])
                if isinstance(obj, dict): return obj
            except ValueError: pass
    raise ValueError('Agent reply does not contain a valid JSON object')

def agent_step(patient_id, name, output_path=None):
    # Legacy skill routes require patient-folder read/write access and raw case.txt.
    # They must not be used for identifiable clinical records.
    import clinical_privacy
    raise clinical_privacy.PrivacyBlocked(
        'Legacy patient-folder agent route disabled. Use manual report or clinical-only report assist.')


def interview_spec(patient_id):
    return agent_step(patient_id, 'interview_spec')


def report_draft(patient_id):
    return agent_step(patient_id, 'report_draft')


def report_assist(patient_id):
    """AI clinical findings only; patient identifiers are added by local report code."""
    import agents
    import clinical_privacy
    import interview
    import report
    with connection() as conn:
        patient = get_patient(conn, patient_id)
        import settings
        if not settings.get(conn, 'clinical_ai_privacy_ack'):
            raise ValueError('Clinical AI privacy approval is required in Settings')
        folder = patient_folder(patient)
        record = interview.load(conn, patient)
        clinical = clinical_privacy.project(record, sex=patient['sex'] or '')
        source_revision = record['revision']
        source_hash = clinical_privacy.fingerprint(clinical)
        selected_name = agents.selected('report_assist')
        selected = agents.get(selected_name)
        if selected['type'] != 'api':
            raise clinical_privacy.PrivacyBlocked(
                'Clinical AI requires a restricted API agent; CLI agents are disabled for patient data')
    prompt = ('You are assisting an Australian HMR pharmacist. Use only the clinical JSON. '
              'Return ONLY JSON with exactly one key: findings, an array of up to 15 objects '
              'each containing exactly title, recommendation, rationale, evidence_ids. '
              'Evidence IDs must be drawn from the input. Do not invent missing clinical facts. '
              'Recommendations are suggestions for pharmacist review, not prescribing decisions. '
              'Do not include names, dates of birth, contact details, provider details or identifiers. '
              'Clinical JSON: ' + json.dumps(clinical, ensure_ascii=False))
    reply = json_object(agents.run(selected_name, prompt))
    findings = clinical_privacy.validate_findings(reply, clinical)
    with connection() as conn:
        patient = get_patient(conn, patient_id)
        latest = interview.load(conn, patient)
        if latest['revision'] != source_revision or clinical_privacy.fingerprint(
                clinical_privacy.project(latest, sex=patient['sex'] or '')) != source_hash:
            raise ValueError('Clinical interview changed during AI analysis; rerun assistance')
        folder = patient_folder(patient)
        if record_store.exists(conn, patient['id'], 'report_spec.ai.json'):
            raise FileExistsError('Existing AI draft must be reviewed or removed before rerunning')
        manual = report.load(conn, patient)
        if manual.get('saved') is False:
            # Only an absent report carries saved=False; an existing report has no saved flag.
            # Start the manual report locally using the existing deterministic composer.
            manual = report.start(conn, patient)
        candidate = {k: v for k, v in manual.items() if k not in ('saved', 'interview_newer')}
        candidate['issues'] = findings
        report.validate(candidate)
        record_store.put_json(conn, patient['id'], 'report_spec.ai.json', candidate)
        db.log(conn, patient_id, 'report_assist', {
            'agent': selected_name, 'clinical_snapshot': source_hash,
            'finding_count': len(findings)}, 'job')
    return 'Clinical-only AI findings ready for pharmacist review'

def import_history(patient_id):
    if patient_id is not None: raise ValueError('batch job takes no patient')
    with connection() as conn:
        plan = history.plan(conn)
        record_store.put_json(conn, record_store.GLOBAL_PATIENT, 'history-import-plan.json', plan)
    return json.dumps(history.summary(plan), ensure_ascii=False)


def import_history_apply(patient_id):
    if patient_id is not None: raise ValueError('batch job takes no patient')
    with connection() as conn:
        plan = record_store.get_json(conn, record_store.GLOBAL_PATIENT, 'history-import-plan.json')
        if plan is None:
            plan = json.loads((Path(db.DATA_DIR) / 'history-import-plan.json').read_text(encoding='utf-8'))
        count = history.apply(conn, plan)
    return json.dumps({'visits_added': count})


JOBS = {'import_history': import_history, 'import_history_apply': import_history_apply, 'intake_dry': intake_dry, 'intake_apply': intake_apply, 'register_xlsx': register_xlsx, 'interview_sheet': interview_pack, 'interview_pack': interview_pack, 'interview_assist': interview_assist, 'report_extract': report_extract, 'report_start': report_start, 'report_assist': report_assist, 'report_build': report_build, 'report_draft': report_draft}


# The service owns one worker; jobs remain fixed callables and never accept commands from the API.
_wakeup = threading.Event()
_stop_worker = threading.Event()
_worker_lock = threading.Lock()
_worker = None

def enqueue(conn, name, patient_id=None, flow=False, fmt='docx'):
    task_id = uuid.uuid4().hex
    try:
        conn.execute("INSERT INTO tasks(id,patient_id,step,state,created,flow,format) VALUES (?,?,?,'queued',?,?,?)", (task_id, patient_id, name, db.now(), int(flow), fmt))
        conn.commit()
    except db.sqlite3.IntegrityError:
        conn.rollback()
        return None
    _wakeup.set()
    return task_id

def start(name, patient_id=None, conn=None, fmt='docx'):
    if fmt not in ('docx', 'pdf', 'both') or (fmt != 'docx' and name not in ('interview_pack', 'interview_sheet', 'report_build')): raise ValueError('invalid format')
    if not isinstance(name, str) or name not in JOBS: raise ValueError('unknown job name')
    patient_jobs = ('interview_sheet', 'interview_pack', 'interview_assist', 'report_extract', 'report_start', 'report_assist', 'report_build', 'report_draft')
    if name in patient_jobs and (not isinstance(patient_id, int) or isinstance(patient_id, bool)): raise ValueError(name + ' needs patient_id')
    if name not in patient_jobs and patient_id is not None: raise ValueError('patient_id is not used by this job')
    owned = conn is None
    conn = conn or db.connect()
    try:
        if patient_id is not None and not conn.execute('SELECT 1 FROM patients WHERE id=?', (patient_id,)).fetchone(): raise ValueError('patient not found')
        import steps
        if steps.ai_off(name, conn): raise ValueError('AI assist is off in Settings')
        task_id = enqueue(conn, name, patient_id, fmt=fmt)
        if not task_id: raise ValueError('task already queued, running or waiting')
        ensure_worker()
        return task_id
    finally:
        if owned: conn.close()

def get(job_id):
    with connection() as conn:
        row = conn.execute('SELECT state,output FROM tasks WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None

def ensure_worker(recover=False):
    global _worker
    with _worker_lock:
        if _worker and _worker.is_alive(): return
        _stop_worker.clear()
        if recover:
            with connection() as conn:
                conn.execute("UPDATE tasks SET state='failed', output=CASE WHEN step IN ('interview_assist','report_draft','report_assist') THEN 'interrupted' || char(10) || 'AI step failed. Continue manually.' ELSE 'interrupted' END, finished=? WHERE state='running'", (db.now(),))
        _worker = threading.Thread(target=_work, daemon=True)
        _worker.start()

def advance(conn, pid, after=-1, fmt='docx'):
    import steps, settings
    p = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    if not p: return None
    # A manual visit/sign-off/report-sent boundary prevents the flow from guessing actions.
    candidates = steps.FLOW[after + 1:]
    for step in candidates:
        if steps.ai_off(step.name, conn) or (step.name == 'report_assist' and not settings.get(conn, 'flow_includes_ai_assist')): continue
        if step.done(conn, p): continue
        ok, reason = step.ready(conn, p)
        if ok:
            return enqueue(conn, step.name, pid, True, fmt)
        if reason in ('visit not recorded', 'patient is not awaiting report', 'report not marked sent', 'confirm the medicine list first', 'save the interview form first', 'run the eMIMS interaction check first', 'add at least one finding', 'invalid report spec'): break
    return None

def _work():
    import steps
    while not _stop_worker.is_set():
        with connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                step = steps.BY_NAME.get(row['step'])
                browser = step and step.runs_in in ('mhr', 'emims', 'ppa')
                changed = conn.execute("UPDATE tasks SET state=?,waiting_for=?,started=? WHERE id=? AND state='queued'", ('waiting' if browser else 'running', step.runs_in if browser else None, db.now(), row['id'])).rowcount
                conn.commit()
                if not changed: continue
                if browser: continue
                try:
                    if steps.ai_off(row['step'], conn): raise ValueError('AI assist is off in Settings')
                    output = (JOBS[row['step']](row['patient_id'], row['format']) if row['step'] in ('interview_pack', 'interview_sheet') else JOBS[row['step']](row['patient_id'], row['format'] == 'pdf') if row['step'] == 'report_build' else JOBS[row['step']](row['patient_id'])) or ''
                    state = 'done'
                except Exception as exc:
                    output, state = str(exc), 'failed'
                    if step and step.runs_in == 'ai': output += '\nAI step failed. Continue manually.'
                conn.execute('UPDATE tasks SET state=?,output=?,finished=? WHERE id=?', (state, '\n'.join(str(output).splitlines()[-200:]), db.now(), row['id']))
                conn.commit()
                if state == 'done' and row['flow']:
                    index = next(i for i, step in enumerate(steps.FLOW) if step.name == row['step'])
                    advance(conn, row['patient_id'], index, row['format'])
                continue
        _wakeup.wait(0.5)
        _wakeup.clear()
