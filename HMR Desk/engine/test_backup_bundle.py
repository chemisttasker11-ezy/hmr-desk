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
