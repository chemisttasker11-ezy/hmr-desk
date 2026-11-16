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
