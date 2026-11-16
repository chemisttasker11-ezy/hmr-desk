"""Encrypted record store: import, export, conflict safety."""
import contextlib
import pytest
import db, records


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    (tmp_path / 'workspace').mkdir(); (tmp_path / 'userdata').mkdir()
    monkeypatch.delenv('HMR_DB_KEY', raising=False)
    with contextlib.closing(db.connect(str(tmp_path / 'userdata' / 'hmr.db'))) as c:
        yield c


def test_put_get_revision_and_conflict(conn):
    assert records.get(conn, 1, 'interview.json') is None
    assert records.revision(conn, 1, 'interview.json') == 'missing'
    rev = records.put(conn, 1, 'interview.json', b'{"a":1}', expected_revision='missing')
    assert records.get(conn, 1, 'interview.json') == b'{"a":1}'
    assert rev == records.revision(conn, 1, 'interview.json')
    with pytest.raises(records.Conflict):
        records.put(conn, 1, 'interview.json', b'{"a":2}', expected_revision='missing')
    assert records.get(conn, 1, 'interview.json') == b'{"a":1}'


def test_rejects_unknown_names(conn):
    for bad in ('../x.json', 'notes.txt', 'interview.json/../x'):
        with pytest.raises(ValueError):
            records.put(conn, 1, bad, b'x')


def test_rollback_with_transaction(conn):
    conn.commit()
    records.put(conn, 1, 'report_spec.json', b'{}')
    conn.rollback()
    assert records.get(conn, 1, 'report_spec.json') is None


def test_import_copies_verifies_and_keeps_files(conn, tmp_path):
    folder = tmp_path / 'p'; folder.mkdir()
    (folder / 'interview.json').write_bytes(b'{"synthetic":true}')
    (folder / 'interview.json.bak').write_bytes(b'{"old":true}')
    (folder / 'other.pdf').write_bytes(b'%PDF')
    assert records.import_folder(conn, 7, folder) == {'interview.json': 'imported', 'interview.json.bak': 'imported'}
    assert (folder / 'interview.json').read_bytes() == b'{"synthetic":true}'
    assert records.import_folder(conn, 7, folder) == {'interview.json': 'already', 'interview.json.bak': 'already'}
    assert sorted(p.name for p in records.removable_files(conn, 7, folder)) == ['interview.json', 'interview.json.bak']


def test_import_never_overwrites_newer_database_record(conn, tmp_path):
    folder = tmp_path / 'p'; folder.mkdir()
    records.put(conn, 7, 'interview.json', b'{"newer":true}'); conn.commit()
    (folder / 'interview.json').write_bytes(b'{"older":true}')
    assert records.import_folder(conn, 7, folder) == {'interview.json': 'conflict'}
    assert records.get(conn, 7, 'interview.json') == b'{"newer":true}'
    assert (folder / 'interview.json').read_bytes() == b'{"older":true}'
    assert records.removable_files(conn, 7, folder) == []


def test_export_is_verbatim_labelled_and_never_overwrites(conn, tmp_path):
    records.put(conn, 3, 'confirmed_meds.json', b'{"meds":[]}'); conn.commit()
    out = tmp_path / 'export'
    assert records.export_folder(conn, 3, out) == {'confirmed_meds.json': 'written'}
    assert (out / 'confirmed_meds.json').read_bytes() == b'{"meds":[]}'
    assert 'OUTSIDE the encryption' in (out / records.EXPORT_NOTE).read_text(encoding='utf-8')
    (out / 'confirmed_meds.json').write_bytes(b'edited')
    assert records.export_folder(conn, 3, out) == {'confirmed_meds.json': 'exists'}
    assert (out / 'confirmed_meds.json').read_bytes() == b'edited'


def test_export_import_round_trip(conn, tmp_path):
    records.put(conn, 3, 'report_spec.json', b'{"issues":[1]}'); conn.commit()
    out = tmp_path / 'export'
    records.export_folder(conn, 3, out)
    assert records.import_folder(conn, 4, out) == {'report_spec.json': 'imported'}
    assert records.get(conn, 4, 'report_spec.json') == b'{"issues":[1]}'


def test_record_name_patterns(conn):
    for ok in ('followup1.json', 'pathology_records.json', 'reconciliation_review.json', 'MIMS interactions (manual) 2026-01-01.txt', 'report_spec.ai.json.bak'):
        assert records.is_record_name(ok), ok
    for bad in ('followup3.json', 'drug_classes.json', 'clinics.json', 'report.docx', 'MIMS interactions/../x.txt', 'a/interview.json', 'HMR Interview x.docx'):
        assert not records.is_record_name(bad), bad


def _patient(conn, tmp_path, folder_name='A'):
    folder = tmp_path / 'workspace' / 'Scheduled' / folder_name
    folder.mkdir(parents=True)
    pid = conn.execute("INSERT INTO patients(key,name,state,folder) VALUES (?,?,?,?)",
                       ('k' + folder_name, 'Synthetic ' + folder_name, 'visited', 'Scheduled/' + folder_name)).lastrowid
    conn.commit()
    return pid, folder


def test_migrate_all_is_repeat_safe_and_never_overwrites(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{"notes":"old"}')
    (folder / 'confirmed_meds.json').write_bytes(b'{"meds":[]}')
    (folder / 'referral.pdf').write_bytes(b'%PDF-1.4 synthetic')
    folder_for = lambda row: jobs.patient_folder(row)
    first = records.migrate_all(conn, folder_for)
    assert first['imported'] == 2 and first['conflict'] == 0
    records.put(conn, pid, 'interview.json', b'{"notes":"newer"}'); conn.commit()
    again = records.migrate_all(conn, folder_for)
    assert again['imported'] == 0 and again['conflict'] == 1 and again['already'] == 1
    assert records.get(conn, pid, 'interview.json') == b'{"notes":"newer"}'
    assert (folder / 'interview.json').read_bytes() == b'{"notes":"old"}'  # plain file left alone
    assert (folder / 'referral.pdf').exists() and records.names(conn, pid) == ['confirmed_meds.json', 'interview.json']


def test_status_never_claims_protection_while_plain_files_remain(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{"a":1}')
    folder_for = lambda row: jobs.patient_folder(row)
    before = records.status(conn, folder_for)
    assert before['plain_files_differing_or_not_stored'] == 1 and before['saved_records_protected'] is False
    records.migrate_all(conn, folder_for)
    after = records.status(conn, folder_for)
    assert after['plain_copies_matching_store'] == 1 and after['records_in_encrypted_store'] == 1
    assert after['saved_records_protected'] is False


def test_export_api_writes_labelled_copy_and_refuses_app_folders(conn, tmp_path):
    import api
    pid, folder = _patient(conn, tmp_path)
    records.put(conn, pid, 'interview.json', b'{"a":1}'); records.put(conn, pid, 'MIMS interactions x.txt', b'synthetic'); conn.commit()
    out = tmp_path / 'export'
    status, body = api.handle(conn, 'POST', '/api/records/export', {}, {'patient_id': pid, 'destination': str(out)})
    assert status == 200 and (out / 'interview.json').read_bytes() == b'{"a":1}'
    assert 'OUTSIDE' in (out / records.EXPORT_NOTE).read_text(encoding='utf-8') and 'licence' in (out / records.EXPORT_NOTE).read_text(encoding='utf-8')
    assert 'outside the encryption' in body['warning']
    for bad in (str(tmp_path / 'workspace' / 'Scheduled' / 'A'), str(tmp_path / 'userdata'), 'relative'):
        status, _ = api.handle(conn, 'POST', '/api/records/export', {}, {'patient_id': pid, 'destination': bad})
        assert status == 400


def test_backup_bundle_carries_records(conn, tmp_path):
    import backup_bundle
    pid, folder = _patient(conn, tmp_path)
    records.put(conn, pid, 'interview.json', b'{"notes":"synthetic backup"}'); conn.commit()
    out = tmp_path / 'bk' / 'b.hmrbackup'
    backup_bundle.create(conn, tmp_path / 'workspace', out, 'synthetic-pass-123')
    dest = tmp_path / 'restored'
    backup_bundle.restore(out, dest, 'synthetic-pass-123')
    import sqlite3
    found = None
    for p in dest.rglob('hmr.db'):
        try:
            c2 = db.connect(str(p)); found = records.get(c2, pid, 'interview.json'); c2.close()
        except Exception: pass
    assert found == b'{"notes":"synthetic backup"}'


def test_files_outside_patient_folders_migrate_and_are_read_from_the_store(conn, tmp_path):
    import json, jobs, importer
    pid, folder = _patient(conn, tmp_path)
    sorting = tmp_path / 'workspace' / 'TO SORT'; sorting.mkdir(parents=True, exist_ok=True)
    (sorting / 'intake_corrections.json').write_text(json.dumps({'a.pdf': {'suburb': 'Sampleton'}}), encoding='utf-8')
    (tmp_path / 'userdata' / 'history-import-plan.json').write_text('[]', encoding='utf-8')
    spec = jobs.interview_spec_path(dict(conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()))
    spec.parent.mkdir(parents=True, exist_ok=True); spec.write_text('{"notes":"synthetic"}', encoding='utf-8')
    folder_for = lambda row: jobs.patient_folder(row)
    first = records.migrate_all(conn, folder_for, jobs.outside_files)
    assert first['imported'] == 3 and first['conflict'] == 0
    assert records.get_json(conn, records.GLOBAL_PATIENT, 'intake_corrections.json') == {'a.pdf': {'suburb': 'Sampleton'}}
    assert records.get_json(conn, pid, 'interview_spec.json') == {'notes': 'synthetic'}
    # a repeat is safe and a newer stored record is never overwritten by the stale plain file
    records.put_json(conn, records.GLOBAL_PATIENT, 'intake_corrections.json', {'a.pdf': {'suburb': 'Newer'}}); conn.commit()
    again = records.migrate_all(conn, folder_for, jobs.outside_files)
    assert again['imported'] == 0 and again['conflict'] == 1 and again['already'] == 2
    assert records.get_json(conn, records.GLOBAL_PATIENT, 'intake_corrections.json')['a.pdf']['suburb'] == 'Newer'
    assert 'Sampleton' in (sorting / 'intake_corrections.json').read_text(encoding='utf-8')  # plain file untouched
    st = records.status(conn, folder_for, jobs.outside_files)
    assert st['saved_records_protected'] is False and st['plain_files_differing_or_not_stored'] == 1


def test_global_names_only_for_the_shared_slot_and_never_import_from_patient_folders(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    with pytest.raises(ValueError):
        records.put(conn, pid, 'history-import-plan.json', b'[]')
    (folder / 'intake_corrections.json').write_text('{}', encoding='utf-8')
    assert 'intake_corrections.json' not in records.import_folder(conn, pid, folder)
    records.put(conn, records.GLOBAL_PATIENT, 'history-import-plan.json', b'[]')
    with pytest.raises(ValueError):
        records.put(conn, records.GLOBAL_PATIENT, 'other.json', b'[]')


def test_corrections_write_to_the_store_not_the_plain_file(conn, tmp_path):
    import json, jobs
    sorting = tmp_path / 'workspace' / 'TO SORT'; sorting.mkdir(parents=True, exist_ok=True)
    plain = sorting / 'intake_corrections.json'; plain.write_text(json.dumps({'a.pdf': {'suburb': 'Old'}}), encoding='utf-8')
    conn.close()
    jobs.correction('a.pdf', {'suburb': 'New'})
    assert json.loads(plain.read_text(encoding='utf-8')) == {'a.pdf': {'suburb': 'Old'}}
    with contextlib.closing(db.connect()) as c2:
        assert records.get_json(c2, records.GLOBAL_PATIENT, 'intake_corrections.json') == {'a.pdf': {'suburb': 'New'}}


def test_shared_export_api_includes_shared_records_only(conn, tmp_path):
    import api
    pid, _ = _patient(conn, tmp_path)
    records.put_json(conn, records.GLOBAL_PATIENT, 'intake_corrections.json', {'synthetic': True})
    records.put_json(conn, pid, 'interview.json', {'private': 'synthetic'})
    conn.commit()
    out = tmp_path / 'shared-export'
    status, body = api.handle(conn, 'POST', '/api/records/export', {}, {'patient_id': 0, 'destination': str(out)})
    assert status == 200 and body['files'] == {'intake_corrections.json': 'written'}
    assert not (out / 'interview.json').exists()
    assert (out / records.EXPORT_NOTE).exists()


def test_retire_only_committed_matching_records_and_restart_export(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{"synthetic":true}')
    (folder / 'report_spec.json').write_bytes(b'{"older":true}')
    (folder / 'source.pdf').write_bytes(b'%PDF synthetic')
    records.import_folder(conn, pid, folder)
    records.put(conn, pid, 'report_spec.json', b'{"newer":true}'); conn.commit()
    result = records.retire_matching(conn, jobs.patient_folder)
    assert result == {'removed': 1, 'different_or_missing': 1, 'skipped': 0, 'errors': 0}
    assert not (folder / 'interview.json').exists()
    assert (folder / 'report_spec.json').read_bytes() == b'{"older":true}'
    assert (folder / 'source.pdf').exists()
    dbfile = conn.execute('PRAGMA database_list').fetchone()[2]
    with contextlib.closing(db.open_encrypted(dbfile, key=conn.hmr_key)) as reopened:
        assert records.get(reopened, pid, 'interview.json') == b'{"synthetic":true}'
        records.export_folder(reopened, pid, tmp_path / 'after-removal-export')
    assert (tmp_path / 'after-removal-export' / 'interview.json').read_bytes() == b'{"synthetic":true}'


def test_retire_shared_copies_and_interview_spec(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    correction = tmp_path / 'workspace' / 'TO SORT' / 'intake_corrections.json'
    correction.parent.mkdir(); correction.write_bytes(b'{}')
    spec = jobs.interview_spec_path(conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())
    spec.parent.mkdir(parents=True, exist_ok=True); spec.write_bytes(b'{"meds":[]}')
    records.migrate_all(conn, jobs.patient_folder, jobs.outside_files)
    result = records.retire_matching(conn, jobs.patient_folder, jobs.outside_files)
    assert result['removed'] == 2
    assert not correction.exists() and not spec.exists()
    assert records.get(conn, 0, 'intake_corrections.json') == b'{}'
    assert records.get(conn, pid, 'interview_spec.json') == b'{"meds":[]}'
    assert records.retire_matching(conn, jobs.patient_folder, jobs.outside_files)['removed'] == 0
    assert records.status(conn, jobs.patient_folder, jobs.outside_files)['saved_records_protected'] is False


def test_retire_refuses_unsaved_transaction(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{}')
    records.put(conn, pid, 'interview.json', b'{}')
    with pytest.raises(ValueError, match='Save changes'):
        records.retire_matching(conn, jobs.patient_folder)
    assert (folder / 'interview.json').exists()


def test_retire_refuses_unencrypted_database(tmp_path):
    with contextlib.closing(db.plain_connect(tmp_path / 'plain.db')) as plain:
        records.ensure(plain); plain.commit()
        with pytest.raises(ValueError, match='persisted encrypted'):
            records.retire_matching(plain, lambda _: None)


def test_retire_verification_failure_never_deletes(conn, tmp_path, monkeypatch):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{}')
    records.import_folder(conn, pid, folder)
    def fail(*args, **kwargs): raise ValueError('synthetic reopen failure')
    monkeypatch.setattr(db, 'open_encrypted', fail)
    with pytest.raises(ValueError, match='reopen failure'):
        records.retire_matching(conn, jobs.patient_folder)
    assert (folder / 'interview.json').exists() and not conn.in_transaction


def test_retire_skips_symlink_and_concurrent_file_change(conn, tmp_path, monkeypatch):
    from pathlib import Path
    import jobs
    pid, folder = _patient(conn, tmp_path)
    target = folder / 'interview.json'; target.write_bytes(b'{}')
    other = tmp_path / 'outside.json'; other.write_bytes(b'{}')
    try: (folder / 'report_spec.json').symlink_to(other)
    except OSError: pytest.skip('symlinks unavailable')
    records.import_folder(conn, pid, folder)
    original = Path.read_bytes
    calls = []
    def changing(path):
        body = original(path)
        if path == target:
            calls.append(1)
            if len(calls) == 1: path.write_bytes(b'{"changed":true}')
        return body
    monkeypatch.setattr(Path, 'read_bytes', changing)
    result = records.retire_matching(conn, jobs.patient_folder)
    assert result['removed'] == 0 and result['skipped'] == 2
    assert target.exists() and other.exists()


def test_retire_api_requires_confirmation(conn, tmp_path):
    import api, jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{}'); records.import_folder(conn, pid, folder)
    status, _ = api.handle(conn, 'POST', '/api/records/retire', {}, {})
    assert status == 400 and (folder / 'interview.json').exists()
    status, result = api.handle(conn, 'POST', '/api/records/retire', {}, {'confirmed': True})
    assert status == 200 and result['removed'] == 1 and not (folder / 'interview.json').exists()


def test_retire_refuses_active_task(conn, tmp_path):
    import jobs
    pid, folder = _patient(conn, tmp_path)
    (folder / 'interview.json').write_bytes(b'{}'); records.import_folder(conn, pid, folder)
    conn.execute("INSERT INTO tasks(id,step,patient_id,state,created) VALUES(?,?,?,?,?)", ('synthetic-task', 'report_build', pid, 'running', '2026-01-01'))
    conn.commit()
    with pytest.raises(ValueError, match='active tasks'):
        records.retire_matching(conn, jobs.patient_folder)
    assert (folder / 'interview.json').exists()
