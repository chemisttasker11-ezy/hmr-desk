"""Encrypted database (SQLCipher) regressions. Synthetic data only."""
import os
import contextlib
import sqlite3

import pytest

import backup_bundle
import db
import dbkey

@contextlib.contextmanager
def plain(path):
    """A plain SQLite connection that is committed and really closed (Windows keeps files open otherwise)."""
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()



@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    monkeypatch.delenv('HMR_DB_KEY', raising=False)


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    (tmp_path / 'userdata').mkdir(exist_ok=True)
    return tmp_path / 'userdata' / 'hmr.db'


def _is_plain(path):
    return open(path, 'rb').read(16) == b'SQLite format 3\x00'


def test_new_database_is_encrypted_with_key_file(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with db.connect(str(target)) as conn:
        conn.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
        conn.commit()
    assert not _is_plain(target)
    assert b'Synthetic Person' not in target.read_bytes()
    assert (tmp_path / 'userdata' / dbkey.KEY_FILE).exists()
    with pytest.raises(sqlite3.DatabaseError):
        with plain(target) as raw:
            raw.execute('SELECT count(*) FROM sqlite_master').fetchone()


def test_plain_database_is_migrated_and_plaintext_removed(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with plain(target) as legacy:
        legacy.executescript(db.SCHEMA)
        legacy.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
        legacy.execute('PRAGMA user_version = 0')
    # an old rolling backup is plain too
    old = tmp_path / 'userdata' / 'hmr-backup-Mon.db'
    with plain(old) as other:
        other.execute('CREATE TABLE t(x)')
        other.execute("INSERT INTO t VALUES ('Synthetic Backup')")
    with db.connect(str(target)) as conn:
        assert conn.execute("SELECT name FROM patients WHERE key='s'").fetchone()[0] == 'Synthetic Person'
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
    assert not _is_plain(target) and not _is_plain(old)
    assert b'Synthetic Person' not in target.read_bytes()
    assert sorted(p.name for p in (tmp_path / 'userdata').iterdir() if '.plain-old' in p.name) == []
    assert not (tmp_path / 'userdata' / 'hmr.db.encrypting').exists()


def test_failed_migration_leaves_original_untouched(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with plain(target) as legacy:
        legacy.execute('CREATE TABLE t(x)')
        legacy.execute("INSERT INTO t VALUES ('keep')")
    key = os.urandom(32)

    def boom(*a, **k):
        raise ValueError('boom')
    monkeypatch.setattr(db, 'open_encrypted', boom)
    with pytest.raises(ValueError):
        db.encrypt_plain_file(str(target), key)
    assert _is_plain(target)
    with plain(target) as check:
        assert check.execute('SELECT x FROM t').fetchone()[0] == 'keep'
    assert not (tmp_path / 'userdata' / 'hmr.db.encrypting').exists()


def test_second_replace_failure_restores_the_original_database(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with plain(target) as legacy:
        legacy.execute('CREATE TABLE t(x)')
        legacy.execute("INSERT INTO t VALUES ('keep')")
    key = os.urandom(32)
    real = db._replace_retry
    calls = []

    def second_fails(source, dest, *a, **k):
        calls.append((source, dest))
        if len(calls) == 2:
            raise PermissionError('locked by another program')
        return real(source, dest, *a, **k)
    monkeypatch.setattr(db, '_replace_retry', second_fails)
    with pytest.raises(PermissionError):
        db.encrypt_plain_file(str(target), key)
    assert _is_plain(target)
    with plain(target) as check:
        assert check.execute('SELECT x FROM t').fetchone()[0] == 'keep'
    assert not (tmp_path / 'userdata' / 'hmr.db.plain-old').exists()


def test_restore_failure_keeps_both_files_and_says_so(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with plain(target) as legacy:
        legacy.execute('CREATE TABLE t(x)')
        legacy.execute("INSERT INTO t VALUES ('keep')")
    key = os.urandom(32)
    real = db._replace_retry
    calls = []

    def fails_after_first(source, dest, *a, **k):
        calls.append(1)
        if len(calls) >= 2:
            raise PermissionError('locked')
        return real(source, dest, *a, **k)
    monkeypatch.setattr(db, '_replace_retry', fails_after_first)
    with pytest.raises(RuntimeError, match='plain-old'):
        db.encrypt_plain_file(str(target), key)
    folder = tmp_path / 'userdata'
    assert (folder / 'hmr.db.plain-old').exists()
    assert (folder / 'hmr.db.encrypting').exists()


def test_no_fresh_database_while_an_unfinished_migration_copy_exists(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    (tmp_path / 'userdata').mkdir(exist_ok=True)
    (tmp_path / 'userdata' / 'hmr.db.plain-old').write_bytes(b'records')
    with pytest.raises(RuntimeError, match='new empty database was not created'):
        db.ensure_encrypted(str(target))
    assert not target.exists()


def test_missing_key_is_refused_and_no_new_key_made(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    db.connect(str(target)).close()
    (tmp_path / 'userdata' / dbkey.KEY_FILE).unlink()
    with pytest.raises(dbkey.KeyUnavailable):
        db.connect(str(target))
    assert not (tmp_path / 'userdata' / dbkey.KEY_FILE).exists()
    assert dbkey.status(str(target))['locked'] is True


def test_wrong_key_refused(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    db.connect(str(target)).close()
    with pytest.raises(dbkey.KeyUnavailable):
        db.open_encrypted(str(target), key=os.urandom(32)).close()


def test_recovery_text_round_trip_and_checksum():
    key = os.urandom(32)
    text = dbkey.recovery_text(key)
    assert dbkey.parse_recovery(text) == key
    assert dbkey.parse_recovery(text.lower().replace('-', ' ')) == key
    bad = 'A' + text[1:] if text[0] != 'A' else 'B' + text[1:]
    with pytest.raises(dbkey.RecoveryKeyError):
        dbkey.parse_recovery(bad)
    with pytest.raises(dbkey.RecoveryKeyError):
        dbkey.parse_recovery('not a key')


def test_recovery_key_shown_until_confirmed_then_refused(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    db.connect(str(target)).close()
    assert dbkey.status(str(target))['recovery_pending'] is True
    text = dbkey.reveal_recovery_key(str(target))
    assert dbkey.reveal_recovery_key(str(target)) == text
    dbkey.acknowledge_recovery_key(str(target))
    assert dbkey.status(str(target))['recovery_pending'] is False
    with pytest.raises(dbkey.RecoveryKeyError):
        dbkey.reveal_recovery_key(str(target))


def test_restore_on_new_pc_with_recovery_key(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    conn = db.connect(str(target))
    conn.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
    conn.commit()
    text = dbkey.reveal_recovery_key(str(target))
    conn.close()
    # copy the encrypted file to "another PC" without its key file
    other = tmp_path / 'pc2'
    other.mkdir()
    (other / 'hmr.db').write_bytes(target.read_bytes())
    with pytest.raises(dbkey.KeyUnavailable):
        db.connect(str(other / 'hmr.db'))
    db.recover_key(text, str(other / 'hmr.db'))
    with db.connect(str(other / 'hmr.db')) as again:
        assert again.execute("SELECT name FROM patients").fetchone()[0] == 'Synthetic Person'
    with pytest.raises(dbkey.RecoveryKeyError):
        db.recover_key(dbkey.recovery_text(os.urandom(32)), str(other / 'hmr.db'))


def test_rotate_key_reencrypts_and_old_key_stops_working(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    conn = db.connect(str(target))
    conn.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
    conn.commit()
    old = conn.hmr_key
    text = db.rotate_key(conn)
    conn.close()
    assert not (tmp_path / 'userdata' / dbkey.PENDING_FILE).exists()
    assert dbkey.parse_recovery(text) != old
    with pytest.raises(dbkey.KeyUnavailable):
        db.open_encrypted(str(target), key=old).close()
    with db.connect(str(target)) as again:
        assert again.execute('SELECT name FROM patients').fetchone()[0] == 'Synthetic Person'
    assert dbkey.status(str(target))['recovery_pending'] is True


def test_interrupted_rotation_is_settled_on_next_connect(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    conn = db.connect(str(target))
    conn.commit()
    # crash after the new key was written but before the database was re-keyed
    dbkey.begin_rotation(str(target))
    conn.close()
    with db.connect(str(target)) as again:
        assert again.execute('SELECT count(*) FROM patients').fetchone()[0] == 0
    assert not (tmp_path / 'userdata' / dbkey.PENDING_FILE).exists()
    # crash after rekey but before the key file swap
    conn = db.connect(str(target))
    new = dbkey.begin_rotation(str(target))
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.execute('PRAGMA rekey = "x\'%s\'"' % new.hex())
    conn.close()
    with db.connect(str(target)) as again:
        assert again.hmr_key == new
    assert not (tmp_path / 'userdata' / dbkey.PENDING_FILE).exists()
    assert dbkey.candidates(str(target)) == [new]


def test_env_key_override(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    key = os.urandom(32)
    monkeypatch.setenv('HMR_DB_KEY', key.hex())
    with db.connect(str(target)) as conn:
        assert conn.hmr_key == key
    assert not (tmp_path / 'userdata' / dbkey.KEY_FILE).exists()


def test_rolling_backup_is_encrypted(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    conn = db.connect(str(target))
    conn.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
    conn.commit()
    db.backup(conn)
    conn.close()
    copies = list((tmp_path / 'userdata').glob('hmr-backup-*.db'))
    assert copies
    for copy in copies:
        assert not _is_plain(copy) and b'Synthetic Person' not in copy.read_bytes()
        with db.open_encrypted(str(copy)) as check:
            assert check.execute('SELECT name FROM patients').fetchone()[0] == 'Synthetic Person'


def test_bundle_snapshot_is_plain_inside_and_restores_to_encrypted(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'note.txt').write_text('synthetic')
    conn = db.connect(str(target))
    conn.execute("INSERT INTO patients(key,name) VALUES ('s','Synthetic Person')")
    conn.commit()
    out = tmp_path / 'backups' / 'b.hmrbak'
    backup_bundle.create(conn, workspace, out, 'a-long-local-passphrase-for-backup')
    conn.close()
    assert b'Synthetic Person' not in out.read_bytes()
    restored = tmp_path / 'restored'
    backup_bundle.restore(out, restored, 'a-long-local-passphrase-for-backup')
    snapshot = restored / 'data' / 'hmr.db'
    assert _is_plain(snapshot)  # the bundle format is unchanged: restore on a new PC needs only the passphrase
    # the engine encrypts it with this PC's own key on first connect
    with db.connect(str(snapshot)) as moved:
        assert moved.execute('SELECT name FROM patients').fetchone()[0] == 'Synthetic Person'
    assert not _is_plain(snapshot)


@pytest.mark.skipif(os.name != 'nt', reason='DPAPI is Windows only')
def test_key_file_is_dpapi_wrapped_on_windows(tmp_path, monkeypatch):
    target = _paths(tmp_path, monkeypatch)
    with db.connect(str(target)) as conn:
        key = conn.hmr_key
    raw = (tmp_path / 'userdata' / dbkey.KEY_FILE).read_bytes()
    assert b'"dpapi"' in raw
    import base64
    assert key.hex().encode() not in raw and base64.b64encode(key) not in raw
    assert dbkey.candidates(str(target)) == [key]
