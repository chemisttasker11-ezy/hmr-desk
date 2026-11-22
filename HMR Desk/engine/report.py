"""Local report editor data and reusable finding search."""
import copy
import datetime as dt
import hashlib
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

def _dmy(value):
    """Display an ISO date as DD/MM/YYYY like the assessment and report dates; other text is unchanged."""
    import re
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', str(value).strip())
    return match[3] + '/' + match[2] + '/' + match[1] if match else value


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
        review = issue.get('template_review')
        if review is not None and (not isinstance(review, dict) or set(review) != {'sha256', 'context_sha256'} or
                                   any(not isinstance(review[k], str) or not re.fullmatch('[a-f0-9]{64}', review[k]) for k in review)):
            raise ValueError('invalid template review')
        if 'template_reviewed' in issue and not isinstance(issue['template_reviewed'], bool): raise ValueError('invalid template_reviewed')
        if 'template_review_for' in issue and not (isinstance(issue['template_review_for'], str) and re.fullmatch('[a-f0-9]{64}', issue['template_review_for'])): raise ValueError('invalid template_review_for')
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
    if not ai: data['held_medicine_actions'] = held_actions(conn, patient)
    if not ai: data = _expose_template_review(conn, patient, data)
    if not ai: data['demographic_mismatches'] = demographic_mismatches(conn, patient, data)
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


def template_review_sha(issue, context_sha256):
    """Review of an imported past-case template covers the exact wording and the saved patient sources it was reviewed against.
    Only a hash is stored, never the template text."""
    parts = ['template-review-v1'] + [str(issue.get(k, '')).strip() for k in ('title', 'rec', 'rationale')] + [context_sha256]
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()


def _current_context_sha(conn, patient):
    """Fingerprint of the saved sources the suggestion context is built from (interview, pathology, confirmed medicines,
    interaction files), not of today's date, so a review does not lapse at midnight. '' when it cannot be established
    (a review is then never valid)."""
    try:
        import suggest
        revisions = suggest.context_for(conn, patient).get('source_revisions')
        if not isinstance(revisions, dict) or not revisions: return ''
        return hashlib.sha256(('template-context-v1\n' + json.dumps(revisions, sort_keys=True, ensure_ascii=False, separators=(',', ':'))).encode('utf-8')).hexdigest()
    except Exception:
        return ''


def _review_is_valid(issue, current):
    review = issue.get('template_review')
    return bool(current and isinstance(review, dict) and review.get('context_sha256') == current and
                review.get('sha256') == template_review_sha(issue, current))


def template_reviews_pending(conn, patient, data):
    """1-based numbers of findings that came from an imported suggestion template and have not been deliberately reviewed
    for this exact wording and the current patient context. Manual findings are never listed. A suggestion-derived
    finding saved before this review existed has no review record, so it is listed until the pharmacist reviews it."""
    numbered = [(n, i) for n, i in enumerate(data.get('issues', []), 1) if isinstance(i, dict) and 'suggestion_source' in i]
    if not numbered: return []
    current = _current_context_sha(conn, patient)
    return [n for n, i in numbered if not _review_is_valid(i, current)]


def _bind_template_reviews(conn, patient, data, old):
    """template_reviewed=True from the client means 'I reviewed this imported template wording for this patient now'.
    It is honoured only when the finding text and its suggestion source are unchanged from the previous save and the
    client saw the current patient context (template_review_for). Editing never creates a review, and a review is
    dropped when the wording changes. Review state in the payload is never trusted: only the previous saved state is."""
    issues = data.get('issues', [])
    previous = old.get('issues', []) if isinstance(old, dict) else []
    if not any(isinstance(i, dict) and ('suggestion_source' in i or 'template_review' in i or 'template_reviewed' in i) for i in list(issues) + list(previous)): return data
    current = None
    result = []
    imported = {}
    for before in previous:
        if isinstance(before, dict) and 'suggestion_source' in before:
            imported.setdefault(tuple(str(before.get(k, '')).strip() for k in ('title', 'rec', 'rationale')), before['suggestion_source'])
    for index, issue in enumerate(issues):
        clean = {k: v for k, v in issue.items() if k not in ('template_review', 'template_reviewed', 'template_review_for')}
        if 'suggestion_source' not in issue:
            # A save that drops the provenance of wording that is still exactly an imported template does not make it a
            # manual finding: the source is restored and the review starts again. Rewritten wording is the pharmacist's own.
            restored = imported.get(tuple(str(issue.get(k, '')).strip() for k in ('title', 'rec', 'rationale')))
            if restored is not None:
                result.append({**clean, 'suggestion_source': copy.deepcopy(restored)})
                continue
            result.append(clean)  # a manual finding carries no review state
            continue
        before = previous[index] if index < len(previous) and isinstance(previous[index], dict) else {}
        same = ({k: str(before.get(k, '')).strip() for k in ('title', 'rec', 'rationale')} == {k: str(issue.get(k, '')).strip() for k in ('title', 'rec', 'rationale')}
                and before.get('suggestion_source') == issue.get('suggestion_source'))
        asked = issue.get('template_reviewed')
        keep = before.get('template_review') if same else None
        if asked is False: keep = None
        elif asked and same:
            if current is None: current = _current_context_sha(conn, patient)
            if current and issue.get('template_review_for') == current: keep = {'sha256': template_review_sha(clean, current), 'context_sha256': current}
        if isinstance(keep, dict) and keep.get('sha256') != template_review_sha(clean, keep.get('context_sha256', '')): keep = None
        result.append({**clean, 'template_review': keep} if keep else clean)
    return {**data, 'issues': result}


def _expose_template_review(conn, patient, data):
    """Read-only view for the editor: whether each suggestion-derived finding is reviewed now, and the context fingerprint
    the pharmacist is looking at. Not stored."""
    if not any(isinstance(i, dict) and 'suggestion_source' in i for i in data.get('issues', [])): return data
    current = _current_context_sha(conn, patient)
    return {**data, 'suggestion_context_sha256': current,
            'issues': [({**i, 'template_reviewed': _review_is_valid(i, current)} if isinstance(i, dict) and 'suggestion_source' in i else i) for i in data['issues']]}


def _bind_followup_review(data, old):
    """followup_text_reviewed=True from the client means 'I reviewed the follow-up text now saved'. It is stored as a hash
    of that exact text, and only when the text and the decision are unchanged from the previous save; otherwise it is dropped."""
    asked = data.pop('followup_text_reviewed', None)  # None = the client did not say; False = explicitly unticked
    text = data.get('followup', '').strip()
    unchanged = bool(old) and old.get('followup', '').strip() == text and old.get('followup_decision') == data.get('followup_decision')
    keep = old.get('followup_reviewed_sha256', '') if unchanged else ''
    if asked is False: keep = ''
    elif asked and unchanged: keep = manual_defaults.text_sha(text, data.get('followup_decision', ''))
    if keep != manual_defaults.text_sha(text, data.get('followup_decision', '')): keep = ''
    return {**data, 'followup_reviewed_sha256': keep} if (keep or old.get('followup_reviewed_sha256') or 'followup_decision' in data) else data


def _save(conn, patient, data):
    expected = data.get('expected_revision') if isinstance(data, dict) else None
    if expected is not None and not isinstance(expected, str): raise ValueError('invalid expected_revision')
    data = with_trusted_policy(conn, patient, data)
    validate(data)
    data = manual_defaults.apply_followup_decision({k: v for k, v in data.items() if k not in ('interview_newer', 'pathology_newer', 'revision', 'expected_revision', 'demographic_mismatches', 'demographic_conflicts', 'medication_recommendations', 'held_medicine_actions', 'suggestion_context_sha256')})
    if expected is not None:
        # Compare and write in one write transaction so two saves cannot both pass the check.
        if not conn.in_transaction: conn.execute('BEGIN IMMEDIATE')
        if records.revision(conn, patient['id'], 'report_spec.json') != expected: raise records.Conflict('report changed since it was read')
    previous = records.get(conn, patient['id'], 'report_spec.json')
    data = _bind_followup_review(data, json.loads(previous) if previous else {})
    data = _bind_template_reviews(conn, patient, data, json.loads(previous) if previous else {})
    if previous is not None: records.put(conn, patient['id'], 'report_spec.json.bak', previous)
    records.put_json(conn, patient['id'], 'report_spec.json', data)
    db.log(conn, patient['id'], 'report_saved', {}, 'api')
    conn.commit()
    return dict(_expose_template_review(conn, patient, data), revision=records.revision(conn, patient['id'], 'report_spec.json'))  # the caller's next conditional save needs it

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
    import medicine_review
    with interview.record_lock(patient):
        has_interview = records.exists(conn, patient['id'], 'interview.json')
        if not records.exists(conn, patient['id'], 'confirmed_meds.json'): raise ValueError('confirm the medicine list first')
        if not medicine_review.confirmed_medicines_current(conn, patient): raise ValueError('Medicine use changed; review and confirm medicines first')
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
    dup_notes = interview.duplicate_notes(record)
    def referral_note(r, m):
        index = next((n for n, x in enumerate(referral_meta) if x is m), -1)
        return '\n'.join(filter(None, (r[4], 'DAA: ' + m['packed'] if m['packed'] else '', dup_notes.get(('meds', index), ''))))
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
                '' if result['verified'] and result['id'] in verification and result['comment'] == UNVERIFIED_DEFAULT_NOTE else result['comment'],
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
    patient_lines = [name, 'DOB: ' + _dmy(p.get('dob') or h['dob']), 'Medicare No: ' + (p.get('medicare') or ''), 'Address: ' + address, 'Phone: ' + (p.get('phone') or '')]
    doctor_lines = [gp,
                    ('Provider number: ' + p['gp_provider']) if p.get('gp_provider') else '',
                    p.get('clinic') or '',
                    ('Practice address: ' + p['clinic_address']) if p.get('clinic_address') else '',
                    ('Practice phone: ' + p['clinic_phone']) if p.get('clinic_phone') else '',
                    'Request date: ' + _dmy(p.get('referral_date') or '')]
    import steps
    visit = steps.event_date(conn, patient, 'visited') or p.get('visit_date') or h['visit'].split(' ')[0]
    return dict(name=name, assess_date=visit, patient='\n'.join(patient_lines), doctor='\n'.join(filter(None, doctor_lines)), dear='Dear ' + (gp or 'Doctor') + ',')

def start(conn, patient):
    folder = jobs.patient_folder(patient)
    if records.exists(conn, patient['id'], 'report_spec.json'): raise FileExistsError('report spec already exists')
    record, derived, dates = _derived(conn, patient); p = dict(patient); h = record['header']
    name = p['name']; gp = p.get('gp') or h['gp'] or ''
    data = manual_defaults.initial_text(name, gp)
    demo = _demographics(conn, patient, record); name = demo['name']; visit = demo['assess_date']
    data.update(out=str(folder / ('HMR ' + re.sub(r'[<>:"/\\|?*]', '', name).rstrip(' .') + '.docx')), report_date=dt.date.today().strftime('%d/%m/%Y'), path_date=dates, demographics_generated=demo, **demo, issues=[], needs_review=REVIEW.copy())
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

# The placeholder note the Interview page puts on a result linked to a source page. Once the pharmacist verifies the row
# it is no longer true, so the report omits exactly this text for verified rows; any other note is printed unchanged.
UNVERIFIED_DEFAULT_NOTE = 'UNVERIFIED — compare source PDF before confirming'
DEMOGRAPHIC_LABELS = {'name': 'patient name', 'assess_date': 'assessment date', 'patient': 'patient details block', 'doctor': 'GP details block', 'dear': 'salutation'}

def _merge_demographics(data, new, replace=()):
    """Refresh brings corrected record values into blocks the pharmacist has not touched. A block that differs from
    what the app last generated was edited (or is from an older spec): it is kept, and returned as a conflict so
    the pharmacist chooses. Only blocks named in `replace` are overwritten."""
    if not isinstance(replace, (list, tuple)) or any(k not in DEMOGRAPHIC_LABELS for k in replace): raise ValueError('invalid replace_demographics')
    generated = data.get('demographics_generated') if isinstance(data.get('demographics_generated'), dict) else {}
    conflicts = []
    for key in DEMOGRAPHIC_LABELS:
        current = data.get(key, '')
        if current == new[key]: continue
        if key in replace or (key in generated and generated[key] == current): data[key] = new[key]
        else: conflicts.append({'key': key, 'label': DEMOGRAPHIC_LABELS[key], 'report': current, 'record': new[key]})
    data['demographics_generated'] = new
    return conflicts

ACK_RECORD = 'report_spec.demographics_ack.json'

def _ack_hash(key, text, record_value):
    """A keep decision is bound to this block's exact text and to what the patient record says now."""
    return hashlib.sha256(json.dumps([key, text, record_value], ensure_ascii=False).encode('utf-8')).hexdigest()

def demographic_mismatches(conn, patient, data):
    """Blocks whose text differs from what the current patient record produces. Response-only. A block is
    acknowledged only while the exact text and the exact record value are unchanged since the pharmacist kept it."""
    record = interview.load(conn, patient)
    new = _demographics(conn, patient, record)
    acks = records.get_json(conn, patient['id'], ACK_RECORD)
    acks = acks if isinstance(acks, dict) else {}
    result = []
    for key, label in DEMOGRAPHIC_LABELS.items():
        text = data.get(key, '')
        if text == new[key]: continue
        result.append({'key': key, 'label': label, 'report': text, 'record': new[key],
                       'acknowledged': acks.get(key) == _ack_hash(key, text, new[key])})
    return result

def unresolved_demographics(conn, patient, data):
    return [m['key'] for m in demographic_mismatches(conn, patient, data) if not m['acknowledged']]

def demographic_status(conn, patient, data):
    """Key -> matches/kept/unresolved, for build evidence. Carries no patient text."""
    status = {key: 'matches' for key in DEMOGRAPHIC_LABELS}
    for m in demographic_mismatches(conn, patient, data): status[m['key']] = 'kept' if m['acknowledged'] else 'unresolved'
    return status

def resolve_demographics(conn, patient, action, keys):
    """Per-block choice. 'replace' writes the record's value into the block; 'keep' records an acknowledgement bound to
    the exact text and record value. Nothing else in the report changes."""
    if action not in ('replace', 'keep') or not isinstance(keys, list) or not keys or any(k not in DEMOGRAPHIC_LABELS for k in keys):
        raise ValueError('invalid demographic choice')
    with _lock:
        data = records.get_json(conn, patient['id'], 'report_spec.json')
        if data is None: raise ValueError('report spec does not exist')
        validate(data)
        mismatches = {m['key']: m for m in demographic_mismatches(conn, patient, data)}
        if any(k not in mismatches for k in keys): raise ValueError('That block already matches the patient record; reload the report')
        if action == 'replace':
            for k in keys: data[k] = mismatches[k]['record']
            generated = dict(data.get('demographics_generated') or {})
            generated.update({k: mismatches[k]['record'] for k in keys})
            data['demographics_generated'] = generated
            _save(conn, patient, data)
        else:
            acks = records.get_json(conn, patient['id'], ACK_RECORD)
            acks = dict(acks) if isinstance(acks, dict) else {}
            for k in keys: acks[k] = _ack_hash(k, mismatches[k]['report'], mismatches[k]['record'])
            records.put_json(conn, patient['id'], ACK_RECORD, acks)
            db.log(conn, patient['id'], 'report_demographics_kept', {'blocks': sorted(keys)}, 'api')  # block names only, no text
            conn.commit()
        return load(conn, patient)

def refresh(conn, patient, replace=()):
    with _lock: return _refresh(conn, patient, replace)

def _carry_forward_unchanged_medicine_recommendations(previous, current):
    """Retain a pharmacist's review text only for an unambiguously unchanged medicine row.

    A mismatch in medicine name, actual-use directions or source notes is deliberately
    not guessed to be the same medicine. Existing edited notes are held in the report
    backup; refresh returns a warning count so no recommendation disappears silently.
    This does not carry forward clinical decisions when the source facts have changed.
    """
    from collections import Counter
    def key(row):
        return tuple(row[:3])
    old_counts = Counter(key(row) for row in previous)
    new_counts = Counter(key(row) for row in current)
    old_unique = {key(row): row for row in previous if old_counts[key(row)] == 1}
    updated, carried = [], 0
    for row in current:
        candidate = old_unique.get(key(row))
        if candidate is not None and new_counts[key(row)] == 1 and candidate[3].strip():
            updated.append([*row[:3], candidate[3]])
            carried += 1
        else:
            updated.append(list(row))
    previous_recommendations = sum(bool(row[3].strip()) for row in previous)
    return updated, {'retained': carried, 'needs_reentry': previous_recommendations - carried}


HELD_MAX_ENTRIES = 1000
HELD_RECORD = 'report_spec.held_actions.json'  # outside the spec: autosave, builds and the AI projection never touch it


def _held_entries(previous, current):
    """Old medicine rows whose typed Action text did NOT carry forward, with why. Mirrors the exact-match rule."""
    from collections import Counter
    def key(row): return tuple(row[:3])
    old_counts = Counter(key(r) for r in previous); new_counts = Counter(key(r) for r in current)
    held = []
    for row in previous:
        if not row[3].strip(): continue
        if old_counts[key(row)] == 1 and new_counts[key(row)] == 1: continue
        reason = 'duplicate' if old_counts[key(row)] > 1 or new_counts[key(row)] > 1 else 'changed_or_removed'
        held.append(dict(name=row[0], directions=row[1], comment=row[2], action=row[3], reason=reason))
    return held


def _held_id(entry):
    return hashlib.sha256('\x1f'.join(entry[k] for k in ('name', 'directions', 'comment', 'action')).encode('utf-8')).hexdigest()[:16]


def _hold_actions(conn, patient, held):
    """Add to the append-only held list in the caller's transaction (the report save commits both together)."""
    store = _held_store(conn, patient)  # read first: a refresh never runs on top of a held record it cannot read
    if not held: return
    entries = list(store['entries']) if store else []
    by_id = {e['id']: e for e in entries}
    for entry in held:
        eid = _held_id(entry)
        if eid in by_id: by_id[eid].update(reason=entry['reason'], resolved=False)
        else:
            by_id[eid] = dict(entry, id=eid, resolved=False); entries.append(by_id[eid])
    if len(entries) > HELD_MAX_ENTRIES: raise ValueError('Too many held medicine recommendations; handle some before refreshing again')  # refuse, never drop text
    records.put_json(conn, patient['id'], HELD_RECORD, {'version': 1, 'entries': entries})


def _held_store(conn, patient):
    """The held record, strictly. Missing is empty. Present but unreadable or malformed raises, so build and sign-off fail closed."""
    try: store = records.get_json(conn, patient['id'], HELD_RECORD)
    except ValueError: store = False  # undecodable bytes or JSON
    if store is None: return None
    ok = (isinstance(store, dict) and set(store) == {'version', 'entries'} and type(store['version']) is int and store['version'] == 1 and
          isinstance(store['entries'], list) and len(store['entries']) <= HELD_MAX_ENTRIES)
    if ok:
        ids = set()
        for e in store['entries']:
            ok = (isinstance(e, dict) and set(e) == {'id', 'name', 'directions', 'comment', 'action', 'reason', 'resolved'} and
                  all(isinstance(e[k], str) for k in ('id', 'name', 'directions', 'comment', 'action', 'reason')) and
                  type(e['resolved']) is bool and e['reason'] in ('duplicate', 'changed_or_removed') and e['action'].strip() != '' and
                  e['id'] == _held_id(e) and e['id'] not in ids)  # id is the hash of the content, so a damaged or duplicated entry is refused
            if not ok: break
            ids.add(e['id'])
    if not ok: raise ValueError('Held medicine recommendations could not be read; do not build or sign off until they are checked')
    return store


def held_actions(conn, patient):
    store = _held_store(conn, patient)
    return [e for e in store['entries'] if not e['resolved']] if store else []


def resolve_held_action(conn, patient, entry_id):
    """The pharmacist has dealt with it. The text stays in the record, only hidden from the list."""
    with _lock:
        store = _held_store(conn, patient)
        match = [e for e in store['entries'] if e['id'] == entry_id and not e['resolved']] if store else []
        if not match: raise ValueError('held recommendation not found')
        match[0]['resolved'] = True
        records.put_json(conn, patient['id'], HELD_RECORD, store)
        db.log(conn, patient['id'], 'report_held_action_resolved', {}, 'api')  # no text
        conn.commit()
        return load(conn, patient)


def _refresh(conn, patient, replace=()):
    data = records.get_json(conn, patient['id'], 'report_spec.json')
    if data is None: raise ValueError('report spec does not exist')
    validate(data)
    record, derived, _ = _derived(conn, patient)
    import pathology_records
    conflicts = _merge_demographics(data, _demographics(conn, patient, record), replace)
    # Keep pharmacist-authored recommendation text ONLY where all three source
    # fields match exactly and the medicine row is unique in both versions.
    # Changed/ambiguous rows require a fresh clinician review rather than guessed mapping.
    held = _held_entries(data['meds'], derived['meds'])
    derived['meds'], medicine_refresh = _carry_forward_unchanged_medicine_recommendations(data['meds'], derived['meds'])
    _hold_actions(conn, patient, held)  # same transaction as the save below
    folder = jobs.patient_folder(patient)
    stored = Path(str(data.get('out') or ''))
    if stored.name and (not stored.is_absolute() or stored.parent.resolve() != folder):
        data['out'] = str(folder / stored.name)  # a restored or moved workspace must not keep a path outside the patient folder
    data.update(derived, medicine_snapshot=medicine_snapshot.snapshot(record), medicine_snapshot_sha256=medicine_snapshot.digest(medicine_snapshot.snapshot(record)), interview_revision=record['revision'], interview_reason=record['details']['reason'],
                pathology_revision=pathology_records.revision(conn, patient))
    saved = save(conn, patient, data)
    db.log(conn, patient['id'], 'report_refreshed', {}, 'job')
    return dict(saved, demographic_conflicts=conflicts, medication_recommendations=medicine_refresh)  # response only

def _read(path):
    stamp = path.stat().st_mtime_ns
    if path not in _cache or _cache[path][0] != stamp: _cache[path] = (stamp, path.read_text(encoding='utf-8'))
    return _cache[path][1]

def library(q):
    words = q.casefold().split()
    if not words: return []
    refs = jobs.references_dir(); result = []
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
