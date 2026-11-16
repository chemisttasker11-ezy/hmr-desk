"""Backups carry the registered approved template and every app setting (synthetic)."""
import sqlite3
from pathlib import Path

import pytest

import backup_bundle
import db
import settings


def make_live(tmp_path, monkeypatch):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    (workspace / 'note.txt').write_text('synthetic')
    data = tmp_path / 'userdata'
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(data))
    conn = db.connect(str(data / 'hmr.db'))
    templates = data / 'templates'
    (templates / 'history').mkdir(parents=True)
    (templates / 'approved-hmr.docx').write_bytes(b'SYNTHETIC DOCX BYTES')
    (templates / 'approved-hmr.json').write_text('{"version":"synthetic-1"}')
    (templates / 'history' / ('a' * 64 + '.docx')).write_bytes(b'OLDER SYNTHETIC DOCX')
    (templates / '.approved-pending.docx').write_bytes(b'unfinished install')
    (data / 'app-config.json').write_text('{"base":"C:/machine/specific"}')
    settings.update(conn, {'pharmacist_name': 'Synthetic Pharmacist'})
    conn.commit()
    return workspace, data, conn


def test_template_history_and_settings_survive_backup_and_restore(tmp_path, monkeypatch):
    workspace, data, conn = make_live(tmp_path, monkeypatch)
    output = tmp_path / 'out.hmrbak'
    secret = 'a-long-local-passphrase-for-backup'
    backup_bundle.create(conn, workspace, output, secret)
    preview = backup_bundle.restore(output, None, secret, preview_only=True)
    assert preview['template_files'] == 3
    recovered = tmp_path / 'recovered'
    backup_bundle.restore(output, recovered, secret)
    restored = recovered / 'data' / 'templates'
    assert (restored / 'approved-hmr.docx').read_bytes() == b'SYNTHETIC DOCX BYTES'
    assert (restored / 'approved-hmr.json').read_text() == '{"version":"synthetic-1"}'
    assert (restored / 'history' / ('a' * 64 + '.docx')).read_bytes() == b'OLDER SYNTHETIC DOCX'
    assert not (restored / '.approved-pending.docx').exists()
    assert not (recovered / 'data' / 'app-config.json').exists()
    with sqlite3.connect(recovered / 'data' / 'hmr.db') as check:
        row = check.execute("SELECT value FROM meta WHERE key='pharmacist_name'").fetchone()
    assert row[0] == 'Synthetic Pharmacist'
    verified = backup_bundle.verify_isolated(recovered)
    assert verified['verified'] and verified['template_files'] == 3
    conn.close()


def test_tampered_template_in_recovery_fails_verification(tmp_path, monkeypatch):
    workspace, data, conn = make_live(tmp_path, monkeypatch)
    output = tmp_path / 'out.hmrbak'
    secret = 'a-long-local-passphrase-for-backup'
    backup_bundle.create(conn, workspace, output, secret)
    recovered = tmp_path / 'recovered'
    backup_bundle.restore(output, recovered, secret)
    (recovered / 'data' / 'templates' / 'approved-hmr.docx').write_bytes(b'SWAPPED LAYOUT')
    with pytest.raises(ValueError, match='length mismatch|hash mismatch'):
        backup_bundle.verify_isolated(recovered)
    conn.close()


def test_backup_without_templates_still_works(tmp_path, monkeypatch):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    output = tmp_path / 'plain.hmrbak'
    backup_bundle.create(conn, workspace, output, 'a-long-local-passphrase-for-backup')
    preview = backup_bundle.restore(output, None, 'a-long-local-passphrase-for-backup', preview_only=True)
    assert preview['template_files'] == 0
    conn.close()


def test_only_database_and_templates_allowed_under_data():
    ok = backup_bundle._safe_data_entry
    assert ok(('data', 'hmr.db')) and ok(('data', 'templates', 'approved-hmr.docx'))
    assert ok(('workspace', 'x'))
    assert not ok(('data', 'app-config.json'))
    assert not ok(('data', 'api_token'))
    assert not ok(('data', 'templates'))
