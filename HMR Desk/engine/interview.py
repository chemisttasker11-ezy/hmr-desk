import datetime as dt
import hashlib
from contextlib import contextmanager
import threading
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import clinical_review
import db
import jobs
import records
import referral
import settings

TEXT = ('notes', 'concerns', 'social', 'mobility', 'exercise', 'alcohol_smoking', 'manages_meds', 'allergies', 'conditions')
TABLES = {'obs': 3, 'meds': 5, 'other_meds': 4, 'pathology': 4}
HEAD = ('name', 'dob', 'age', 'address', 'phone', 'gp', 'visit', 'referral_date', 'pharmacist', 'pharmacist_phone', 'pharmacist_credential')
DETAIL_FIELDS = ('manager', 'manager_details', 'daa', 'daa_type', 'daa_pharmacy', 'smoking', 'alcohol', 'alcohol_details', 'height_referral', 'height_actual', 'weight_referral', 'weight_actual', 'bmi_referral', 'bmi_actual', 'reason')
DETAIL_CHOICES = {'manager': ('', 'self', 'other', 'unknown'), 'daa': ('', 'yes', 'no', 'unknown'), 'daa_type': ('', 'sachets', 'webster', 'other'), 'smoking': ('', 'never', 'current', 'ex', 'unknown'), 'alcohol': ('', 'yes', 'no', 'unknown')}
SYMPTOMS = {'sx_falls': 'Falls in the last 12 months', 'sx_dizziness': 'Dizziness on standing', 'sx_drowsiness': 'Drowsiness', 'sx_pain': 'Pain', 'sx_sleep': 'Sleep problems', 'sx_bowel': 'Bowel problems', 'sx_bladder': 'Bladder problems', 'sx_mood': 'Low mood or anxiety', 'sx_memory': 'Memory problems', 'sx_appetite': 'Appetite or weight change'}
NEW_FIELDS = ('present', 'present_details', 'lives', 'missed_doses', 'missed_doses_details', 'device_technique', 'device_technique_details', 'swallowing', 'swallowing_details', 'recent_change', 'recent_change_details', 'smoking_details', 'home_bp', 'home_bgl', *SYMPTOMS, *(k + '_details' for k in SYMPTOMS))
DETAIL_FIELDS += NEW_FIELDS
DETAIL_CHOICES.update({'present': ('', 'alone', 'with_other'), 'lives': ('', 'alone', 'partner', 'family', 'other'), 'missed_doses': ('', 'none', 'sometimes', 'often', 'not_asked'), 'device_technique': ('', 'ok', 'issues', 'none', 'not_checked'), 'swallowing': ('', 'no', 'yes', 'not_asked'), 'recent_change': ('', 'no', 'yes', 'not_asked'), **{k: ('', 'no', 'yes', 'not_asked') for k in SYMPTOMS}})
def empty_details():
    return {'version': 1, **{k: '' for k in DETAIL_FIELDS}, 'height_as_listed': False, 'weight_as_listed': False, 'bmi_as_listed': False, 'meds': []}

def details_text(data):
    d = data.get('details') or empty_details()
    labels = {'manager': 'Medicine management', 'manager_details': 'Manager details', 'daa': 'DAA', 'daa_type': 'DAA type', 'daa_pharmacy': 'DAA pharmacy / details', 'smoking': 'Smoking', 'smoking_details': 'Smoking details', 'alcohol': 'Alcohol', 'alcohol_details': 'Alcohol details', 'present': 'Present at the visit', 'present_details': 'Who was present', 'lives': 'Lives', 'missed_doses': 'Missed doses', 'device_technique': 'Inhaler / device technique', 'swallowing': 'Swallowing problems', 'recent_change': 'Recent hospital or specialist change', 'home_bp': 'Home BP readings', 'home_bgl': 'Home blood glucose readings', **SYMPTOMS}
    labels.update({k + '_details': label + ' details' for k, label in list(labels.items()) if k in ('missed_doses', 'device_technique', 'swallowing', 'recent_change', *SYMPTOMS)})
    lines = [label + ': ' + CHOICE_LABELS.get(k, {}).get(d.get(k), d.get(k, '')) for k, label in labels.items() if d.get(k)]
    for name in ('height', 'weight', 'bmi'):
        if d[name + '_referral'] or d[name + '_actual'] or d[name + '_as_listed']:
            lines.append(name.title() + ': referral ' + d[name + '_referral'] + '; at interview ' + (d[name + '_referral'] + ' (as listed)' if d[name + '_as_listed'] else d[name + '_actual']))
    return '\n'.join(lines)

def medicine_rows(data):
    rows = [r[:] for r in data['meds']]
    for i, meta in enumerate((data.get('details') or {}).get('meds', [])):
        if i < len(rows):
            rows[i][4] = '\n'.join(filter(None, (rows[i][4], 'DAA: ' + meta['packed'] if meta['packed'] else '', use_text(meta), reference_text(meta), 'How often used: ' + meta['prn_use'] if meta.get('prn_use') else '')))
    return rows

USE_REASONS = ('', 'finished_course', 'stopped_gp', 'stopped_specialist', 'self_ceased', 'ran_out_of_scripts', 'side_effects', 'other', 'unknown')
USE_LABELS = {'finished_course': 'Finished course', 'stopped_gp': 'Stopped by GP', 'stopped_specialist': 'Stopped by specialist', 'self_ceased': 'Self ceased', 'ran_out_of_scripts': 'Ran out of scripts', 'side_effects': 'Side effects', 'other': 'Other', 'unknown': 'Unknown'}
CHOICE_LABELS = {'manager': {'self': 'Patient', 'other': 'Someone else', 'unknown': 'Unknown'}, 'daa': {'yes': 'Yes', 'no': 'No', 'unknown': 'Unknown'}, 'daa_type': {'sachets': 'Sachets', 'webster': 'Webster pack', 'other': 'Other'}, 'smoking': {'never': 'Never smoked', 'current': 'Current smoker', 'ex': 'Ex-smoker', 'unknown': 'Unknown'}, 'alcohol': {'yes': 'Drinks alcohol', 'no': 'No alcohol', 'unknown': 'Unknown'}, 'present': {'alone': 'Patient alone', 'with_other': 'With carer or family'}, 'lives': {'alone': 'Alone', 'partner': 'With partner', 'family': 'With family', 'other': 'Other'}, 'missed_doses': {'none': 'None', 'sometimes': 'Sometimes', 'often': 'Often', 'not_asked': 'Not asked'}, 'device_technique': {'ok': 'OK', 'issues': 'Issues', 'none': 'No devices', 'not_checked': 'Not checked'}, 'swallowing': {'no': 'No', 'yes': 'Yes', 'not_asked': 'Not asked'}, 'recent_change': {'no': 'No', 'yes': 'Yes', 'not_asked': 'Not asked'}, **{k: {'no': 'No', 'yes': 'Yes', 'not_asked': 'Not asked'} for k in SYMPTOMS}, 'kind': {'prescribed': 'Prescribed elsewhere', 'otc': 'Over the counter', 'complementary': 'Complementary or vitamin'}}
def use_text(meta):
    status = meta.get('use_status', '')
    if not status: return ''
    text = {'taking': 'Taking', 'not_using': 'Not using', 'unknown': 'Not yet confirmed'}[status]
    if status == 'not_using' and meta.get('use_reason'): text += ' — ' + USE_LABELS[meta['use_reason']]
    if status == 'not_using' and meta.get('use_details'): text += ': ' + meta['use_details']
    return text

REFERENCE_KEYS = {'source', 'code', 'display', 'release'}

def valid_reference(ref):
    return isinstance(ref, dict) and set(ref) == REFERENCE_KEYS and all(isinstance(v, str) and 0 < len(v) <= 400 for v in ref.values())

def reference_text(meta):
    ref = (meta or {}).get('reference')
    return 'Reference: ' + ref['display'] + ' (' + ref['source'].upper() + ' ' + ref['code'] + ', release ' + ref['release'] + ')' if valid_reference(ref) else ''

def valid_use(m, base, optional):
    if 'reference' in m:
        if not valid_reference(m['reference']): return False
        m = {k: v for k, v in m.items() if k != 'reference'}
    if any(k in m and (not isinstance(m[k], str) or len(m[k]) > 20000 or (k == 'kind' and m[k] not in ('', 'prescribed', 'otc', 'complementary'))) for k in optional): return False
    m = {k: v for k, v in m.items() if k not in optional}
    extra = {'use_status', 'use_reason', 'use_details'}
    if set(m) not in (base, base | extra): return False
    return not (extra <= set(m)) or (m['use_status'] in ('', 'taking', 'not_using', 'unknown') and m['use_reason'] in USE_REASONS and isinstance(m['use_details'], str) and len(m['use_details']) <= 20000)

def referral_text(folder):
    clarify = []
    files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == '.pdf' and not f.name.lower().startswith(('ppa consent - ', 'hmr interview - ')))
    files = [f for f in files if re.search(r'_ [A-Z]{2,4}\.pdf$', f.name)] or [f for f in files if 'referral' in f.name.lower()]
    if files:
        specmod = importlib.util.spec_from_file_location('hmr_intake', __import__('app_paths').resource_root() / 'scripts' / 'intake' / 'intake.py')
        module = importlib.util.module_from_spec(specmod); specmod.loader.exec_module(module)
        with module.fitz.open(files[0]) as doc: pages = [page.get_text() for page in doc]
        if any(len(t.strip()) < 200 for t in pages):
            try:
                ocr = module.ocr_pdfs([files[0]]).get(str(files[0]), [])
                if len(ocr) != len(pages): raise ValueError('OCR page count mismatch')
                pages = [t if len(t.strip()) >= 200 else ocr[i] for i, t in enumerate(pages)]
            except Exception:
                clarify.append('Referral is a scan; OCR failed - check by eye')
        text = '\f'.join(pages)
        return text, clarify
    return None, clarify

def blank(conn, patient):
    p = dict(patient); folder = jobs.patient_folder(patient)
    header = {k: str(p.get(k) or '') for k in HEAD}
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            born = dt.datetime.strptime(header['dob'][:10], fmt).date()
            today = dt.date.today(); header['age'] = str(today.year - born.year - ((today.month, today.day) < (born.month, born.day)))
            break
        except ValueError: pass
    header['visit'] = ' '.join(filter(None, (p.get('visit_date'), p.get('visit_time'))))
    for key, setting in [('pharmacist', 'pharmacist_name'), ('pharmacist_phone', 'pharmacist_phone'), ('pharmacist_credential', 'pharmacist_credential')]: header[key] = settings.get(conn, setting)
    record = {'header': header, **{k: '' for k in TEXT}, 'obs': [[x, '', ''] for x in ('Height / weight / BMI', 'BP sitting / standing', 'Pulse', 'Renal function')], 'meds': [], 'other_meds': [], 'pathology': [], 'clarify': [], 'consent': {'signed': False, 'date': '', 'by': 'patient', 'relationship': 0, 'authorised_name': ''}, 'sources': []}
    # Preserve the form's section order in JSON as well as in the export.
    record = {k: record[k] for k in ('header', 'notes', 'concerns', 'social', 'mobility', 'exercise', 'alcohol_smoking', 'manages_meds', 'allergies', 'obs', 'conditions', 'meds', 'other_meds', 'pathology', 'clarify', 'consent', 'sources')}
    path = folder / 'Pathology'
    if path.is_dir():
        for f in sorted(path.glob('*.pdf')):
            m = re.match(r'^(\d{2,4}[-./]\d{1,2}[-./]\d{2,4})\s+(.+)$', f.stem)
            if m: record['pathology'].append([m[2], '', m[1], ''])
        if record['pathology']: record['sources'].append('Pathology file names - check')
    spec = jobs.interview_spec_path(patient)
    text, clarify = referral_text(folder)
    found = referral.parse(text) if text is not None else None
    record['clarify'].extend(clarify)
    if spec.is_file():
        data = json.loads(spec.read_text(encoding='utf-8-sig'))
        for k in TEXT:
            source = 'alcohol' if k == 'alcohol_smoking' else k
            if isinstance(data.get(source), str): record[k] = data[source]
        for k in HEAD:
            if not record['header'][k] and data.get(k) is not None: record['header'][k] = str(data[k])
        for idx, key in ((0, 'obs_from_referral'), (3, 'renal')): record['obs'][idx][1] = str(data.get(key) or '')
        record['meds'] = [[str(x) for x in (r[0], r[1], '', r[2], '')] for r in data.get('meds', []) if isinstance(r, list) and len(r) >= 3]
        if data.get('pathology'): record['pathology'] = [[str(x or '') for x in r] for r in data['pathology'] if isinstance(r, list) and len(r) == 4]
        record['clarify'].extend(str(x) for x in data.get('clarify', []))
        record['sources'].append('From previous interview spec - check')
    else:
        if found is not None:
            record['meds'] = [[name, directions, '', '', ''] for name, directions in found['meds']]
            for k in ('conditions', 'allergies'): record[k] = '\n'.join(found[k])
            obs = found['obs']
            record['obs'][0][1] = '; '.join(k.title() + ': ' + obs[k] for k in ('height', 'weight', 'bmi') if obs[k])
            record['details'] = empty_details()
            for k in ('height', 'weight', 'bmi'): record['details'][k + '_referral'] = obs[k]
            record['obs'][1][1] = obs['bp']
            record['obs'][3][1] = found['renal']
            record['alcohol_smoking'] = '\n'.join(k.title() + ': ' + found[k] for k in ('alcohol', 'smoking') if found[k])
            record['social'] = found['social']
            record['clarify'].extend('Referral section not fully read: ' + k for k in found['unparsed'])
            for k in ('meds', 'conditions', 'allergies', 'obs', 'alcohol_smoking', 'social', 'renal'):
                value = found['renal'] if k == 'renal' else record[k] if k != 'obs' else any(obs.values())
                if value: record['sources'].append(k + ' from referral - check')
    if 'details' not in record: record['details'] = empty_details()
    if found is not None:
        record['details']['reason'] = found['reason']
        names = {r[0].strip().casefold() for r in record['meds']}
        ceased = []
        for name in found['ceased']:
            if name.strip().casefold() not in names:
                record['meds'].append([name, '', '', '', '']); ceased.append(len(record['meds']) - 1); names.add(name.strip().casefold())
    record['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in record['meds']]
    if found is not None:
        for i in ceased: record['details']['meds'][i].update(use_status='not_using', use_reason='', use_details='Ceased per referral')
    # Clinical fields entered at intake are not automatically promoted unless
    # a named pharmacist confirmed them against an exact original PDF page.
    reviewed_source = folder / 'referral_source.json'
    if reviewed_source.is_file():
        reviewed = json.loads(reviewed_source.read_text(encoding='utf-8')).get('clinical_review', {})
        if clinical_review.is_reviewed(reviewed):
            reviewer = reviewed.get('reviewed_by', '')
            # Each fact cites its own original PDF page.
            if reviewed.get('conditions'):
                origin = clinical_review.origin(reviewed, 'conditions')
                record['conditions'] = reviewed['conditions']
                record['sources'].append('Conditions confirmed: ' + origin + '; ' + reviewer)
            allergy_state = reviewed.get('allergies_status', 'unknown')
            origin = clinical_review.origin(reviewed, 'allergies')
            if allergy_state == 'explicit_none':
                record['allergies'] = 'No known allergies — explicitly documented in ' + origin
                record['sources'].append('Allergy negative confirmed: ' + origin + '; ' + reviewer)
            elif allergy_state == 'listed' and reviewed.get('allergies'):
                record['allergies'] = reviewed['allergies']
                record['sources'].append('Allergies confirmed: ' + origin + '; ' + reviewer)
            if reviewed.get('medicines'):
                origin = clinical_review.origin(reviewed, 'medicines')
                record['clarify'].append('Confirmed prescribed referral list from ' + origin +
                                         ' (actual use still to reconcile): ' + reviewed['medicines'][:9000])
            if reviewed.get('observations'):
                origin = clinical_review.origin(reviewed, 'observations')
                record['obs'].append(['Referral observation', reviewed['observations'], origin])
        elif any(reviewed.get(k) for k in ('conditions','medicines','observations','allergies')):
            record['clarify'].append('Unconfirmed source material was entered during intake; review original PDF')
    return record

class Conflict(Exception):
    pass


def revision(conn, patient):
    """Conflict token for the saved interview record (sha256 of its exact bytes, or 'missing')."""
    return records.revision(conn, patient['id'], 'interview.json')


_lock = threading.RLock()

@contextmanager
def record_lock(patient):
    # The lock file remains stable across atomic replacement of interview.json.
    with _lock, (jobs.patient_folder(patient) / '.interview.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try: yield
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(lock, fcntl.LOCK_UN)


def validate(record):
    keys = {'header', *TEXT, *TABLES, 'clarify', 'consent', 'sources'}
    if not isinstance(record, dict) or set(record) - {'saved', 'consent_file', 'details', 'revision', 'consent_signed_draft'} != keys: raise ValueError('invalid interview fields')
    def string(x): return isinstance(x, str) and len(x) <= 20000
    if not isinstance(record['header'], dict) or set(record['header']) != set(HEAD) or not all(string(x) for x in record['header'].values()): raise ValueError('invalid header')
    if not all(string(record[k]) for k in TEXT): raise ValueError('invalid text field')
    for k, width in TABLES.items():
        rows = record[k]
        if not isinstance(rows, list) or len(rows) > 80 or any(not isinstance(r, list) or len(r) != width or not all(string(x) for x in r) for r in rows): raise ValueError('invalid ' + k)
    for k in ('clarify', 'sources'):
        if not isinstance(record[k], list) or len(record[k]) > 80 or not all(string(x) for x in record[k]): raise ValueError('invalid ' + k)
    c = record['consent']
    if not isinstance(c, dict) or set(c) != {'signed', 'date', 'by', 'relationship', 'authorised_name'} or type(c['signed']) is not bool or not string(c['date']) or c['by'] not in ('patient', 'authorised') or type(c['relationship']) is not int or c['relationship'] not in range(6) or not string(c['authorised_name']) or (c['signed'] and c['by'] == 'authorised' and (not c['relationship'] or not c['authorised_name'].strip())): raise ValueError('invalid consent')
    if 'details' in record:
        d = record['details']
        if isinstance(d, dict):
            for k in NEW_FIELDS: d.setdefault(k, '')
        expected = {'version', *DETAIL_FIELDS, 'height_as_listed', 'weight_as_listed', 'bmi_as_listed', 'meds', 'other_meds'}
        if not isinstance(d, dict) or set(d) - {'other_meds', 'reason'} != expected - {'other_meds', 'reason'} or type(d['version']) is not int or d['version'] != 1 or not all(string(d.get(k, '') if k == 'reason' else d[k]) for k in DETAIL_FIELDS) or any(d[k] not in choices for k, choices in DETAIL_CHOICES.items()) or not all(type(d[k + '_as_listed']) is bool for k in ('height', 'weight', 'bmi')): raise ValueError('invalid interview details')
        if not isinstance(d['meds'], list) or len(d['meds']) != len(record['meds']) or any(not isinstance(m, dict) or not (valid_use(m, {'packed', 'as_instructed'}, {'prn_use'}) or valid_use(m, {'packed', 'as_instructed', 'checked', 'priority'}, {'prn_use'})) or ('checked' in m and (type(m['checked']) is not bool or type(m['priority']) is not int or not 0 <= m['priority'] <= 1000000)) or m['packed'] not in ('', 'packed', 'not packed', 'unknown') or type(m['as_instructed']) is not bool for m in d['meds']): raise ValueError('invalid medicine details')
        if 'other_meds' in d and (not isinstance(d['other_meds'], list) or len(d['other_meds']) != len(record['other_meds']) or any(not isinstance(m, dict) or not valid_use(m, {'checked', 'priority'}, {'kind'}) or type(m['checked']) is not bool or type(m['priority']) is not int or not 0 <= m['priority'] <= 1000000 for m in d['other_meds'])): raise ValueError('invalid other medicine details')
        for key, field in (('meds', 'prn_use'), ('other_meds', 'kind')):
            for m in d.get(key, []): m.setdefault(field, '')
    if 'consent_signed_draft' in record and (type(record['consent_signed_draft']) is not bool or (record['consent_signed_draft'] and c['signed'])): raise ValueError('invalid consent draft')
    if 'revision' in record and (not isinstance(record['revision'], str) or not re.fullmatch(r'missing|[0-9a-f]{64}', record['revision'])): raise ValueError('invalid revision')
    if 'saved' in record and not isinstance(record['saved'], bool): raise ValueError('invalid saved flag')
    if 'consent_file' in record and not string(record['consent_file']): raise ValueError('invalid consent file')

def signed_file(folder):
    return sorted(f.name for f in folder.iterdir() if f.is_file() and 'signed' in f.name.lower())

def load(conn, patient):
    folder = jobs.patient_folder(patient)
    content = records.get(conn, patient['id'], 'interview.json')
    data = json.loads(content) if content is not None else blank(conn, patient)
    data['revision'] = hashlib.sha256(content).hexdigest() if content is not None else 'missing'
    if 'details' not in data:
        data['details'] = empty_details()
        data['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in data.get('meds', [])]
    if isinstance(data['details'], dict) and isinstance(data['details'].get('meds'), list):
        for m in data['details']['meds']:
            if isinstance(m, dict) and set(m) == {'packed', 'as_instructed'}: m.update(checked=False, priority=0)
    if isinstance(data['details'], dict) and 'other_meds' not in data['details']: data['details']['other_meds'] = [{'checked': False, 'priority': 0} for _ in data.get('other_meds', [])]
    if isinstance(data['details'], dict):
        data['details'].setdefault('reason', '')
        for k in NEW_FIELDS: data['details'].setdefault(k, '')
        for key in ('meds', 'other_meds'):
            for m in data['details'].get(key, []) if isinstance(data['details'].get(key), list) else []:
                if isinstance(m, dict):
                    if not any(k in m for k in ('use_status', 'use_reason', 'use_details')): m.update(use_status='', use_reason='', use_details='')
                    m.setdefault('prn_use' if key == 'meds' else 'kind', '')
    if isinstance(data.get('consent'), dict):
        for key, value in [('by', 'patient'), ('relationship', 0), ('authorised_name', '')]: data['consent'].setdefault(key, value)
    if isinstance(data.get('header'), dict):
        for key, setting in [('pharmacist', 'pharmacist_name'), ('pharmacist_phone', 'pharmacist_phone'), ('pharmacist_credential', 'pharmacist_credential')]: data['header'][key] = settings.get(conn, setting)
    validate(data); data['saved'] = content is not None
    signed = signed_file(folder)
    data['consent_file'] = signed[0] if signed else ''
    return data

def save(conn, patient, record, *, locked=False, signing=False):
    if not locked:
        with record_lock(patient):
            folder = jobs.patient_folder(patient)
            name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
            # The interview records live in the encrypted database and roll back with the transaction.
            # Only the consent PDF is still an ordinary file, so it is restored by hand.
            pdf = folder / ('PPA Consent - ' + name + '.pdf')
            pdf_original = pdf.read_bytes() if pdf.exists() else None
            old_revision = record.get('revision') if isinstance(record, dict) else None
            try:
                result = save(conn, patient, record, locked=True, signing=signing)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                if not (pdf.exists() and pdf_original is not None and pdf.read_bytes() == pdf_original):
                    if pdf_original is None:
                        pdf.unlink(missing_ok=True)
                    else:
                        fd, temp = tempfile.mkstemp(dir=folder)
                        try:
                            with os.fdopen(fd, 'wb') as out: out.write(pdf_original)
                            os.replace(temp, pdf)
                        finally:
                            if os.path.exists(temp): os.unlink(temp)
                if isinstance(record, dict) and old_revision is not None: record['revision'] = old_revision
                raise
    validate(record); data = {k: v for k, v in record.items() if k not in ('saved', 'consent_file', 'revision')}
    folder = jobs.patient_folder(patient)
    previous_bytes = records.get(conn, patient['id'], 'interview.json')
    if record.get('revision') != records.digest(previous_bytes): raise Conflict('interview conflict')
    previous = json.loads(previous_bytes.decode('utf-8')) if previous_bytes is not None else {}
    was_signed = previous.get('consent', {}).get('signed') is True
    if not signing and was_signed and signed_file(folder) and (data['consent'] != previous['consent'] or data.get('consent_signed_draft', False)): raise ValueError('signed consent cannot be changed')
    if previous_bytes is not None:
        records.put(conn, patient['id'], 'interview.json.bak', previous_bytes)
    records.put(conn, patient['id'], 'interview.json', json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    record['revision'] = revision(conn, patient)
    name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
    consent_path = folder / ('PPA Consent - ' + name + '.pdf')
    if consent_path.exists() and not was_signed and not data['consent']['signed'] and not signed_file(folder): fill_consent(conn, patient, data, consent_path)
    conn.execute('UPDATE patients SET has_sheet=1,updated_at=? WHERE id=?', (db.now(), patient['id']))
    db.log(conn, patient['id'], 'interview_saved', {}, 'api')
    if data['consent']['signed'] and not was_signed: db.log(conn, patient['id'], 'consent_signed', {'date': data['consent']['date']}, 'api')
    return {**data, 'saved': True, 'revision': record['revision']}

def available(folder, stem, suffixes):
    stem = re.sub(r'[<>:"/\\|?*]', '', stem).rstrip(' .')
    candidate = stem; n = 1
    while any((folder / (candidate + s)).exists() for s in suffixes):
        candidate = stem + ' ' + dt.datetime.now().strftime('%H%M') + (f' {n}' if n > 1 else ''); n += 1
    return candidate

def export(conn, patient, fmt):
    if fmt not in ('docx', 'pdf', 'both'): raise ValueError('invalid format')
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.enum.section import WD_ORIENT
    data = load(conn, patient); folder = jobs.patient_folder(patient)
    if data.get('consent_signed_draft'): raise ValueError('complete authorised person name and relationship before export')
    stem = available(folder, 'HMR Interview - ' + patient['name'], ('.docx', '.pdf'))
    target = folder / (stem + '.docx')
    doc = Document(); sec = doc.sections[0]; sec.orientation = WD_ORIENT.LANDSCAPE; sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for m in ('left_margin', 'right_margin', 'top_margin', 'bottom_margin'): setattr(sec, m, Cm(1.5))
    doc.styles['Normal'].font.name = 'Calibri'; doc.styles['Normal'].font.size = Pt(10)
    doc.add_heading('HMR Interview - ' + data['header']['name'], 1)
    labels = dict(zip(HEAD, ('Name', 'DOB', 'Age', 'Address', 'Phone', 'GP', 'Visit', 'Referral date', 'Pharmacist', 'Pharmacist phone', 'Credential')))
    for k, v in data['header'].items():
        if k in ('dob', 'visit') and re.match(r'^\d{4}-\d{2}-\d{2}' + (r'(?: |$)' if k == 'visit' else r'$'), v):
            try: v = dt.date.fromisoformat(v[:10]).strftime('%d/%m/%Y') + v[10:]
            except ValueError: pass
        doc.add_paragraph(labels[k] + ': ' + v)
    def section(title, value, lines=2):
        doc.add_heading(title, 2)
        if value: doc.add_paragraph(value)
        else:
            for _ in range(lines): doc.add_paragraph('_' * 110)
    def table(title, headers, rows, spare):
        doc.add_heading(title, 2); t = doc.add_table(rows=1, cols=len(headers)); t.style = 'Table Grid'
        for cell, label in zip(t.rows[0].cells, headers): cell.text = label; cell.paragraphs[0].runs[0].bold = True
        for row in rows + [[''] * len(headers) for _ in range(spare)]:
            for cell, val in zip(t.add_row().cells, row): cell.text = val
    for k, title in [('notes','Interview notes'), ('concerns', "Patient's concerns / goals"), ('social','Social status'), ('mobility','Mobility'), ('exercise','Exercise'), ('alcohol_smoking','Alcohol / smoking'), ('manages_meds','Who manages medicines, DAA, devices'), ('allergies','Allergies / adverse reactions')]: section(title, data[k], 6 if k == 'notes' else 2)
    if details_text(data): section('Interview details', details_text(data))
    table('Observations', ['Measure','Referral','At interview'], data['obs'], 1)
    section('Current conditions', data['conditions'])
    table('Medicines on referral', ['Medicine','Referral directions','Actually taking','Points to check','Notes'], medicine_rows(data), 3)
    other_rows = [r[:] for r in data['other_meds']]
    for i, meta in enumerate(data['details'].get('other_meds', [])):
        if i < len(other_rows): other_rows[i][3] = '\n'.join(filter(None, (other_rows[i][3], use_text(meta), CHOICE_LABELS['kind'].get(meta.get('kind'), ''), reference_text(meta))))
    table('Other medicines found', ['Medicine','Directions','Why / who','Notes'], other_rows, 3)
    table('Pathology on file', ['Test','Result','Date','Comment'], data['pathology'], 2)
    section('To clarify', '\n'.join(data['clarify']))
    section('PPA consent', 'Signed: ' + ('Yes' if data['consent']['signed'] else 'No') + '    Date: ' + data['consent']['date'])
    with target.open('xb') as f: doc.save(f)
    if fmt in ('pdf', 'both'):
        import pdf_export
        pdf_export.convert(target, folder / (stem + '.pdf'))
    return str(target)

def consent_template():
    for ext in ('.pdf', '.docx'):
        p = Path(db.BASE) / 'TEMPLATES' / ('PPA Consent' + ext)
        if p.is_file(): return p
    return None

def pack(conn, patient, fmt='docx'):
    record = load(conn, patient)
    if not record['saved']: save(conn, patient, record)
    output = 'Interview: ' + export(conn, patient, fmt)
    folder = jobs.patient_folder(patient); name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
    if record['consent']['signed'] or signed_file(folder): return output + '\nSigned consent kept'
    template = consent_template()
    if not template: return output + '\nPPA consent form not added: put it at TEMPLATES\\PPA Consent.pdf or .docx'
    target = folder / ('PPA Consent - ' + name + template.suffix.lower())
    if template.suffix.lower() == '.pdf':
        fill_consent(conn, patient, record, target)
    else:
        from docx import Document
        if target.exists(): return output + '\nExisting consent form kept'
        doc = Document(template); fields = dict(record['header']); fields['medicare'] = patient['medicare'] or ''; fields['date'] = dt.date.today().strftime('%d/%m/%Y')
        def paragraphs(container):
            yield from container.paragraphs
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells: yield from paragraphs(cell)
        all_paragraphs = list(paragraphs(doc))
        for section in doc.sections:
            all_paragraphs.extend(paragraphs(section.header)); all_paragraphs.extend(paragraphs(section.footer))
        for para in all_paragraphs:
            text = para.text
            for key, value in fields.items(): text = text.replace('{{' + key + '}}', value)
            if text != para.text:
                if para.runs:
                    para.runs[0].text = text
                    for run in para.runs[1:]: run.text = ''
                else: para.add_run(text)
        with target.open('xb') as f: doc.save(f)
    return output + '\nConsent: ' + str(target)


def fill_consent(conn, patient, record, target):
    import fitz
    template = consent_template()
    if not template or template.suffix.lower() != '.pdf': return
    visit = str(dict(patient).get('visit_date') or '')
    try: date = dt.date.fromisoformat(visit[:10]).strftime('%d/%m/%Y')
    except ValueError:
        try: date = dt.datetime.strptime(visit[:10], '%d/%m/%Y').strftime('%d/%m/%Y')
        except ValueError: date = ''
    c = record['consent']; authorised = c['by'] == 'authorised'
    fields = {'Patient Name Given name and family name': record['header']['name'],
              'Name of Pharmacist Providing Service': settings.get(conn, 'pharmacist_name'),
              'Date of Service': date,  # date only, no visit time (user's choice)
              'Date of Consent': '' if authorised else date,
              'Date of Consent_2': date if authorised else '',
              'Authorised Person Name': c['authorised_name'] if authorised else ''}
    if target.exists():
        try:
            with fitz.open(target) as existing:
                widgets = {w.field_name: (w.field_value, w.text_fontsize) for page in existing for w in page.widgets() or []}
                actual = {name: value for name, (value, _) in widgets.items()}
            if any(actual.get(k) for k in ('Patient signature', 'Authorised Person Signature')): return
            expected = dict(fields, **{'Check Box' + str(i): 'Yes' if authorised and i == c['relationship'] else 'Off' for i in range(1, 6)})
            if all((actual.get(k) or '') == v for k, v in expected.items() if k in actual) and all(widgets[k][1] == 10 for k in fields if k in widgets): return
        except fitz.FileDataError: return
    try:
        with fitz.open(template) as pdf:
            for page in pdf:
                for widget in page.widgets() or []:
                    if widget.field_name in fields:
                        widget.field_value = fields[widget.field_name]; widget.text_fontsize = 10; widget.update()
                    elif widget.field_name in ('Check Box' + str(i) for i in range(1, 6)):
                        widget.field_value = 'Yes' if authorised and widget.field_name == 'Check Box' + str(c['relationship']) else 'Off'; widget.update()
            content = pdf.tobytes()
    except fitz.FileDataError: content = template.read_bytes()
    fd, temp = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as out: out.write(content)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp): os.unlink(temp)
