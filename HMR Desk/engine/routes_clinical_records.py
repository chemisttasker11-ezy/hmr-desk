"""Clinical record routes: pathology sources and records, medicine reconciliation, interview, medicine context.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import db
import jobs
import records
import settings


def handle(conn, method, path, query, body):
    match = re.fullmatch(r'/api/patients/(\d+)/pathology/sources', path)
    if match and method in ('GET', 'POST'):
        import pathology_import
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET':
            return 200, pathology_import.sources(conn, p)
        if not isinstance(body, dict) or set(body) != {'path'} or not isinstance(body['path'], str):
            raise ValueError('Invalid pathology import')
        result = pathology_import.import_pdf(conn, p, body['path'])
        db.log(conn, p['id'], 'pathology_source_imported',
               {'sha256': result['sha256'], 'pages': result['page_count'], 'name': result['name']}, 'api')
        conn.commit()
        return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/results', path)
    if match and method == 'GET':
        import results
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        return 200, results.for_patient(conn, p)
    match = re.fullmatch(r'/api/patients/(\d+)/pathology-records', path)
    if match and method in ('GET', 'POST'):
        import pathology_records
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET':
            return 200, pathology_records.load(conn, p)
        try:
            result = pathology_records.save(conn, p, body, reviewer=settings.get(conn, 'pharmacist_name'))
        except ValueError as exc:
            if 'changed; reload' in str(exc): return 409, {'error': str(exc)}
            raise
        db.log(conn, p['id'], 'pathology_records_saved',
               {'count': len(result['records']), 'revision': result['revision']}, 'api')
        conn.commit()
        return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/reconciliation', path)
    if match and method in ('GET', 'POST'):
        import interview
        import reconciliation
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        record = interview.load(conn, p)
        saved_review = records.get_json(conn, p['id'], 'reconciliation_review.json') or {}
        if method == 'POST':
            if not isinstance(body, dict) or set(body) != {'source_hash', 'reviewed_by'}: raise ValueError('invalid reconciliation review')
            review = reconciliation.acknowledge(record, body['source_hash'], body['reviewed_by'])
            records.put_json(conn, p['id'], 'reconciliation_review.json', review)
            db.log(conn, p['id'], 'reconciliation_reviewed', {'source_hash': review['source_hash']}, 'api')
            conn.commit()
            return 200, reconciliation.review_status(record, review)
        result = reconciliation.audit(record)
        result.update(reconciliation.review_status(record, saved_review))
        return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/interview/medicine-row-image', path)
    if match and method == 'POST':
        import interview
        import referral_row_image
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        # The row's own evidence travels with the request, so the image can only belong to the row that asked for it.
        if not isinstance(body, dict) or set(body) != {'source_evidence'} or not interview.valid_use({'source_evidence': body['source_evidence']}, set(), set()): raise ValueError('invalid row evidence')
        try: return 200, referral_row_image.render(jobs.patient_folder(p), {'source_evidence': body['source_evidence']})
        except Exception: return 200, {'kind': 'none', 'note': 'The page image could not be produced. Open the original PDF and compare by eye.'}
    match = re.fullmatch(r'/api/patients/(\d+)/interview', path)
    if match:
        import interview
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET': return 200, interview.load(conn, p)
        if method == 'POST':
            try: result = interview.save(conn, p, body)
            except interview.Conflict:
                conn.rollback(); return 409, {'error': 'interview conflict'}
            return 200, result
    match = re.fullmatch(r'/api/patients/(\d+)/medicine-context', path)
    if match and method == 'GET':
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        import followup
        return 200, followup.medicine_context(conn, p)
    return None
