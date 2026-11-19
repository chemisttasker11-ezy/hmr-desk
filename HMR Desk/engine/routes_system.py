"""System routes: templates, medicine reference, records, backups, storage, settings and AI agents.

Each handler is moved verbatim from api.handle. handle() returns (status, payload) for a route it
owns and None otherwise, so api.handle falls through to its remaining routes. ValueError and
TypeError still propagate to api.handle, which turns them into the same 400 response.
"""
import re
from pathlib import Path

import agents
import db
import jobs
import medicine_reference
import records
import settings


def handle(conn, method, path, query, body):
    if path == '/api/agents' and method == 'GET': return 200, agents.public(agents.load())
    if path == '/api/templates/register' and method == 'POST':
        import template_report_builder
        if not isinstance(body, dict) or set(body) != {'source', 'version', 'approved_by', 'owner_authorised'}:
            raise ValueError('Invalid template registration request')
        result = template_report_builder.register(
            body['source'], body['version'], body['approved_by'], body['owner_authorised']
        )
        db.log(conn, None, 'template_registered',
               {'version': result['version'], 'sha256': result['sha256'],
                'approved_by': result['approved_by']}, 'app')
        conn.commit()
        return 200, result
    if path == '/api/medicine-reference/install' and method == 'POST':
        if not isinstance(body, dict) or set(body) != {'source'}:
            raise ValueError('Invalid medicine reference request')
        result = medicine_reference.install(body['source'])
        db.log(conn, None, 'medicine_reference_installed',
               {'sources': [s['source'] for s in result['sources']]}, 'app')
        conn.commit()
        return 200, result
    if path == '/api/medicines/status' and method == 'GET':
        return 200, medicine_reference.status()
    if path == '/api/medicines/suggest' and method == 'POST':
        if not isinstance(body, dict) or set(body) != {'queries'}: raise ValueError('Invalid suggestion request')
        return 200, medicine_reference.suggest_many(body['queries'])
    if path == '/api/medicines/search' and method == 'GET':
        q = query.get('q', ''); q = q[0] if isinstance(q, list) and q else q
        if not isinstance(q, str): raise ValueError('invalid search')
        flag = query.get('grouped', ''); flag = flag[0] if isinstance(flag, list) and flag else flag
        if flag == '1':
            return 200, medicine_reference.search_grouped(q)
        return 200, medicine_reference.search(q)
    if path == '/api/records/status' and method == 'GET':
        return 200, records.status(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
    if path == '/api/records/migrate' and method == 'POST':
        return 200, records.migrate_all(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
    if path == '/api/records/retire' and method == 'POST':
        if body != {'confirmed': True}: raise ValueError('Confirmation required')
        result = records.retire_matching(conn, lambda row: jobs.patient_folder(row), jobs.outside_files)
        db.log(conn, None, 'record_plain_copies_removed', result, 'api')
        conn.commit()
        return 200, result
    if path == '/api/records/export' and method == 'POST':
        if not isinstance(body, dict) or set(body) != {'patient_id', 'destination'} or not isinstance(body['patient_id'], int): raise ValueError('invalid export input')
        row = conn.execute('SELECT * FROM patients WHERE id=?', (body['patient_id'],)).fetchone()
        if not row and body['patient_id'] != records.GLOBAL_PATIENT: raise ValueError('patient not found')
        dest = Path(body['destination']) if isinstance(body['destination'], str) else None
        if not dest or not dest.is_absolute() or dest.is_symlink(): raise ValueError('choose an export folder')
        resolved = dest.resolve()
        for guarded in (Path(db.DATA_DIR).resolve(), Path(db.BASE).resolve()):
            if resolved == guarded or guarded in resolved.parents: raise ValueError('export outside the app data and the patient workspace')
        result = records.export_folder(conn, body['patient_id'], resolved)
        db.log(conn, row['id'] if row else None, 'records_exported', {'count': len(result)}, 'api')
        conn.commit()
        return 200, {'files': result, 'folder': str(resolved), 'warning': 'This copy is outside the encryption HMR Desk applies to its own storage.'}
    if path == '/api/backups/create' and method == 'POST':
        import backup_bundle
        if not isinstance(body, dict) or set(body) != {'target', 'passphrase'}: raise ValueError('invalid backup input')
        return 200, backup_bundle.create(conn, db.BASE, body['target'], body['passphrase'])
    if path == '/api/backups/preview' and method == 'POST':
        import backup_bundle
        if not isinstance(body, dict) or set(body) != {'source', 'passphrase'}: raise ValueError('invalid backup preview')
        return 200, backup_bundle.restore(body['source'], None, body['passphrase'], preview_only=True)
    if path == '/api/backups/validate-isolated' and method == 'POST':
        import backup_bundle
        if not isinstance(body, dict) or set(body) != {'destination'} or not isinstance(body['destination'], str):
            raise ValueError('Invalid isolated recovery validation')
        return 200, backup_bundle.verify_isolated(body['destination'])
    if path == '/api/backups/restore' and method == 'POST':
        import backup_bundle
        if not isinstance(body, dict) or set(body) != {'source', 'destination', 'passphrase'}: raise ValueError('invalid restore input')
        # Restore into a new, isolated directory; NEVER replace an active database.
        return 200, backup_bundle.restore(body['source'], body['destination'], body['passphrase'])
    if path == '/api/storage/status' and method == 'GET':
        return 200, db.storage_status()
    if path == '/api/storage/recovery-key' and method == 'POST':
        import dbkey
        try:
            return 200, {'recovery_key': dbkey.reveal_recovery_key(db.db_path())}
        except dbkey.RecoveryKeyError as exc:
            return 409, {'error': str(exc)}
    if path == '/api/storage/recovery-key/confirm' and method == 'POST':
        import dbkey
        return 200, dbkey.acknowledge_recovery_key(db.db_path())
    if path == '/api/storage/rotate' and method == 'POST':
        recovery = db.rotate_key(conn)
        db.log(conn, None, 'storage_key_rotated', {}, 'app'); conn.commit()
        return 200, {'recovery_key': recovery}
    if path == '/api/settings' and method == 'GET': return 200, {'settings': settings.listing(conn)}
    if path == '/api/settings' and method == 'POST':
        settings.update(conn, body); db.log(conn, None, 'settings_updated', {'keys': list(body)}, 'api'); conn.commit()
        return 200, {'ok': True}
    if path == '/api/agents' and method == 'POST':
        agents.put(body); return 200, {'ok': True}
    if path == '/api/agents/delete' and method == 'POST':
        if not isinstance(body, dict): raise ValueError('invalid body')
        agents.delete(body.get('name')); return 200, {'ok': True}
    if path == '/api/agents/select' and method == 'POST':
        agents.select(body); return 200, {'ok': True}
    if path == '/api/agents/test' and method == 'POST':
        if not isinstance(body, dict): raise ValueError('invalid body')
        return 200, {'reply': agents.run(body.get('name'), 'Reply with the single word OK.', test=True)[:200]}
    return None
