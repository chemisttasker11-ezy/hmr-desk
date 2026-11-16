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

INTAKE_SCRIPT = Path(db.BASE) / 'scripts' / 'intake' / 'intake.py'
SKILL = Path(os.environ['USERPROFILE']) / '.claude' / 'skills' / 'australian-hmr-report'
EXTRACT_SCRIPT = SKILL / 'scripts' / 'extract.py'
BUILD_SCRIPT = SKILL / 'scripts' / 'build.py'
INTERVIEW_SCRIPT = Path(os.environ['USERPROFILE']) / '.claude' / 'skills' / 'australian-hmr-report' / 'scripts' / 'make_interview.py'
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
    with _lock:
        data = importer.read(path) if path.exists() else {}
        data.setdefault(file, {}).update(fields)
        atomic_json(path, data)


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def run_script(script, *args):
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
    output = run_script(EXTRACT_SCRIPT, folder, images)
    if (folder / 'interview.json').is_file():
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
        p = get_patient(conn, patient_id)
        folder, spec = patient_folder(p), report_spec_path(p)
        if not spec.is_file(): raise FileNotFoundError('Report spec missing: ' + str(spec))
        data = importer.read(spec)
        report.validate(data)
        if not data['issues']: raise ValueError('add at least one finding')
        pending = report.placeholders(data)
        if pending: raise ValueError('Review placeholder fields: ' + ', '.join(pending))
        target = Path(data['out'])
        if not target.is_absolute(): target = folder / target
        target = target.resolve()
        if target.parent != folder or target.suffix.lower() != '.docx': raise ValueError('Report output must be a DOCX in patient folder')
        preview = spec.with_name(spec.stem + '-sheet.png')
        pdf_target = target.with_suffix('.pdf')
        if target.exists() or preview.exists() or (pdf and pdf_target.exists()): raise FileExistsError('Report output or preview already exists')
        if not Path(data['out']).is_absolute(): raise ValueError('Report spec out must be an absolute path')
        output = run_script(BUILD_SCRIPT, spec)
        if not target.is_file(): raise RuntimeError('Report was not created: ' + str(target))
        if pdf:
            try:
                subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SKILL / 'scripts' / 'word2pdf.ps1'), str(target), str(pdf_target)], check=True, capture_output=True, timeout=120)
                if not pdf_target.is_file(): raise RuntimeError('PDF was not created')
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc: raise RuntimeError('PDF conversion failed; DOCX kept at ' + str(target) + ': ' + str(exc)) from exc
        if p['state'] == 'visited' and db.can_move(p['state'], 'report_drafted'):
            db.set_state(conn, patient_id, 'report_drafted', source='job')
        db.log(conn, patient_id, 'report_build', {'file': str(target)}, 'job')
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
            result = subprocess.run(['pdftotext', '-layout', str(file), '-'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
            if result.returncode or not result.stdout.strip(): raise ValueError('Referral PDF has no readable text: ' + file.name)
            parts.append(result.stdout)
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
    # Legacy full-report prompts and skill routes expose identifiable patient files.
    # Keep them unavailable until a clinical-only adapter is implemented.
    import clinical_privacy
    raise clinical_privacy.PrivacyBlocked('Legacy patient-folder AI generation is disabled; use the manual report editor')
    import agents
    with connection() as conn:
        p = get_patient(conn, patient_id)
        folder = patient_folder(p)
        target = output_path or (interview_spec_path(p) if name == 'interview_spec' else report_spec_path(p))
        if target.exists(): raise FileExistsError('Spec already exists: ' + str(target))
    agent = agents.selected('report_assist' if output_path is not None and name == 'report_draft' else name)
    selected = agents.get(agent)
    route = selected['route']
    keys = INTERVIEW_KEYS if name == 'interview_spec' else REPORT_KEYS
    if route == 'skill':
        template = (Path(__file__).parent / 'prompts' / (name + '_skill.txt')).read_text(encoding='utf-8')
        prompt = template.format(folder=str(folder), target=str(target), keys=', '.join(sorted(keys)))
        target.parent.mkdir(parents=True, exist_ok=True)
        reply = agents.skill_run(selected, prompt, Path(db.BASE) if name == 'interview_spec' else folder)
        statuses = [line.strip()[len('HMR-STATUS:'):].strip() for line in reply.splitlines() if line.strip().startswith('HMR-STATUS:')]
        status = statuses[-1] if statuses else ''
        if status != 'success':
            if target.is_file(): target.unlink()
            reason = status[len('blocked - '):].strip() if status.startswith('blocked - ') else 'agent gave no status'
            raise ValueError((reason or 'agent gave no status') + '\n' + '\n'.join(reply.splitlines()[-199:]))
        try:
            spec = json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(spec, dict) or not keys <= spec.keys(): raise ValueError('Spec missing required top-level keys')
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError('Invalid or missing spec: ' + str(exc) + '\n' + '\n'.join(reply.splitlines()[-199:])) from None
        with connection() as conn: db.log(conn, patient_id, name, {'agent': agent, 'route': route, 'file': str(target)}, 'job')
        return 'Spec created by ' + agent + ' (' + route + ')'
    template = (Path(__file__).parent / 'prompts' / (name + '.txt')).read_text(encoding='utf-8')
    rules = '\n\n'.join((SKILL / f).read_text(encoding='utf-8') for f in ('SKILL.md', 'references/report-runbook.md'))
    if name == 'interview_spec':
        source = referral_text(folder)
        pathology = folder / 'Pathology'
        if pathology.is_dir():
            for file in sorted(pathology.iterdir()):
                if file.is_file() and file.suffix.lower() == '.txt':
                    source += '\n\nPathology ' + file.name + ':\n' + file.read_text(encoding='utf-8')
                elif file.is_file() and file.suffix.lower() == '.pdf':
                    result = subprocess.run(['pdftotext', '-layout', str(file), '-'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
                    if not result.returncode and result.stdout.strip(): source += '\n\nPathology ' + file.name + ':\n' + result.stdout
        keys = INTERVIEW_KEYS
    else:
        source = (folder / 'case.txt').read_text(encoding='utf-8')
        keys = REPORT_KEYS
        # Search using frequent words, without passing the full patient extract as command arguments.
        import re
        terms = list(dict.fromkeys(re.findall(r'(?i)\b[a-z]{6,}\b', source)))[:12]
        if terms:
            try: source += '\n\nSimilar cases:\n' + run_script(SKILL / 'scripts' / 'find_cases.py', *terms)
            except (OSError, subprocess.SubprocessError, RuntimeError): pass
    shape = (SKILL / 'scripts' / 'example-spec.json').read_text(encoding='utf-8') if name == 'report_draft' else json.dumps({k: ([] if k in ('meds', 'pathology', 'clarify') else 0 if k == 'age' else '') for k in sorted(keys)})
    prompt = template + '\n\nSpec shape: ' + shape + '\n\nRequired top-level keys: ' + ', '.join(sorted(keys)) + '\nOutput path: ' + str(target) + '\n\nSkill rules:\n' + rules + '\n\nCase source:\n' + source
    reply = agents.run(agent, prompt)
    try:
        spec = json_object(reply)
        if not keys <= spec.keys(): raise ValueError('Agent reply missing required keys: ' + ', '.join(sorted(keys - spec.keys())))
    except (ValueError, TypeError):
        directory = Path(db.DATA_DIR) / 'agent-replies'; directory.mkdir(parents=True, exist_ok=True)
        with (directory / (uuid.uuid4().hex + '.txt')).open('x', encoding='utf-8') as f: f.write(reply)
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as f: json.dump(spec, f, ensure_ascii=False, indent=2)
    with connection() as conn: db.log(conn, patient_id, name, {'agent': agent, 'route': route, 'file': str(target)}, 'job')
    return 'Spec created by ' + agent


def interview_spec(patient_id): return agent_step(patient_id, 'interview_spec')
def report_draft(patient_id): return agent_step(patient_id, 'report_draft')

def report_assist(patient_id):
    import report
    with connection() as conn: folder = patient_folder(get_patient(conn, patient_id))
    target = folder / ('report-assist-' + uuid.uuid4().hex + '.json')
    try:
        output = agent_step(patient_id, 'report_draft', target)
        report.validate(json.loads(target.read_text(encoding='utf-8')))
        os.replace(target, folder / 'report_spec.ai.json')
        with connection() as conn: db.log(conn, patient_id, 'report_assist', {'file': str(folder / 'report_spec.ai.json')}, 'job')
        return output
    finally:
        if target.exists(): target.unlink()

def import_history(patient_id):
    if patient_id is not None: raise ValueError('batch job takes no patient')
    with connection() as conn: records = history.plan(conn)
    atomic_json(Path(db.DATA_DIR) / 'history-import-plan.json', records)
    return json.dumps(history.summary(records), ensure_ascii=False)


def import_history_apply(patient_id):
    if patient_id is not None: raise ValueError('batch job takes no patient')
    records = json.loads((Path(db.DATA_DIR) / 'history-import-plan.json').read_text(encoding='utf-8'))
    with connection() as conn: count = history.apply(conn, records)
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
