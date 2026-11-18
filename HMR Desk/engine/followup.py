"""Local follow-up interview records and Word exports."""
import json
import re
from pathlib import Path
import jobs
import records

FIELDS = ('date', 'method', 'spoke_with', 'med_changes', 'recommendations', 'issues', 'outcome', 'notes')

def load(conn, patient, number):
    saved = records.get_json(conn, patient['id'], f'followup{number}.json')
    if saved is not None: return saved
    data = records.get_json(conn, patient['id'], 'report_spec.json') or {}
    return dict(date='', method='phone', spoke_with='', med_changes='', recommendations=[[i['rec'], '', ''] for i in data.get('issues', []) if i.get('rec')], issues='', outcome='', notes='')

def validate(data):
    if not isinstance(data, dict) or set(data) != set(FIELDS): raise ValueError('invalid follow-up fields')
    if any(not isinstance(data[k], str) or len(data[k]) > 20000 for k in FIELDS if k != 'recommendations'): raise ValueError('invalid follow-up text')
    if data['method'] not in ('phone', 'in person'): raise ValueError('invalid method')
    rows = data['recommendations']
    if not isinstance(rows, list) or len(rows) > 80 or any(not isinstance(r, list) or len(r) != 3 or any(not isinstance(x, str) or len(x) > 20000 for x in r) or r[1] not in ('yes', 'partly', 'no', '') for r in rows): raise ValueError('invalid recommendations')

def save(conn, patient, number, data):
    records.put_json(conn, patient['id'], f'followup{number}.json', data)
    conn.commit()
    return data

def export(conn, patient, number):
    from docx import Document
    data = load(conn, patient, number); validate(data)
    folder = jobs.patient_folder(patient)
    name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
    stem = f'HMR Follow-up {number} - {name}'
    doc = Document(); doc.add_heading(stem, 0)
    for key, label in [('date','Date'), ('method','Method'), ('spoke_with','Spoke with'), ('med_changes','Medicine changes')]:
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
