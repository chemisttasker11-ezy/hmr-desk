import hashlib
import importlib.util
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import db
import app_paths
import fitz

MAX_PDF = 25 * 1024 * 1024
FIELDS = ('name', 'phone', 'address', 'suburb', 'gp', 'clinic', 'referral_date', 'dob', 'sex', 'medicare', 'irn', 'ihi')


def parser():
    path = app_paths.resource_root() / 'scripts' / 'intake' / 'intake.py'
    spec = importlib.util.spec_from_file_location('referral_parser', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_pdf(path):
    path = Path(path)
    if not path.is_absolute() or path.suffix.lower() != '.pdf' or path.is_symlink() or not path.is_file():
        raise ValueError('Choose a regular PDF file')
    with path.open('rb') as f:
        data = f.read(MAX_PDF + 1)
    if len(data) > MAX_PDF: raise ValueError('PDF exceeds 25 MB')
    if not data.startswith(b'%PDF-'): raise ValueError('File is not a PDF')
    return data


def review(conn, paths):
    if not isinstance(paths, list) or not paths or len(paths) > 100 or any(not isinstance(p, str) for p in paths):
        raise ValueError('Choose up to 100 PDF files')
    module = parser()
    result = []
    seen_hashes, seen_keys = set(), set()
    for source in paths:
        row = {'file': Path(source).name, 'status': 'error'}
        try:
            data = read_pdf(source)
            digest = hashlib.sha256(data).hexdigest()
            with fitz.open(stream=data, filetype='pdf') as doc:
                if doc.needs_pass: raise ValueError('PDF is password protected')
                pages = [p.get_text() for p in doc]
            if not pages: raise ValueError('PDF has no pages')
            methods = ['text' if len(page.strip()) >= 25 else 'ocr' for page in pages]
            ocr_flags = []
            if 'ocr' in methods:
                try:
                    ocr = module.ocr_pdfs([Path(source)]).get(str(Path(source)), [])
                except Exception:
                    ocr = []
                if len(ocr) == len(pages):
                    pages = [page if len(page.strip()) >= 25 else (ocr[i] or '') for i, page in enumerate(pages)]
                else:
                    ocr_flags.append('OCR unavailable or incomplete: inspect the original PDF and enter referral details manually')
                if hashlib.sha256(read_pdf(source)).hexdigest() != digest: raise ValueError('Source changed during review; try again')
            kind, _, flags = module.classify('\n'.join(pages))
            flags.extend(ocr_flags)
            fields = {}
            if kind == 'referral':
                fields, more = module.extract_fields('\n'.join(pages[:3])); flags += more
            key = db.patient_key(fields.get('name')) if fields.get('name') else ''
            candidates = conn.execute('SELECT id,name,dob,medicare,ihi,gp FROM patients WHERE key=? OR key LIKE ?', (key, key + ' @%')).fetchall() if key else []
            duplicate = candidates[0] if candidates else None
            content_dup = conn.execute("SELECT patient_id FROM events WHERE type='referral_received' AND json_extract(detail, '$.sha256')=? LIMIT 1", (digest,)).fetchone()
            batch_dup = digest in seen_hashes or bool(key and key in seen_keys)
            seen_hashes.add(digest)
            if key: seen_keys.add(key)
            token = uuid.uuid4().hex
            item = {'source': source, 'sha256': digest, 'fields': fields, 'kind': kind}
            conn.execute('INSERT INTO meta(key,value) VALUES (?,?)', ('referral_review_' + token, json.dumps(item)))
            row.update(token=token, kind=kind, fields=fields, flags=flags,
                       page_previews=[{'page': i + 1, 'method': methods[i],
                                       'text': text[:1200]} for i, text in enumerate(pages[:20])],
                       status='duplicate' if duplicate or content_dup or batch_dup else ('review' if kind == 'referral' else 'manual'),
                       duplicate_kind='content' if content_dup or digest in {x.get('sha256') for x in result} else ('identity' if duplicate or batch_dup else None),
                       sha256=digest,
                       patient_id=(duplicate or content_dup)['id' if duplicate else 'patient_id'] if duplicate or content_dup else None,
                       duplicate_candidates=[{'id': candidate['id'], 'name': candidate['name'],
                                              'dob': candidate['dob'], 'gp': candidate['gp']} for candidate in candidates])
        except Exception as exc:
            row['message'] = str(exc)
        result.append(row)
    conn.commit()
    return {'rows': result}


def commit(conn, token, fields, distinct_person=False, manual_referral=False):
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token): raise ValueError('Invalid review')
    if type(distinct_person) is not bool or type(manual_referral) is not bool: raise ValueError('Invalid pharmacist acknowledgement')
    if not isinstance(fields, dict) or not fields.keys() <= set(FIELDS) or any(not isinstance(v, str) for v in fields.values()): raise ValueError('Invalid fields')
    record = conn.execute('SELECT value FROM meta WHERE key=?', ('referral_review_' + token,)).fetchone()
    if not record: raise ValueError('Review expired; review the PDF again')
    item = json.loads(record['value'])
    if item['kind'] != 'referral' and not manual_referral: raise ValueError('Unrecognised PDF requires explicit pharmacist confirmation as an HMR referral')
    data = read_pdf(item['source'])
    if hashlib.sha256(data).hexdigest() != item['sha256']: raise ValueError('Source changed; review the PDF again')
    name = fields.get('name', '').strip()
    key = db.patient_key(name)
    if not key: raise ValueError('Patient name is required')
    folder = Path(db.BASE) / 'TO SORT' / ('Referral-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    try:
        target = folder / 'referral.pdf'
        with target.open('xb') as f: f.write(data)
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM events WHERE type='referral_received' AND json_extract(detail, '$.sha256')=?", (item['sha256'],)).fetchone():
            raise ValueError('This exact referral was already added')
        candidates = conn.execute('SELECT id,dob,medicare,ihi FROM patients WHERE key=? OR key LIKE ?',
                                  (key, key + ' @%')).fetchall()
        if candidates:
            if not distinct_person: raise ValueError('Patient name matches an existing record; compare reliable identifiers and explicitly confirm a different person')
            for candidate in candidates:
                for identifier in ('ihi', 'medicare'):
                    left, right = (fields.get(identifier) or '').strip(), (candidate[identifier] or '').strip()
                    if left and right and re.sub(r'\\D', '', left) == re.sub(r'\\D', '', right):
                        raise ValueError('Identifier matches an existing patient; do not create a separate identity')
                dob = (fields.get('dob') or '').strip()
                if dob and candidate['dob'] and dob == candidate['dob']:
                    raise ValueError('Name and date of birth match an existing patient; review existing record')
                compared = any((fields.get(field) or '').strip() and candidate[field] and
                               (fields.get(field) or '').strip() != candidate[field] for field in ('dob', 'ihi', 'medicare'))
                if not compared:
                    raise ValueError('Different reliable identifiers are required before adding a same-name patient')
            key = key + ' @' + uuid.uuid4().hex[:12]
        cols = list(FIELDS)
        values = [fields.get(col, '').strip() or None for col in cols]
        cursor = conn.execute('INSERT INTO patients (key,folder,' + ','.join(cols) + ') VALUES (' + ','.join('?' for _ in range(len(cols)+2)) + ')', [key, os.path.relpath(folder, db.BASE), *values])
        pid = cursor.lastrowid
        db.log(conn, pid, 'referral_received', {'file': Path(item['source']).name, 'source': item['source'], 'sha256': item['sha256'], 'folder': os.path.relpath(folder, db.BASE)}, 'intake')
        conn.execute('DELETE FROM meta WHERE key=?', ('referral_review_' + token,))
        conn.commit()
        return {'patient_id': pid}
    except Exception:
        conn.rollback()
        shutil.rmtree(folder)
        raise
