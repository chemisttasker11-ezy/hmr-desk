"""Local report editor data and reusable finding search."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

import brainstorm
import db
import interview
import jobs
import records
import manual_defaults
import medicine_snapshot

WIDTHS = {'meds': 4, 'otc': 3, 'ceased': 3, 'path': 5}
REVIEW = ['thanks', 'reason', 'intro', 'followup']
_cache = {}
_lock = threading.RLock()

def validate(data):
    if not isinstance(data, dict) or not jobs.REPORT_KEYS <= data.keys(): raise ValueError('report spec missing required keys')
    for key in jobs.REPORT_KEYS - set(WIDTHS) - {'issues'}:
        if not isinstance(data[key], str): raise ValueError('invalid ' + key)
    for key, width in WIDTHS.items():
        if not isinstance(data[key], list) or any(not isinstance(row, list) or len(row) != width or any(not isinstance(x, str) for x in row) for row in data[key]): raise ValueError('invalid ' + key + ' rows')
    if not isinstance(data['issues'], list) or any(not isinstance(i, dict) or any(not isinstance(i.get(k), str) or not i[k].strip() for k in ('title', 'rec', 'rationale')) for i in data['issues']): raise ValueError('invalid issues')
    for issue in data['issues']:
        if 'suggestion_source' not in issue: continue
        origin = issue['suggestion_source']
        if (not isinstance(origin, dict) or set(origin) != {'version','context_snapshot_sha256','evidence'} or
            origin['version'] != 1 or not isinstance(origin['context_snapshot_sha256'],str) or
            not re.fullmatch('[a-f0-9]{64}',origin['context_snapshot_sha256']) or
            not isinstance(origin['evidence'],list) or len(origin['evidence']) > 500 or
            any(not isinstance(e,dict) or not isinstance(e.get('id'),str) or not isinstance(e.get('text'),str) for e in origin['evidence']) or
            len(json.dumps(origin,ensure_ascii=False)) > 2000000):
            raise ValueError('invalid suggestion source evidence')
    if 'followup_decision' in data and data['followup_decision'] not in manual_defaults.DECISIONS: raise ValueError('invalid followup_decision')
    if 'followup_text_reviewed' in data and not isinstance(data['followup_text_reviewed'], bool): raise ValueError('invalid followup_text_reviewed')
    if 'followup_reviewed_sha256' in data and (not isinstance(data['followup_reviewed_sha256'], str) or (data['followup_reviewed_sha256'] and not re.fullmatch('[a-f0-9]{64}', data['followup_reviewed_sha256']))): raise ValueError('invalid followup_reviewed_sha256')
    if data.get('followup_policy') not in (None, manual_defaults.POLICY_VERSION): raise ValueError('invalid followup_policy')
    if data.get('followup_policy') == manual_defaults.POLICY_VERSION and 'followup_decision' not in data: raise ValueError('followup_decision is required')
    if 'needs_review' in data and (not isinstance(data['needs_review'], list) or any(x not in REVIEW for x in data['needs_review'])): raise ValueError('invalid needs_review')

def load(conn, patient, ai=False):
    data = records.get_json(conn, patient['id'], 'report_spec.ai.json' if ai else 'report_spec.json')
    if data is None: return {'saved': False}
    validate(data)
    if not ai: data = with_trusted_policy(conn, patient, data)
    if not ai: data['followup_text_reviewed'] = manual_defaults.review_valid(data)
    if not ai: data['revision'] = records.revision(conn, patient['id'], 'report_spec.json')
    if not ai: data['interview_newer'] = 'interview_revision' in data and interview.revision(conn, patient) != data['interview_revision']
    if not ai:
        import pathology_records
        data['pathology_newer'] = 'pathology_revision' in data and pathology_records.revision(conn, patient) != data['pathology_revision']
    return data

def save(conn, patient, data):
    with _lock: return _save(conn, patient, data)

POLICY_RECORD = 'report_spec.policy.json'


def trusted_policy(conn, patient):
    """Whether this spec was created under the follow-up decision policy. Persisted by the engine when the spec is
    created, never taken from a request, so deleting the marker or the decision from a payload cannot downgrade it."""
    saved = records.get_json(conn, patient['id'], POLICY_RECORD)
    return manual_defaults.POLICY_VERSION if isinstance(saved, dict) and saved.get('version') == manual_defaults.POLICY_VERSION else None


def with_trusted_policy(conn, patient, data):
    data = {k: v for k, v in data.items() if k != 'followup_policy'}
    policy = trusted_policy(conn, patient)
    return {**data, 'followup_policy': policy} if policy else data


def _bind_followup_review(data, old):
    """followup_text_reviewed=True from the client means 'I reviewed the follow-up text now saved'. It is stored as a hash
    of that exact text, and only when the text and the decision are unchanged from the previous save; otherwise it is dropped."""
    asked = data.pop('followup_text_reviewed', False)
    text = data.get('followup', '').strip()
    unchanged = bool(old) and old.get('followup', '').strip() == text and old.get('followup_decision') == data.get('followup_decision')
    keep = old.get('followup_reviewed_sha256', '') if unchanged else ''
    if asked and unchanged: keep = manual_defaults.text_sha(text, data.get('followup_decision', ''))
    if keep != manual_defaults.text_sha(text, data.get('followup_decision', '')): keep = ''
    return {**data, 'followup_reviewed_sha256': keep} if (keep or old.get('followup_reviewed_sha256') or 'followup_decision' in data) else data


def _save(conn, patient, data):
    expected = data.get('expected_revision') if isinstance(data, dict) else None
    if expected is not None and not isinstance(expected, str): raise ValueError('invalid expected_revision')
    data = with_trusted_policy(conn, patient, data)
    validate(data)
    data = manual_defaults.apply_followup_decision({k: v for k, v in data.items() if k not in ('interview_newer', 'pathology_newer', 'revision', 'expected_revision')})
    if expected is not None:
        # Compare and write in one write transaction so two saves cannot both pass the check.
        if not conn.in_transaction: conn.execute('BEGIN IMMEDIATE')
        if records.revision(conn, patient['id'], 'report_spec.json') != expected: raise records.Conflict('report changed since it was read')
    previous = records.get(conn, patient['id'], 'report_spec.json')
    data = _bind_followup_review(data, json.loads(previous) if previous else {})
    if previous is not None: records.put(conn, patient['id'], 'report_spec.json.bak', previous)
    records.put_json(conn, patient['id'], 'report_spec.json', data)
    db.log(conn, patient['id'], 'report_saved', {}, 'api')
    conn.commit()
    return dict(data, revision=records.revision(conn, patient['id'], 'report_spec.json'))  # the caller's next conditional save needs it

def placeholders(data):
    return manual_defaults.unresolved(data)

def observations(record):
    d = record.get('details', {}); lines = []
    rows = record.get('obs', [])
    for r in [r for r in rows if r[0] != 'Height / weight / BMI'] + [r for r in rows if r[0] == 'Height / weight / BMI']:
        if r[0] == 'Height / weight / BMI':
            parts = []
            for key in ('height', 'weight', 'bmi'):
                value = d.get(key + '_actual', '')
                referral = d.get(key + '_referral', '')
                if d.get(key + '_as_listed') and referral: value = referral
                elif not value and referral: value = referral + ' (referral)'
                if value: parts.append(key.title() + ': ' + value)
            value = '; '.join(parts) or (r[2] or (r[1] + ' (referral)' if r[1] else ''))
        else: value = r[2] or (r[1] + ' (referral)' if r[1] else '')
        if value: lines.append(r[0] + ': ' + value)
    for key, label in (('home_bp', 'Home BP readings'), ('home_bgl', 'Home blood glucose readings')):
        if d.get(key): lines.append(label + ': ' + d[key])
    for key, label in (('smoking', 'Smoking'), ('alcohol', 'Alcohol')):
        if d.get(key) and d[key] != 'unknown': lines.append(label + ': ' + interview.CHOICE_LABELS[key][d[key]] + (' — ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if record.get('mobility'): lines.append('Mobility: ' + record['mobility'])
    for key, label, choices in (('missed_doses', 'Missed doses', ('sometimes', 'often')), ('device_technique', 'Device technique', ('issues',))):
        if d.get(key) in choices: lines.append(label + ': ' + interview.CHOICE_LABELS[key][d[key]].lower() + (' — ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if d.get('swallowing') == 'yes': lines.append('Swallowing problems reported' + (': ' + d['swallowing_details'] if d.get('swallowing_details') else ''))
    for key, label in interview.SYMPTOMS.items():
        if d.get(key) == 'yes': lines.append('Reports ' + label.lower() + (': ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if d.get('recent_change') == 'yes': lines.append('Recent hospital or specialist change: ' + (d.get('recent_change_details') or 'yes'))
    return '\n'.join(lines)

def intro_text(record, name, visit):
    d = record['details']
    if not any(d.get(k) for k in ('present', 'lives', 'manager', 'daa')): return ''
    # Owner's reports are third person: "<name> was interviewed at home, ...".
    text = name + ' was interviewed at home' + (' on ' + visit if visit else '')
    if d.get('present') == 'with_other': text += ', with ' + (d.get('present_details') or 'a carer or family member') + ' present'
    elif d.get('present') == 'alone': text += ', alone'
    sentences = [text + '.']
    if d.get('lives'): sentences.append(name + ' lives ' + {'alone': 'alone', 'partner': 'with a partner', 'family': 'with family', 'other': 'in another living arrangement'}[d['lives']] + '.')
    manager = {'self': 'the patient', 'other': d.get('manager_details') or 'someone else'}.get(d.get('manager'))
    clause = 'Medicines are managed by ' + manager if manager else ''
    if d.get('daa') == 'yes':
        aid = 'a dose administration aid' + (' (' + interview.CHOICE_LABELS['daa_type'][d['daa_type']] + ')' if d.get('daa_type') else '') + (' packed by ' + d['daa_pharmacy'] if d.get('daa_pharmacy') else '')
        clause = clause + ', using ' + aid if clause else 'Medicines are supplied using ' + aid
    elif d.get('daa') == 'no': clause = clause + ', without a dose administration aid' if clause else 'No dose administration aid is used'
    if clause: sentences.append(clause + '.')
    return ' '.join(sentences)

def actual(r, m):
    """Actual-use cell for a referral medicine row.

    Confirmation of use and confirmation of directions stay distinct: an explicit
    'taking' with no recorded directions is reported as confirmed use with missing
    directions, never as 'Not yet confirmed' and never with invented directions.
    """
    prn = '; used ' + m['prn_use'] if m.get('prn_use') else ''
    if m.get('use_status') == 'unknown':
        return 'Not yet confirmed' + ('; previously recorded directions: ' + r[2] if r[2] else ('; referral: ' + r[1] if r[1] else '')) + prn
    if r[2]:
        return r[2] + prn
    if m.get('use_status') == 'taking':
        return 'Taking confirmed - actual directions not recorded' + ('; referral directions: ' + r[1] if r[1] else '') + prn
    return ('Not yet confirmed; referral: ' + r[1] if r[1] else 'Not yet confirmed') + prn


def other_actual(r, m):
    """Actual-use cell for a medicine found during the interview (same rule as actual)."""
    if m.get('use_status') == 'unknown':
        return 'Not yet confirmed' + ('; previously recorded directions: ' + r[1] if r[1] else '')
    if r[1]:
        return r[1]
    if m.get('use_status') == 'taking':
        return 'Taking confirmed - actual directions not recorded'
    return 'Not yet confirmed'


def _derived(conn, patient):
    folder = jobs.patient_folder(patient)
    import api
    with interview.record_lock(patient):
        has_interview = records.exists(conn, patient['id'], 'interview.json')
        if not records.exists(conn, patient['id'], 'confirmed_meds.json'): raise ValueError('confirm the medicine list first')
        if not api.confirmed_medicines_current(conn, patient): raise ValueError('Medicine use changed; review and confirm medicines first')
        record = interview.load(conn, patient); p = dict(patient); h = record['header']
    if not has_interview:
        confirmed = records.get_json(conn, patient['id'], 'confirmed_meds.json')
        record['meds'] = [[r[0], '', '', '', 'Brand: ' + r[1] if r[1] else ''] for r in confirmed['meds']]
        record['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in record['meds']]
        record['allergies'] = '\n'.join(confirmed['allergies'])
    referral_rows = record['meds']
    referral_meta = record['details']['meds']
    other_rows = record['other_meds']
    other_meta = record['details']['other_meds']

    def other_note(r, m):
        return ' | '.join(filter(None, [*r[2:], interview.use_text(m)]))
    def referral_note(r, m):
        return '\n'.join(filter(None, (r[4], 'DAA: ' + m['packed'] if m['packed'] else '')))
    import pathology_records
    clinical_pathology = pathology_records.load(conn, patient)
    verified_pathology = clinical_pathology['records']
    verification = clinical_pathology.get('verification', {})
    def _date_key(raw):
        raw = (raw or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return dt.datetime.strptime(raw[:10], fmt).date().isoformat()
            except ValueError:
                pass
        return raw.casefold()
    def _legacy_key(row):
        return (row[0].strip().casefold(), row[1].strip().casefold(), _date_key(row[2]))
    structured_keys = {
        (row['test'].strip().casefold(), row['value'].strip().casefold(),
         _date_key(row['sample_date']))
        for row in verified_pathology
        if row['test'].strip() and row['value'].strip() and row['sample_date']
    }
    # Keep original legacy JSON unchanged. Show a matching structured record
    # only once in the report; unresolved legacy rows stay visibly unverified.
    pathology_table = [[r[0], r[1], '', '',
                        'UNVERIFIED legacy interview entry — confirm against original source | ' +
                        ' '.join(filter(None, (r[3], ('Date: ' + r[2]) if r[2] else '')))]
                       for r in record['pathology']
                       if any(r) and _legacy_key(r) not in structured_keys]
    for result in verified_pathology:
        if not result['test'].strip(): continue
        pathology_table.append([
            result['test'],
            result['value'], result['unit'], result['reference_interval'],
            ' | '.join(filter(None, (
                ('Verified by ' + verification[result['id']]['verified_by'] +
                 ' at ' + verification[result['id']]['verified_at']
                 if result['verified'] and result['id'] in verification else
                 'LEGACY VERIFICATION — reviewer not recorded; check original source'
                 if result['verified'] else 'UNVERIFIED — check original source'),
                'Sample: ' + result['sample_date'] if result['sample_date'] else '',
                'Source: ' + result['source'] if result['source'] else '',
                result['comment'],
            )))
        ])
    dates = list(dict.fromkeys(
        [r[2] for r in record['pathology'] if r[2]] +
        [r['sample_date'] for r in verified_pathology if r['sample_date']]
    ))
    return record, dict(conditions=record['conditions'], allergies=record['allergies'], obs=observations(record), meds=[[r[0], actual(r, m), referral_note(r, m), ''] for r, m in zip(referral_rows, referral_meta) if any(r) and m.get('use_status') != 'not_using'] + [[r[0], other_actual(r, m), ' | '.join(filter(None, r[2:])), ''] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') != 'not_using' and m.get('kind') not in ('otc', 'complementary')], otc=[[r[0], other_actual(r, m), ' | '.join(filter(None, r[2:]))] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') != 'not_using' and m.get('kind') in ('otc', 'complementary')], ceased=[[r[0], r[1], ' | '.join(filter(None, ['Referral medicine', r[2], '\n'.join(filter(None, (referral_note(r, m), interview.use_text(m))))]))] for r, m in zip(referral_rows, referral_meta) if any(r) and m.get('use_status') == 'not_using'] + [[r[0], r[1], ' | '.join(filter(None, ['Found during interview', other_note(r, m)]))] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') == 'not_using'], path=pathology_table), ', '.join(dates)

def _demographics(conn, patient, record):
    """Patient, GP and date blocks, built the same way at start and at refresh."""
    p = dict(patient); h = record['header']
    name = p['name']; gp = p.get('gp') or h['gp'] or ''
    address = ', '.join(filter(None, (p.get('address'), p.get('suburb'))))
    patient_lines = [name, 'DOB: ' + (p.get('dob') or h['dob']), 'Medicare No: ' + (p.get('medicare') or ''), 'Address: ' + address, 'Phone: ' + (p.get('phone') or '')]
    doctor_lines = [gp, p.get('clinic') or '', 'Request date: ' + (p.get('referral_date') or '')]
    import steps
    visit = steps.event_date(conn, patient, 'visited') or p.get('visit_date') or h['visit'].split(' ')[0]
    return dict(name=name, assess_date=visit, patient='\n'.join(patient_lines), doctor='\n'.join(filter(None, doctor_lines)), dear='Dear ' + gp + ',')

def start(conn, patient):
    folder = jobs.patient_folder(patient)
    if records.exists(conn, patient['id'], 'report_spec.json'): raise FileExistsError('report spec already exists')
    record, derived, dates = _derived(conn, patient); p = dict(patient); h = record['header']
    name = p['name']; gp = p.get('gp') or h['gp'] or ''
    data = manual_defaults.initial_text(name, gp)
    demo = _demographics(conn, patient, record); name = demo['name']; visit = demo['assess_date']
    data.update(out=str(folder / ('HMR ' + re.sub(r'[<>:"/\\|?*]', '', name).rstrip(' .') + '.docx')), report_date=dt.date.today().strftime('%d/%m/%Y'), path_date=dates, **demo, issues=[], needs_review=REVIEW.copy())
    data.update(derived, medicine_snapshot=medicine_snapshot.snapshot(record), medicine_snapshot_sha256=medicine_snapshot.digest(medicine_snapshot.snapshot(record)), interview_revision=record['revision'], interview_reason=record['details']['reason'], pathology_revision=__import__('pathology_records').revision(conn, patient))
    intro = intro_text(record, name, visit)
    if intro: data['intro'] = intro
    if record['details']['reason'].strip():
        data['reason'] = record['details']['reason']; data['needs_review'].remove('reason')
    validate(data)
    try: records.put(conn, patient['id'], 'report_spec.json', records.dumps(data), expected_revision='missing')
    except records.Conflict: raise FileExistsError('report spec already exists')
    records.put_json(conn, patient['id'], POLICY_RECORD, {'version': manual_defaults.POLICY_VERSION})
    db.log(conn, patient['id'], 'report_started', {}, 'job')
    conn.commit()
    return data

def refresh(conn, patient):
    with _lock: return _refresh(conn, patient)

def _refresh(conn, patient):
    data = records.get_json(conn, patient['id'], 'report_spec.json')
    if data is None: raise ValueError('report spec does not exist')
    validate(data)
    record, derived, _ = _derived(conn, patient)
    import pathology_records
    data.update(_demographics(conn, patient, record))  # a corrected DOB, GP or visit date must reach the report, not only the tables
    folder = jobs.patient_folder(patient)
    stored = Path(str(data.get('out') or ''))
    if stored.name and (not stored.is_absolute() or stored.parent.resolve() != folder):
        data['out'] = str(folder / stored.name)  # a restored or moved workspace must not keep a path outside the patient folder
    data.update(derived, medicine_snapshot=medicine_snapshot.snapshot(record), medicine_snapshot_sha256=medicine_snapshot.digest(medicine_snapshot.snapshot(record)), interview_revision=record['revision'], interview_reason=record['details']['reason'],
                pathology_revision=pathology_records.revision(conn, patient))
    saved = save(conn, patient, data)
    db.log(conn, patient['id'], 'report_refreshed', {}, 'job')
    return saved

def _read(path):
    stamp = path.stat().st_mtime_ns
    if path not in _cache or _cache[path][0] != stamp: _cache[path] = (stamp, path.read_text(encoding='utf-8'))
    return _cache[path][1]

def library(q):
    words = q.casefold().split()
    if not words: return []
    refs = jobs.SKILL / 'references'; result = []
    text = _read(refs / 'finding-library.md') if (refs / 'finding-library.md').is_file() else ''
    for section in re.split(r'(?m)(?=^## )', text):
        if not section.startswith('## '): continue
        title, _, body = section.partition('\n')
        if all(w in section.casefold() for w in words): result.append(dict(source='library', title=title[3:].strip(), rec=body.strip(), rationale='', context='Full library section; split and edit for this patient.'))
    for line in (_read(refs / 'case-index.jsonl') if (refs / 'case-index.jsonl').is_file() else '').splitlines():
        if not line.strip(): continue
        case = json.loads(line)
        for finding in case.get('findings', []):
            # Reject any unredacted name or birth date rather than exposing it.
            fields = [str(finding.get(k, '')) for k in ('title', 'rec', 'rationale')]
            if re.search(r'(?i)\b(?:mr|mrs|ms|miss|dr)\.?\s+(?!\[pt\])[A-Z][a-z]+|\b(?:dob|date of birth|born)\b', ' '.join(fields)): continue
            context = str(case.get('Current Conditions', ''))
            if re.search(r'(?i)\b(?:mr|mrs|ms|miss|dr)\.?\s+(?!\[pt\])[A-Z][a-z]+|\b(?:dob|date of birth|born)\b', context): continue
            searchable = ' '.join(fields + [context] + [' '.join(m.get('row', [])) for m in case.get('meds', [])] + case.get('pathology', [])).casefold()
            if all(w in searchable for w in words): result.append(dict(source='past case', title=fields[0], rec=fields[1], rationale=fields[2], context=context))
    result = result[:30]
    brain_count = 0
    for section in brainstorm.sections(refs / 'brainstorm-v2.pdf'):
        if all(w in (section['title'] + ' ' + section['text']).casefold() for w in words):
            passage = brainstorm.passage(section, [re.escape(w) for w in words])
            if passage is None: continue
            result.append(dict(**passage, source=f"Brainstorm V2 p.{passage['page']}", rec=passage['snippet'], rationale='', context=''))
            brain_count += 1
            if brain_count == 10: break
    return result
