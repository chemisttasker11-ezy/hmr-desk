"""Authenticated, conservative, local-only pathology PDF import and source preview.

Documents are copied into the patient folder; all text and candidate rows stay
unconfirmed. Original PDF bytes and SHA256 are retained, with per-page excerpts.
No patient records leave the local machine and no dose decisions are produced.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

import fitz

import jobs
import records

MAX_FILE = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_SOURCES = 80
_LOCK = threading.RLock()


NAME = 'pathology_sources.json'


def sources(conn, patient):
    index = records.get_json(conn, patient['id'], NAME)
    if index is None:
        return {'version': 1, 'sources': []}
    if index.get('version') != 1 or not isinstance(index.get('sources'), list):
        raise ValueError('Invalid pathology source index')
    return index


def import_pdf(conn, patient, file_path):
    source = Path(file_path)
    if not source.is_absolute() or source.is_symlink() or not source.is_file() or source.suffix.lower() != '.pdf':
        raise ValueError('Select a regular pathology PDF')
    with source.open('rb') as f:
        contents = f.read(MAX_FILE + 1)
    if len(contents) > MAX_FILE or not contents.startswith(b'%PDF-'):
        raise ValueError('Pathology PDF is too large or invalid')
    digest = hashlib.sha256(contents).hexdigest()
    try:
        with fitz.open(stream=contents, filetype='pdf') as pdf:
            if pdf.needs_pass:
                raise ValueError('Password-protected PDF requires manual review')
            if not 1 <= pdf.page_count <= MAX_PAGES:
                raise ValueError('Pathology PDF exceeds 100 pages')
            pages = []
            for page in pdf:
                text = page.get_text('text', sort=True).strip()
                pages.append({
                    'page': page.number + 1,
                    'method': 'pdf_text' if len(text) > 20 else 'unreadable_or_scanned',
                    'unconfirmed_excerpt': text[:1500],
                })
    except (fitz.FileDataError, fitz.EmptyFileError) as error:
        raise ValueError('PDF is damaged or unreadable') from error
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError('Source changed during import; review the updated PDF')
    with _LOCK:
        index = sources(conn, patient)
        if len(index['sources']) >= MAX_SOURCES:
            raise ValueError('Maximum pathology source count reached')
        if any(item['sha256'] == digest for item in index['sources']):
            raise ValueError('This exact pathology PDF is already imported')
        patient_dir = jobs.patient_folder(patient).resolve()
        target_dir = patient_dir / 'Pathology'
        if target_dir.is_symlink():
            raise ValueError('Unsafe pathology folder')
        target_dir.mkdir(exist_ok=True)
        if target_dir.resolve().parent != patient_dir or not target_dir.is_dir():
            raise ValueError('Pathology folder must be inside the patient workspace')
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', source.name).strip(' .')
        if not safe or not safe.lower().endswith('.pdf'):
            safe = 'Pathology source.pdf'
        target = target_dir / (uuid.uuid4().hex[:12] + '-' + safe)
        try:
            with target.open('xb') as file:
                file.write(contents)
                file.flush()
                os.fsync(file.fileno())
            record = {
                'id': uuid.uuid4().hex,
                'name': target.name,
                'sha256': digest,
                'page_count': len(pages),
                'pages': pages,
                'verification': 'unconfirmed; pharmacist to compare original image',
            }
            index['sources'].append(record)
            records.put_json(conn, patient['id'], NAME, index)
            conn.commit()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return record
