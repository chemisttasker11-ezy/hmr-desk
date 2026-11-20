"""Source-traceable pathology entry independent of legacy interview 4-column rows.

No inferred units, clinical risk interpretation or automatic dose decisions.
Patient identifiers and source PDFs remain in the local patient workspace.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import records

FIELDS = {'id', 'test', 'value', 'unit', 'reference_interval', 'sample_date', 'source',
          'verified', 'comment'}
MAX_ROWS = 120
MAX_HISTORY = 2000


NAME = 'pathology_records.json'


def revision(conn, patient):
    return records.revision(conn, patient['id'], NAME)


def load(conn, patient):
    content = records.get_json(conn, patient['id'], NAME)
    if content is None:
        return {'version': 2, 'revision': 'missing', 'records': [], 'verification': {}, 'history': []}
    if content.get('version', 1) not in (1, 2):
        raise ValueError('Unsupported pathology file version')
    validate(content['records'])
    history = content.get('history', [])
    verification = content.get('verification', {})
    if not isinstance(history, list) or len(history) > MAX_HISTORY or not isinstance(verification, dict):
        raise ValueError('Invalid pathology audit metadata')
    return {'version': content.get('version', 1), 'revision': revision(conn, patient),
            'records': content['records'], 'verification': verification, 'history': history}


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


def save(conn, patient, data, reviewer=''):
    if not isinstance(data, dict) or set(data) != {'revision', 'records'}:
        raise ValueError('Invalid pathology save')
    # Compare and write in one write transaction so two saves cannot both pass the check.
    if not conn.in_transaction: conn.execute('BEGIN IMMEDIATE')
    if data['revision'] != revision(conn, patient):
        conn.rollback()
        raise ValueError('Pathology changed; reload before saving')
    validate(data['records'])
    previous = load(conn, patient)
    old = {r['id']: r for r in previous['records']}
    new = {r['id']: r for r in data['records']}
    verification = dict(previous['verification'])
    history = list(previous['history'])
    reviewer = reviewer.strip() if isinstance(reviewer, str) else ''
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    for rid in set(old) | set(new):
        before, after = old.get(rid), new.get(rid)
        if before == after:
            continue
        if before and before['verified'] and after and after['verified']:
            # A value/dose/result amendment invalidates previous verification;
            # a separate reviewer confirmation must follow its unverified save.
            raise ValueError('Changed verified result must be marked unverified and saved before re-verification')
        if after and after['verified'] and (not before or not before['verified']):
            if len(reviewer) < 3:
                raise ValueError('Enter pharmacist name in Settings before verifying pathology')
            verification[rid] = {'verified_by': reviewer[:150], 'verified_at': stamp}
        if not after or not after['verified']:
            verification.pop(rid, None)
        history.append({'row_id': rid, 'at': stamp, 'reviewed_by': reviewer[:150],
                        'before': before, 'after': after})
    if len(history) > MAX_HISTORY:
        raise ValueError('Pathology audit history limit reached; archive old entries before continuing')
    records.put_json(conn, patient['id'], NAME, {'version': 2, 'records': data['records'],
                                                  'verification': verification, 'history': history})
    conn.commit()
    return load(conn, patient)
