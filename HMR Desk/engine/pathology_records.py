"""Source-traceable pathology entry independent of legacy interview 4-column rows.

No inferred units, clinical risk interpretation or automatic dose decisions.
Patient identifiers and source PDFs remain in the local patient workspace.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import jobs

FIELDS = {'id', 'test', 'value', 'unit', 'reference_interval', 'sample_date', 'source',
          'verified', 'comment'}
MAX_ROWS = 120


def file_for(patient):
    return jobs.patient_folder(patient) / 'pathology_records.json'


def revision(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'missing'


def load(patient):
    path = file_for(patient)
    if not path.is_file():
        return {'version': 1, 'revision': 'missing', 'records': []}
    content = json.loads(path.read_text(encoding='utf-8'))
    validate(content['records'])
    return {'version': 1, 'revision': revision(path), 'records': content['records']}


def validate(records):
    if not isinstance(records, list) or len(records) > MAX_ROWS:
        raise ValueError('Invalid pathology records')
    ids = set()
    for row in records:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError('Invalid pathology record fields')
        if not all(isinstance(row[k], str) and len(row[k]) <= 1000 for k in FIELDS - {'verified'}):
            raise ValueError('Invalid pathology text')
        if type(row['verified']) is not bool:
            raise ValueError('Invalid pathology verification status')
        if not re.fullmatch(r'[a-f0-9]{32}', row['id']) or row['id'] in ids:
            raise ValueError('Invalid or duplicate pathology row ID')
        ids.add(row['id'])
        if row['sample_date']:
            try:
                dt.date.fromisoformat(row['sample_date'])
            except ValueError as exc:
                raise ValueError('Invalid pathology sample date') from exc
        if row['verified'] and not all(row[k].strip() for k in ('test', 'value', 'unit', 'sample_date', 'source')):
            raise ValueError('Verification requires test, value, unit, date and source')
    return True


def save(patient, data):
    if not isinstance(data, dict) or set(data) != {'revision', 'records'}:
        raise ValueError('Invalid pathology save')
    path = file_for(patient)
    if data['revision'] != revision(path):
        raise ValueError('Pathology changed; reload before saving')
    validate(data['records'])
    # A standalone file maintains legacy interview.json compatibility.
    jobs.atomic_json(path, {'version': 1, 'records': data['records']})
    return load(patient)
