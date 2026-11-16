import hashlib
import importlib.util
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import db
import fitz

MAX_PDF = 25 * 1024 * 1024
FIELDS = ('name', 'phone', 'address', 'suburb', 'gp', 'clinic', 'referral_date', 'dob', 'sex', 'medicare', 'irn', 'ihi')


def parser():
    path = Path(db.BASE) / 'scripts' / 'intake' / 'intake.py'
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
            if any(len(page.strip()) < 200 for page in pages):
                ocr = module.ocr_pdfs([Path(source)]).get(str(Path(source)), [])
                if len(ocr) != len(pages): raise ValueError('OCR did not return every page')
                pages = [page if len(page.strip()) >= 200 else ocr[i] for i, page in enumerate(pages)]
                if hashlib.sha256(read_pdf(source)).hexdigest() != digest: raise ValueError('Source changed during review; try again')
            kind, _, flags = module.classify('\n'.join(pages))
            fields = {}
            if kind == 'referral':
                fields, more = module.extract_fields('\n'.join(pages[:3])); flags += more
            key = db.patient_key(fields.get('name')) if fields.get('name') else ''
            duplicate = conn.execute('SELECT id FROM patients WHERE key=?', (key,)).fetchone() if key else None
            content_dup = conn.execute("SELECT patient_id FROM events WHERE type='referral_received' AND json_extract(detail, '$.sha256')=? LIMIT 1", (digest,)).fetchone()
            batch_dup = digest in seen_hashes or bool(key and key in seen_keys)
            seen_hashes.add(digest)
            if key: seen_keys.add(key)
            token = uuid.uuid4().hex
            item = {'source': source, 'sha256': digest, 'fields': fields, 'kind': kind}
            conn.execute('INSERT INTO meta(key,value) VALUES (?,?)', ('referral_review_' + token, json.dumps(item)))
            row.update(token=token, kind=kind, fields=fields, flags=flags,
                       status='duplicate' if duplicate or content_dup or batch_dup else ('review' if kind == 'referral' else 'rejected'),
                       duplicate_kind='content' if content_dup or digest in {x.get('sha256') for x in result} else ('identity' if duplicate or batch_dup else None),
                       sha256=digest,
                       patient_id=(duplicate or content_dup)['id' if duplicate else 'patient_id'] if duplicate or content_dup else None)
        except Exception as exc:
            row['message'] = str(exc)
        result.append(row)
    conn.commit()
    return {'rows': result}


def commit(conn, token, fields):
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token): raise ValueError('Invalid review')
    if not isinstance(fields, dict) or not fields.keys() <= set(FIELDS) or any(not isinstance(v, str) for v in fields.values()): raise ValueError('Invalid fields')
    record = conn.execute('SELECT value FROM meta WHERE key=?', ('referral_review_' + token,)).fetchone()
    if not record: raise ValueError('Review expired; review the PDF again')
    item = json.loads(record['value'])
    if item['kind'] != 'referral': raise ValueError('Only classified referrals can be added')
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
        if conn.execute('SELECT 1 FROM patients WHERE key=?', (key,)).fetchone() or conn.execute("SELECT 1 FROM events WHERE type='referral_received' AND json_extract(detail, '$.sha256')=?", (item['sha256'],)).fetchone():
            raise ValueError('Possible duplicate patient or referral; review existing patient')
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
