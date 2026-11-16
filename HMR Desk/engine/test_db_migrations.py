"""Versioned, non-destructive SQLite migration regressions (synthetic data only)."""
import sqlite3

import pytest

import db


def test_new_db_has_versioned_schema_and_idempotent_reconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    target = tmp_path / 'userdata' / 'hmr.db'
    with db.connect(str(target)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        conn.execute("INSERT INTO patients(key,name) VALUES ('synthetic','Synthetic Person')")
    with db.connect(str(target)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT name FROM patients WHERE key='synthetic'").fetchone()[0] == 'Synthetic Person'


def test_legacy_schema_upgrade_preserves_rows_and_does_not_reapply(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    target = tmp_path / 'userdata' / 'historical.db'
    target.parent.mkdir()
    with sqlite3.connect(target) as legacy:
        legacy.executescript(db.SCHEMA)
        legacy.execute("INSERT INTO patients(key,name) VALUES ('prior','Prior Synthetic')")
        legacy.execute("INSERT INTO messages(id,direction,body,state,created_at) VALUES ('old','in','test','received','2026-01-01')")
        assert legacy.execute('PRAGMA user_version').fetchone()[0] == 0
    with db.connect(str(target)) as upgraded:
        assert upgraded.execute('PRAGMA user_version').fetchone()[0] == 1
        assert upgraded.execute("SELECT name FROM patients WHERE key='prior'").fetchone()[0] == 'Prior Synthetic'
        assert upgraded.execute("SELECT body FROM messages WHERE id='old'").fetchone()[0] == 'test'
        assert 'ai_intent' in {r[1] for r in upgraded.execute('PRAGMA table_info(messages)')}
        assert 'format' in {r[1] for r in upgraded.execute('PRAGMA table_info(tasks)')}
    with db.connect(str(target)) as again:
        assert again.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1


def test_newer_database_refused_without_modification(tmp_path):
    target = tmp_path / 'future.db'
    with sqlite3.connect(target) as future:
        future.execute('PRAGMA user_version = 999')
        future.execute('CREATE TABLE sentinel (payload TEXT)')
        future.execute("INSERT INTO sentinel VALUES ('untouched')")
    with pytest.raises(RuntimeError, match='newer'):
        db.connect(str(target))
    with sqlite3.connect(target) as check:
        assert check.execute('PRAGMA user_version').fetchone()[0] == 999
        assert check.execute('SELECT payload FROM sentinel').fetchone()[0] == 'untouched'


def test_additive_migration_rolls_back_on_column_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    target = tmp_path / 'legacy.db'
    with sqlite3.connect(target) as legacy:
        legacy.executescript(db.SCHEMA)
    original = db._ADDITIVE_COLUMNS
    monkeypatch.setattr(db, '_ADDITIVE_COLUMNS', original + (('patients', 'not_a_column', 'INVALID SQL ('),))
    with pytest.raises(sqlite3.OperationalError):
        db.connect(str(target))
    with sqlite3.connect(target) as check:
        assert check.execute('PRAGMA user_version').fetchone()[0] == 0
        assert 'is_test' not in {r[1] for r in check.execute('PRAGMA table_info(patients)')}
