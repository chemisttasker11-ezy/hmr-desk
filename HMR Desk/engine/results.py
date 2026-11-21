"""Per-patient results: the pathology and interaction results held for a patient, in one read-only view.

Composes existing sources only (pathology_records, pathology_import, interaction_scope, steps, report_status).
It decides nothing and gates nothing: it states what is on file, when it was saved and whether the latest
built report was made from it. Clinical text is shown only to the local app; nothing here is sent anywhere.
"""
import os
from pathlib import Path

import interaction_scope
import jobs
import pathology_import
import pathology_records
import report_status
import steps


def _pathology_pdfs(patient):
    root = jobs.patient_folder(patient) / 'Pathology'
    out = []
    if root.is_dir():
        for f in sorted(root.glob('*.pdf')):
            if f.is_file() and not f.is_symlink():
                stat = f.stat()
                out.append({'name': f.name, 'modified': stat.st_mtime_ns // 1_000_000_000, 'bytes': stat.st_size})
    return out


def for_patient(conn, patient):
    records_ = pathology_records.load(conn, patient)
    last = conn.execute("SELECT ts,detail FROM events WHERE patient_id=? AND type='pathology_result' ORDER BY id DESC LIMIT 1",
                        (patient['id'],)).fetchone()
    collection = None
    if last:
        import json
        try: collection = {'at': last['ts'], 'status': (json.loads(last['detail'] or '{}') or {}).get('status', '')}
        except (ValueError, TypeError, AttributeError): collection = {'at': last['ts'], 'status': ''}
    basis = report_status.build_basis(conn, patient)
    return {
        'pathology': {
            'collection': collection,
            'recheck_pending': steps.pathology_recheck_pending(conn, patient),
            'records': [{k: r[k] for k in ('test', 'value', 'unit', 'reference_interval', 'sample_date', 'source', 'verified', 'comment')}
                        for r in records_['records']],
            'record_revision': records_['revision'],
            'source_pdfs': _pathology_pdfs(patient),
            'imported_sources': [{'name': s.get('name', ''), 'pages': s.get('page_count')} for s in pathology_import.sources(conn, patient).get('sources', []) if isinstance(s, dict)],
            'report': basis['pathology'],
        },
        'interactions': {
            'evidence_state': interaction_scope.evidence_state(conn, patient),
            'files': interaction_scope.evidence_files(conn, patient),
            'report': basis['interactions'],
        },
        'report_built_at': basis['built_at'],
        'note': 'Display only. A result being on file is not clinical sign-off. Whether the report used it refers to the whole saved record.',
    }
