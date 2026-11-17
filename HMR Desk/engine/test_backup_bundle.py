"""Synthetic AES-GCM full workspace backup integrity and recovery regression."""
import json
import sqlite3
from pathlib import Path

import pytest

import backup_bundle
import db


def test_encrypted_snapshot_round_trip_and_no_overwrite(tmp_path, monkeypatch):
    workspace = tmp_path / 'active workspace'
    patient = workspace / 'TO SORT' / 'Referral-synthetic'
    patient.mkdir(parents=True)
    (patient / 'referral.pdf').write_bytes(b'%PDF- synthetic no patient identifiers')
    (patient / 'interview.json').write_text(json.dumps({'notes': 'synthetic only'}))
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'active data'))
    conn = db.connect(str(tmp_path / 'active data' / 'hmr.db'))
    with conn:
        conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                     ('synthetic test', 'Synthetic Test', 'TO SORT/Referral-synthetic'))
    secret = 'a-long-local-passphrase-for-backup'
    output = tmp_path / 'encrypted.hmrbak'
    backup_bundle.create(conn, workspace, output, secret)
    assert output.read_bytes().startswith(backup_bundle.MAGIC)
    assert b'synthetic only' not in output.read_bytes()
    assert b'Synthetic Test' not in output.read_bytes()
    location = tmp_path / 'recovered'
    with pytest.raises(ValueError):
        backup_bundle.restore(output, location, 'a-long-wrong-passphrase')
    assert not location.exists()
    backup_bundle.restore(output, location, secret)
    assert (location / 'workspace' / 'TO SORT' / 'Referral-synthetic' / 'referral.pdf').read_bytes().startswith(b'%PDF-')
    with sqlite3.connect(location / 'data' / 'hmr.db') as check:
        assert check.execute('SELECT name FROM patients').fetchone()[0] == 'Synthetic Test'
    with pytest.raises(FileExistsError):
        backup_bundle.restore(output, location, secret)
    damaged = tmp_path / 'tampered.hmrbak'
    content = bytearray(output.read_bytes())
    content[-22] ^= 5
    damaged.write_bytes(content)
    with pytest.raises(ValueError):
        backup_bundle.restore(damaged, tmp_path / 'damaged-restore', secret)
    assert not (tmp_path / 'damaged-restore').exists()
    conn.close()


def test_backup_fails_inside_active_data(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with pytest.raises(ValueError, match='outside'):
        backup_bundle.create(conn, workspace, workspace / 'unsafe.hmrbak', 'twelve chars')
    conn.close()


def test_backup_rejects_concurrent_workspace_modification(tmp_path, monkeypatch):
    workspace = tmp_path / 'active'
    workspace.mkdir()
    item = workspace / 'interview.json'
    item.write_text('{"version":1}')
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(data))
    conn = db.connect(str(data / 'hmr.db'))
    original_fsync = backup_bundle.os.fsync

    def simulated_concurrent_save(fd):
        item.write_text('{"version":2,"modified":true}')
        return original_fsync(fd)

    monkeypatch.setattr(backup_bundle.os, 'fsync', simulated_concurrent_save)
    output = tmp_path / 'should-not-exist.hmrbak'
    with pytest.raises(ValueError, match='changed during backup'):
        backup_bundle.create(conn, workspace, output, 'a-long-backup-password')
    assert not output.exists()
    conn.close()


def test_plaintext_staging_uses_private_data_root(tmp_path, monkeypatch):
    """Never put decrypted patient case files in a system-wide temporary directory."""
    import os
    from pathlib import Path

    data = tmp_path / 'user-private'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'synthetic-interview.json').write_text('{"synthetic":true}')
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(data))
    real_temporary = backup_bundle.tempfile.TemporaryDirectory
    stage_locations = []

    def record_directory(*args, **kwargs):
        stage_locations.append(Path(kwargs.get('dir')).resolve())
        return real_temporary(*args, **kwargs)

    monkeypatch.setattr(backup_bundle.tempfile, 'TemporaryDirectory', record_directory)
    conn = db.connect(str(data / 'hmr.db'))
    output = tmp_path / 'backup.hmrbak'
    backup_bundle.create(conn, workspace, output, 'synthetic-passphrase-123')
    target = tmp_path / 'isolated-restore'
    backup_bundle.restore(output, target, 'synthetic-passphrase-123')
    assert len(stage_locations) == 2
    private = data / '.protected-backup-staging'
    assert all(stage == private for stage in stage_locations)
    assert (target / 'workspace' / 'synthetic-interview.json').exists()
    assert not any(private.iterdir()), 'Temporary directories must be removed'
    if os.name != 'nt':
        assert private.stat().st_mode & 0o777 == 0o700
    conn.close()


def test_read_only_backup_preview_verifies_patient_scope_and_never_restores(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'synthetic.json').write_text('{"test":true}')
    data = tmp_path / 'data'
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(data))
    conn = db.connect(str(data / 'hmr.db'))
    with conn:
        conn.execute("INSERT INTO patients(key,name) VALUES ('synthetic','Synthetic Example')")
    backup = tmp_path / 'test.hmrbak'
    backup_bundle.create(conn, workspace, backup, 'synthetic-strong-passphrase')
    before = sorted(tmp_path.iterdir())
    preview = backup_bundle.restore(backup, None, 'synthetic-strong-passphrase', preview_only=True)
    assert preview['verified'] is True
    assert preview['patients'] == 1
    assert preview['workspace_files'] == 1
    assert preview['will_activate'] is False
    assert sorted(tmp_path.iterdir()) == before
    with pytest.raises(ValueError, match='Wrong passphrase'):
        backup_bundle.restore(backup, None, 'not-the-right-passphrase', preview_only=True)
    conn.close()


def test_isolated_restore_integrity_check_before_activation(tmp_path, monkeypatch):
    workspace = tmp_path / 'active workspace'
    workspace.mkdir()
    (workspace / 'synthetic.json').write_text('{"clinical":"synthetic"}')
    userdata = tmp_path / 'userdata'
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(userdata))
    conn = db.connect(str(userdata / 'hmr.db'))
    with conn:
        conn.execute("INSERT INTO patients(key,name) VALUES ('synthetic case','Synthetic Case')")
    backup = tmp_path / 'isolated.hmrbak'
    backup_bundle.create(conn, workspace, backup, 'long-synthetic-passphrase')
    isolated = tmp_path / 'restored'
    backup_bundle.restore(backup, isolated, 'long-synthetic-passphrase')
    checked = backup_bundle.verify_isolated(isolated)
    assert checked['verified']
    assert checked['patients'] == 1
    assert checked['files'] == 2
    assert (isolated / 'restore-manifest.json').is_file()
    (isolated / 'workspace' / 'synthetic.json').write_text('tampered')
    with pytest.raises(ValueError, match='length mismatch|hash mismatch'):
        backup_bundle.verify_isolated(isolated)
    with pytest.raises(ValueError, match='active clinical storage'):
        backup_bundle.verify_isolated(workspace)
    conn.close()


def test_empty_workspace_backup_restores_a_workspace_folder(tmp_path, monkeypatch):
    workspace = tmp_path / 'active workspace'
    workspace.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'active data'))
    conn = db.connect(str(tmp_path / 'active data' / 'hmr.db'))
    output = tmp_path / 'backups' / 'empty.hmrbak'
    backup_bundle.create(conn, workspace, output, 'a-long-local-passphrase-for-backup')
    conn.close()
    location = tmp_path / 'recovered'
    backup_bundle.restore(output, location, 'a-long-local-passphrase-for-backup')
    assert (location / 'workspace').is_dir()
    assert backup_bundle.verify_isolated(location)['verified'] is True


def test_backup_round_trip_preserves_structured_patient_records(tmp_path, monkeypatch):
    import pathology_records, records
    workspace = tmp_path / 'active workspace'
    folder = workspace / 'TO SORT' / 'Referral-synthetic'
    folder.mkdir(parents=True)
    (folder / 'referral.pdf').write_bytes(b'%PDF- synthetic no patient identifiers')
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'active data'))
    conn = db.connect(str(tmp_path / 'active data' / 'hmr.db'))
    with conn:
        cursor = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                              ('synthetic test', 'Synthetic Test', 'TO SORT/Referral-synthetic'))
    patient = {'id': cursor.lastrowid, 'key': 'synthetic test', 'name': 'Synthetic Test',
               'folder': 'TO SORT/Referral-synthetic'}
    row = dict(id='c' * 32, test='eGFR', value='41', unit='mL/min/1.73m2',
               reference_interval='60-120', sample_date='2026-11-01',
               source='synthetic-lab.pdf page 2', verified=True, comment='Synthetic comment')
    pathology_records.save(conn, patient, {'revision': pathology_records.revision(conn, patient),
                                           'records': [row]}, reviewer='Synthetic Reviewer')
    records.put_json(conn, patient['id'], 'confirmed_meds.json',
                     {'medicine_snapshot_sha256': 'a' * 64, 'confirmed': ['Synthetic 5mg']})
    secret = 'a-long-local-passphrase-for-backup'
    output = tmp_path / 'encrypted.hmrbak'
    backup_bundle.create(conn, workspace, output, secret)
    location = tmp_path / 'recovered'
    backup_bundle.restore(output, location, secret)
    restored = db.connect(str(location / 'data' / 'hmr.db'))
    loaded = pathology_records.load(restored, patient)
    assert loaded['records'] == [row]
    assert loaded['verification']['c' * 32]['verified_by'] == 'Synthetic Reviewer'
    assert records.get_json(restored, patient['id'], 'confirmed_meds.json')['confirmed'] == ['Synthetic 5mg']
    restored.close()
    conn.close()
