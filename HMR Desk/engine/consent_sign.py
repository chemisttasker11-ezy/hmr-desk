import base64
import binascii
import datetime as dt
import re
import os
import tempfile

import fitz
import interview
import jobs


def unsigned_path(patient):
    name = re.sub(r'[<>:"/\\|?*]', '', patient['name']).rstrip(' .')
    return jobs.patient_folder(patient) / ('PPA Consent - ' + name + '.pdf')


def form(conn, patient, record):
    target = unsigned_path(patient)
    if not target.exists():
        template = interview.consent_template()
        if not template or template.suffix.lower() != '.pdf': raise ValueError('PDF consent template missing')
    interview.fill_consent(conn, patient, record, target)
    return target


def preview(conn, patient):
    with interview.record_lock(patient): return preview_locked(conn, patient)

def preview_locked(conn, patient):
    record = interview.load(conn, patient)
    folder = jobs.patient_folder(patient)
    signed = interview.signed_file(folder)
    path = folder / signed[0] if signed else form(conn, patient, record)
    with fitz.open(path) as pdf:
        if len(pdf) < 2: raise ValueError('consent form has no page 2')
        png = pdf[1].get_pixmap(matrix=fitz.Matrix(110 / 72, 110 / 72), alpha=False).tobytes('png')
    return {'png': base64.b64encode(png).decode('ascii'), 'by': record['consent']['by'], 'signed_file': signed[0] if signed else '', 'revision': record['revision']}


def sign(conn, patient, encoded, revision):
    with interview.record_lock(patient):
        return sign_locked(conn, patient, encoded, revision)

def sign_locked(conn, patient, encoded, revision):
    if not isinstance(encoded, str) or len(encoded) > ((2 * 1024 * 1024 + 2) // 3) * 4: raise ValueError('invalid PNG')
    try: image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError): raise ValueError('invalid PNG') from None
    if len(image) > 2 * 1024 * 1024 or not image.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('invalid PNG')
    try: pix = fitz.Pixmap(image)
    except Exception: raise ValueError('invalid PNG') from None
    if pix.width < 1 or pix.height < 1: raise ValueError('invalid PNG')
    folder = jobs.patient_folder(patient)
    if interview.signed_file(folder): raise ValueError('signed file already exists')
    record = interview.load(conn, patient)
    if record['revision'] != revision: raise interview.Conflict('interview conflict')
    consent = record['consent']
    if consent['by'] == 'authorised' and (not consent['relationship'] or not consent['authorised_name'].strip()): raise ValueError('authorised person name and relationship required')
    if not record['consent']['date']:
        visit = str(patient['visit_date'] or '')[:10]
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                record['consent']['date'] = dt.datetime.strptime(visit, fmt).strftime('%Y-%m-%d')  # same format as the app's date input
                break
            except ValueError: pass
        if not record['consent']['date']: raise ValueError('valid visit date required')
    path = form(conn, patient, record)
    target = path.with_name(path.stem + ' signed.pdf')
    with fitz.open(path) as pdf:
        if len(pdf) < 2: raise ValueError('consent form has no page 2')
        page = pdf[1]
        field = 'Patient signature' if record['consent']['by'] == 'patient' else 'Authorised Person Signature'
        widget = next ( (w for w in page.widgets() or [] if w.field_name == field), None)
        if not widget or widget.rect.is_empty: raise ValueError('signature field missing')
        page.insert_image(widget.rect, stream=image, keep_proportion=True, overlay=True)
        content = pdf.tobytes()
    created = False
    try:
        with target.open('xb') as out:
            created = True
            out.write(content)
        record['consent']['signed'] = True
        record['consent_signed_draft'] = False
        interview.save(conn, patient, record, locked=True, signing=True)
        conn.commit()
    except Exception:
        conn.rollback()
        if created: target.unlink(missing_ok=True)
        raise
    return {'file': target.name}
