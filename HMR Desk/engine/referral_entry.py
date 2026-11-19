import hashlib
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import clinical_review
import db
import app_paths
import fitz

MAX_PDF = 25 * 1024 * 1024
MAX_PAGES = 150
MAX_TEXT_PER_PAGE = 150000
FIELDS = ('name', 'phone', 'address', 'suburb', 'gp', 'clinic', 'referral_date', 'dob', 'sex', 'medicare', 'irn', 'ihi')


def parser():
    path = app_paths.resource_root() / 'scripts' / 'intake' / 'intake.py'
    spec = importlib.util.spec_from_file_location('referral_parser', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UNRECOGNISED_LAYOUT_FLAG = ('This PDF layout is not one the app reads medicines, conditions or allergies from, so they will not be '
                            'pre-filled at the interview either. Enter them from the original PDF.')


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
                if not 1 <= doc.page_count <= MAX_PAGES:
                    raise ValueError('PDF page count exceeds the 150-page intake limit')
                pages = [p.get_text()[:MAX_TEXT_PER_PAGE] for p in doc]
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
            # Intake never fills the clinical box: the pharmacist enters it from the original. Later, the interview can
            # read medicines, conditions and allergies only from recognised referral layouts, so say plainly when
            # this PDF is not one. A flag only; nothing is inferred or changed.
            import referral
            if referral.layout('\n'.join(pages)) not in ('clinical summary', 'HMR referral form'):
                flags.append(UNRECOGNISED_LAYOUT_FLAG)
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
            excerpts = [{'page': i + 1, 'method': methods[i], 'text': text[:1200]}
                        for i, text in enumerate(pages[:20])]
            item = {'source': source, 'sha256': digest, 'fields': fields, 'kind': kind,
                    'page_previews': excerpts, 'page_count': len(pages), 'flags': flags}
            conn.execute('INSERT INTO meta(key,value) VALUES (?,?)', ('referral_review_' + token, json.dumps(item)))
            row.update(token=token, kind=kind, fields=fields, flags=flags,
                       page_previews=excerpts,
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


def _validate_date(value, field):
    value = (value or '').strip()
    if not value:
        return
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %B %Y'):
        try:
            parsed = dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
        if field == 'dob' and parsed > dt.date.today():
            raise ValueError('Date of birth cannot be in the future')
        return
    raise ValueError('Invalid ' + ('date of birth' if field == 'dob' else 'referral date') +
                     '; confirm the exact date from the original PDF')


CLINICAL_FIELDS = clinical_review.FIELDS


def _review_pages(value, page_count):
    """Accept per-field pages, or a version 1 single page applied to populated fields."""
    if 'source_pages' in value:
        pages = value['source_pages']
        if not isinstance(pages, dict) or set(pages) != set(CLINICAL_FIELDS):
            raise ValueError('Invalid per-field PDF source pages')
    else:
        legacy = value['source_page']
        if type(legacy) is not int:
            raise ValueError('Invalid PDF source page number')
        pages = {field: legacy if clinical_review.populated(value, field) else 0
                 for field in CLINICAL_FIELDS}
    for page in pages.values():
        if type(page) is not int or not 0 <= page <= page_count:
            raise ValueError('Invalid PDF source page number')
    return {field: pages[field] for field in CLINICAL_FIELDS}


def validate_clinical_review(value, page_count):
    """No inferred negatives. Only a named reviewer may confirm source text.

    Each populated clinical field needs its own original PDF page.
    """
    if value is None:
        return {'version': 2, 'confirmed': False, 'allergies_status': 'unknown',
                'source_pages': {key: 0 for key in CLINICAL_FIELDS}, 'reviewed_by': '',
                **{key: '' for key in CLINICAL_FIELDS}}
    base = {'confirmed', 'allergies_status', 'reviewed_by', *CLINICAL_FIELDS}
    if not isinstance(value, dict) or type(value.get('confirmed')) is not bool:
        raise ValueError('Invalid clinical source review')
    if set(value) not in (base | {'source_page'}, base | {'source_pages'}):
        raise ValueError('Invalid clinical source review')
    if value['allergies_status'] not in ('unknown', 'explicit_none', 'listed'):
        raise ValueError('Invalid allergy documentation state')
    if any(not isinstance(value[key], str) or len(value[key]) > 10000 for key in (*CLINICAL_FIELDS, 'reviewed_by')):
        raise ValueError('Invalid clinical review text')
    pages = _review_pages(value, page_count)
    text = {key: value[key].strip() for key in (*CLINICAL_FIELDS, 'reviewed_by')}
    checked = {**value, **text}
    if value['confirmed']:
        if len(text['reviewed_by']) < 3:
            raise ValueError('Source page and reviewing pharmacist are required for confirmed clinical fields')
        filled = [key for key in CLINICAL_FIELDS if clinical_review.populated(checked, key)]
        if not filled:
            raise ValueError('Source page and reviewing pharmacist are required for confirmed clinical fields')
        for key in filled:
            if pages[key] < 1:
                raise ValueError('Source page is required for each confirmed clinical field: ' + key)
        for key in CLINICAL_FIELDS:
            if key not in filled and pages[key]:
                raise ValueError('A source page was given for an empty clinical field: ' + key)
    if value['confirmed'] and value['allergies_status'] == 'listed' and not text['allergies']:
        raise ValueError('Explicitly listed allergies require source-verified allergy details')
    if value['confirmed'] and value['allergies_status'] == 'explicit_none' and text['allergies']:
        raise ValueError('Explicitly no known allergies cannot be combined with an allergy list')
    if not value['confirmed'] and value['allergies_status'] == 'explicit_none':
        raise ValueError('Do not record no known allergies without explicit source confirmation')
    return {'version': 2, 'confirmed': value['confirmed'], 'allergies_status': value['allergies_status'],
            'source_pages': pages, 'reviewed_by': text['reviewed_by'],
            **{key: text[key] for key in CLINICAL_FIELDS}}


def commit(conn, token, fields, distinct_person=False, manual_referral=False, clinical=None):
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token): raise ValueError('Invalid review')
    if type(distinct_person) is not bool or type(manual_referral) is not bool: raise ValueError('Invalid pharmacist acknowledgement')
    if not isinstance(fields, dict) or not fields.keys() <= set(FIELDS) or any(not isinstance(v, str) for v in fields.values()): raise ValueError('Invalid fields')
    for key in ('dob', 'referral_date'):
        _validate_date(fields.get(key), key)
    record = conn.execute('SELECT value FROM meta WHERE key=?', ('referral_review_' + token,)).fetchone()
    if not record: raise ValueError('Review expired; review the PDF again')
    item = json.loads(record['value'])
    clinical_review = validate_clinical_review(clinical, item.get('page_count', 1))
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
        with target.open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        source_record = {
            'schema_version': 1, 'sha256': item['sha256'], 'original_filename': Path(item['source']).name,
            'page_excerpts_unconfirmed': item.get('page_previews', []),
            'extraction_flags': item.get('flags', []),
            'confirmed_identity_fields': {k: v.strip() for k, v in fields.items()},
            'manual_source_classification': bool(manual_referral),
            'clinical_review': clinical_review,
            'source_truth': 'original referral.pdf; extracted fields require pharmacist source review',
        }
        with (folder / 'referral_source.json').open('x', encoding='utf-8') as f:
            json.dump(source_record, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
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
                    if left and right and re.sub(r'\D', '', left) == re.sub(r'\D', '', right):
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
        # Materialize the interview record at intake so referral-derived medicines and
        # their unconfirmed exact-unique proposals are ready before the interview.
        # A quiet record write inside one transaction: no workflow events, sheet
        # flags, consent files or medicine-ID assignment - those belong to the
        # pharmacist's own first save. Never confirms a medicine and never
        # overwrites an existing record; failure rolls back only this
        # materialization, and the record is built on first interview open instead.
        try:
            import interview
            import records
            patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
            if records.get(conn, pid, 'interview.json') is None:
                data = interview.load(conn, patient)
                # Attached only here: a persisted proposal always means prepared
                # at intake. Records built later on first interview open never
                # carry one, so the interview cannot show false intake provenance.
                interview.prepare_prefill_proposals(data)
                interview.validate(data)
                stored = {k: v for k, v in data.items() if k not in ('saved', 'consent_file', 'revision')}
                records.put(conn, pid, 'interview.json', json.dumps(stored, ensure_ascii=False, indent=2).encode('utf-8'))
                db.log(conn, pid, 'interview_prepared_at_intake', {}, 'intake')
                conn.commit()
        except Exception:
            conn.rollback()
        return {'patient_id': pid}
    except Exception:
        conn.rollback()
        shutil.rmtree(folder)
        raise
