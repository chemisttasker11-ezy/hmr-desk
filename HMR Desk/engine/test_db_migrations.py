"""Versioned, non-destructive SQLite migration regressions (synthetic data only)."""
import contextlib
import sqlite3

import pytest

import db

@contextlib.contextmanager
def plain(path):
    """A plain SQLite connection that is committed and really closed (Windows keeps files open otherwise)."""
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()



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
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    target = tmp_path / 'userdata' / 'historical.db'
    target.parent.mkdir()
    with plain(target) as legacy:
        legacy.executescript(db.SCHEMA)
        legacy.execute("INSERT INTO patients(key,name) VALUES ('prior','Prior Synthetic')")
        legacy.execute("INSERT INTO messages(id,direction,body,state,created_at) VALUES ('old','in','test','received','2026-01-01')")
        assert legacy.execute('PRAGMA user_version').fetchone()[0] == 0
    with contextlib.closing(db.connect(str(target))) as upgraded:
        assert upgraded.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        snapshots = list((tmp_path / 'userdata' / '.migration-snapshots').glob('before-schema-*.db'))
        assert len(snapshots) == 1
        with db.open_encrypted(snapshots[0]) as previous:
            assert previous.execute('PRAGMA user_version').fetchone()[0] == 0
            assert previous.execute("SELECT name FROM patients WHERE key='prior'").fetchone()[0] == 'Prior Synthetic'
        assert upgraded.execute("SELECT name FROM patients WHERE key='prior'").fetchone()[0] == 'Prior Synthetic'
        assert upgraded.execute("SELECT body FROM messages WHERE id='old'").fetchone()[0] == 'test'
        assert 'ai_intent' in {r[1] for r in upgraded.execute('PRAGMA table_info(messages)')}
        assert 'format' in {r[1] for r in upgraded.execute('PRAGMA table_info(tasks)')}
        assert {'gp_provider', 'clinic_address', 'clinic_phone'} <= {r[1] for r in upgraded.execute('PRAGMA table_info(patients)')}
    with db.connect(str(target)) as again:
        assert again.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1
    assert len(list((tmp_path / 'userdata' / '.migration-snapshots').glob('before-schema-*.db'))) == 1


def test_newer_database_refused_without_modification(tmp_path):
    target = tmp_path / 'future.db'
    with plain(target) as future:
        future.execute('PRAGMA user_version = 999')
        future.execute('CREATE TABLE sentinel (payload TEXT)')
        future.execute("INSERT INTO sentinel VALUES ('untouched')")
    with pytest.raises(RuntimeError, match='newer'):
        db.connect(str(target))
    with db.open_encrypted(target) as check:
        assert check.execute('PRAGMA user_version').fetchone()[0] == 999
        assert check.execute('SELECT payload FROM sentinel').fetchone()[0] == 'untouched'


def test_additive_migration_rolls_back_on_column_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    target = tmp_path / 'legacy.db'
    with plain(target) as legacy:
        legacy.executescript(db.SCHEMA)
    original = db._ADDITIVE_COLUMNS
    monkeypatch.setattr(db, '_ADDITIVE_COLUMNS', original + (('patients', 'not_a_column', 'INVALID SQL ('),))
    with pytest.raises(db.sqlite3.OperationalError):
        db.connect(str(target))
    with db.open_encrypted(target) as check:
        assert check.execute('PRAGMA user_version').fetchone()[0] == 0
        assert 'is_test' not in {r[1] for r in check.execute('PRAGMA table_info(patients)')}


def test_encrypted_v1_patient_gp_migration_preserves_rollback_snapshot(tmp_path, monkeypatch):
    """Synthetic SQLCipher v1 -> v2: real encrypted file, schema columns, backup and rollback bytes."""
    import shutil
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    target = tmp_path / 'userdata' / 'hmr.db'
    target.parent.mkdir()
    # Build a fully encrypted synthetic database, then represent the v1 patient schema.
    with contextlib.closing(db.connect(str(target))) as previous:
        previous.execute("INSERT INTO patients(key,name,gp) VALUES ('v1-synthetic','Version One Synthetic','Dr Example')")
        previous.execute("INSERT INTO messages(id,direction,body,state,created_at) VALUES ('v1msg','in','fictional message','received','2026-01-01')")
        for col in ('gp_provider', 'clinic_address', 'clinic_phone'):
            previous.execute('ALTER TABLE patients DROP COLUMN ' + col)
        previous.execute('PRAGMA user_version = 1')
        previous.commit()
        key = previous.hmr_key
    with contextlib.closing(db.open_encrypted(target, key=key, readonly=True)) as old:
        assert old.execute('PRAGMA user_version').fetchone()[0] == 1
        assert 'gp_provider' not in {r[1] for r in old.execute('PRAGMA table_info(patients)')}
        assert old.execute("SELECT name FROM patients WHERE key='v1-synthetic'").fetchone()[0] == 'Version One Synthetic'
    with db.connect(str(target)) as upgraded:
        assert upgraded.execute('PRAGMA user_version').fetchone()[0] == 2
        assert {'gp_provider', 'clinic_address', 'clinic_phone'} <= {r[1] for r in upgraded.execute('PRAGMA table_info(patients)')}
        assert upgraded.execute("SELECT gp FROM patients WHERE key='v1-synthetic'").fetchone()[0] == 'Dr Example'
        assert upgraded.execute("SELECT body FROM messages WHERE id='v1msg'").fetchone()[0] == 'fictional message'
        assert upgraded.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    snapshots = list((tmp_path / 'userdata' / '.migration-snapshots').glob('before-schema-*.db'))
    assert len(snapshots) == 1
    # The immutable snapshot must still open as the v1 schema with its original records.
    rollback_copy = tmp_path / 'rollback-synthetic.db'
    shutil.copy2(snapshots[0], rollback_copy)
    with contextlib.closing(db.open_encrypted(rollback_copy, key=key)) as restored:
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert restored.execute('PRAGMA user_version').fetchone()[0] == 1
        assert 'gp_provider' not in {r[1] for r in restored.execute('PRAGMA table_info(patients)')}
        assert restored.execute("SELECT gp FROM patients WHERE key='v1-synthetic'").fetchone()[0] == 'Dr Example'
        assert restored.execute("SELECT body FROM messages WHERE id='v1msg'").fetchone()[0] == 'fictional message'
