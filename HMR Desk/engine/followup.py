"""Local follow-up interview records and Word exports."""
import json
import re
from pathlib import Path
import jobs
import records

LEGACY_FIELDS = ('date', 'method', 'spoke_with', 'med_changes', 'recommendations', 'issues', 'outcome', 'notes')
FIELDS = LEGACY_FIELDS + ('preferred_method', 'choice_offered_on')
METHODS = ('phone', 'video', 'in person')  # 'in person' is face-to-face; the others are telehealth
TELEHEALTH_FROM = '2026-11-01'  # PPA HMR Program Rules, October 2026, s5.9 and s8: follow-up delivery choice from this date
LABELS = {'': 'Not recorded', 'phone': 'Telephone (telehealth)', 'video': 'Video conference (telehealth)', 'in person': 'Face-to-face'}


def normalize(data):
    """Fill the delivery-choice fields for records saved before they existed (blank = not documented, never guessed)
    and drop the computed review_issues key a client may send back."""
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k != 'review_issues'}
        if set(LEGACY_FIELDS) <= set(data):
            data = {**{'preferred_method': '', 'choice_offered_on': ''}, **data}
    return data


def _day(value):
    import datetime as dt
    try: return dt.date.fromisoformat(value) if value else None
    except (TypeError, ValueError): return None


def review_issues(data):
    """Documentation gaps against the delivery rules, for a follow-up dated on or after 1 Nov 2026.
    A review aid only: it never blocks saving, and it does not certify eligibility or claim acceptance."""
    day = _day(data.get('date'))
    if not day: return []
    method, preferred, offered = data.get('method', ''), data.get('preferred_method', ''), data.get('choice_offered_on', '')
    if day.isoformat() < TELEHEALTH_FROM:
        return ['Video follow-ups before 1 Nov 2026 are not covered by the October 2026 rules checked here'] if method == 'video' else []
    issues = []
    if not method: issues.append('Delivery method not recorded (the Portal claim requires it)')
    if not preferred: issues.append("Patient's preferred delivery option not documented")
    if not offered: issues.append('Date the delivery choice was offered not recorded')
    elif _day(offered) is None: issues.append('Choice-offered date is not a valid date')
    elif _day(offered) > day: issues.append('Choice-offered date is after the follow-up date')
    if preferred == 'in person' and method in ('phone', 'video'):
        issues.append('Telehealth was recorded although the patient prefers face-to-face')
    return issues

def load(conn, patient, number):
    saved = records.get_json(conn, patient['id'], f'followup{number}.json')
    if saved is not None: return normalize(saved)
    data = records.get_json(conn, patient['id'], 'report_spec.json') or {}
    return dict(date='', method='', preferred_method='', choice_offered_on='', spoke_with='', med_changes='', recommendations=[[i['rec'], '', ''] for i in data.get('issues', []) if i.get('rec')], issues='', outcome='', notes='')

def validate(data):
    data = normalize(data)
    if not isinstance(data, dict) or set(data) != set(FIELDS): raise ValueError('invalid follow-up fields')
    if any(not isinstance(data[k], str) or len(data[k]) > 20000 for k in FIELDS if k != 'recommendations'): raise ValueError('invalid follow-up text')
    if data['method'] not in ('',) + METHODS: raise ValueError('invalid method')
    if data['preferred_method'] not in ('',) + METHODS: raise ValueError('invalid preferred method')
    if data['choice_offered_on'] and _day(data['choice_offered_on']) is None: raise ValueError('invalid choice-offered date')
    rows = data['recommendations']
    if not isinstance(rows, list) or len(rows) > 80 or any(not isinstance(r, list) or len(r) != 3 or any(not isinstance(x, str) or len(x) > 20000 for x in r) or r[1] not in ('yes', 'partly', 'no', '') for r in rows): raise ValueError('invalid recommendations')

def save(conn, patient, number, data):
    data = normalize(data)
    records.put_json(conn, patient['id'], f'followup{number}.json', data)
    conn.commit()
    return data

def export(conn, patient, number):
    from docx import Document
    data = load(conn, patient, number); validate(data)
    gaps = review_issues(data)
    folder = jobs.patient_folder(patient)
    name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
    stem = f'HMR Follow-up {number} - {name}'
    doc = Document(); doc.add_heading(stem, 0)
    doc.add_paragraph('Date: ' + data['date'])
    doc.add_paragraph('Delivery method used: ' + LABELS[data['method']])
    doc.add_paragraph("Patient's preferred delivery option: " + LABELS[data['preferred_method']])
    doc.add_paragraph('Delivery choice offered on: ' + (data['choice_offered_on'] or 'Not recorded'))
    if gaps:
        doc.add_paragraph('Review before relying on this record: ' + '; '.join(gaps))
    for key, label in [('spoke_with','Spoke with'), ('med_changes','Medicine changes')]:
        doc.add_paragraph(label + ': ' + data[key])
    doc.add_heading('Recommendations', 2)
    table = doc.add_table(rows=1, cols=3); table.style = 'Table Grid'
    for cell, value in zip(table.rows[0].cells, ('Recommendation', 'Implemented', 'Comment')): cell.text = value
    for row in data['recommendations']:
        for cell, value in zip(table.add_row().cells, row): cell.text = value
    for key, label in [('issues','Issues'), ('outcome','Outcome'), ('notes','Notes')]:
        doc.add_heading(label, 2); doc.add_paragraph(data[key])
    n = 1
    while True:
        target = folder / (stem + (f' ({n})' if n > 1 else '') + '.docx')
        try:
            with target.open('xb') as out: doc.save(out)
            return str(target)
        except FileExistsError: n += 1


def medicine_context(conn, patient):
    """Read-only context from the saved interview, never a current-medication confirmation.

    No parsing of source documents, terminology lookup, status promotion or follow-up changes. A saved
    reference remains visible even when its separately licensed catalog is missing or updated.
    """
    import interview
    content = records.get(conn, patient['id'], 'interview.json')
    if content is None:
        return {'available': False, 'revision': 'missing', 'medicines': []}
    saved = json.loads(content)
    interview.validate(saved)
    result = []
    for key, origin in (('meds', 'Referral'), ('other_meds', 'Found during interview')):
        details = saved.get('details', {}).get(key, [])
        for i, row in enumerate(saved.get(key, [])):
            meta = details[i] if i < len(details) else {}
            result.append({'origin': origin, 'name': row[0],
                           'listed_directions': row[1] if key == 'meds' else '',
                           'interview_directions': row[2] if key == 'meds' else row[1],
                           'use': interview.use_text(meta) or 'Not recorded',
                           'reference': dict(meta['reference']) if interview.valid_reference(meta.get('reference')) else None})
    return {'available': True, 'revision': records.digest(content), 'medicines': result}
