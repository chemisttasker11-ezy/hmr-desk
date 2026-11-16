"""HMR Desk database: the single source of truth for patient state.
Location: %USERPROFILE%\\HMR-Desk-data\\hmr.db (see DATA_DIR); override with env HMR_DB (tests).
Run `python db.py` for a self-check."""
import datetime, json, logging, os, re, time, unicodedata, tempfile
from contextlib import closing
from pathlib import Path
try:
    # SQLCipher build of the standard sqlite3 API: the patient database is encrypted at rest.
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError as _exc:  # no silent fallback to an unencrypted database
    raise ImportError('HMR Desk needs the sqlcipher3-wheels package for its encrypted database') from _exc
import app_paths
import dbkey

BASE = str(app_paths.workspace_root())


# Not under AppData: Claude Desktop is a packaged app, so programs it launches get a private redirected copy of
# AppData and a database there splits into two copies. Not under OneDrive either.
DATA_DIR = str(app_paths.data_root())


def db_path():
    return os.environ.get('HMR_DB') or os.path.join(DATA_DIR, 'hmr.db')


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,          -- patient_key(name): stable match across files
  name TEXT NOT NULL,
  phone TEXT, address TEXT, suburb TEXT, postcode TEXT,
  gp TEXT, clinic TEXT, referral_date TEXT,
  dob TEXT, sex TEXT, medicare TEXT, irn TEXT, ihi TEXT,
  state TEXT NOT NULL DEFAULT 'new',  -- state machine, see STATES
  status_text TEXT,                   -- wording shown on the dashboard (plan JSON "Status")
  visit_date TEXT, visit_time TEXT, visit_end TEXT, visit_group TEXT,  -- current slot (ISO date, HH:MM)
  offered_date TEXT,                  -- day an offer was for, kept after a decline/hold
  note TEXT, reply TEXT,
  contact_id TEXT,                    -- id in the SMS connector's contact store
  folder TEXT,                        -- path relative to BASE
  has_pathology INTEGER DEFAULT 0, has_sheet INTEGER DEFAULT 0,
  plan_order INTEGER,                 -- position in the plan JSON; NULL = not on the current plan (e.g. old declines)
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS day_plans (
  date TEXT PRIMARY KEY, start_time TEXT, start_place TEXT, end_place TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
  title TEXT NOT NULL, place TEXT, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  kind TEXT NOT NULL CHECK(kind IN ('hmr','followup1','followup2')),
  visit_date TEXT, report_sent TEXT, claimed TEXT, folder TEXT,
  source TEXT NOT NULL CHECK(source IN ('import','app')), note TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,                -- out: fixed client id sent to the gateway; in: gateway inbox id
  patient_id INTEGER REFERENCES patients(id),
  direction TEXT NOT NULL CHECK (direction IN ('out','in')),
  body TEXT NOT NULL,
  kind TEXT,                          -- out: invitation/offer/follow-up/confirmation/reply/test; in: YES/DECLINE/OTHER
  state TEXT NOT NULL,                -- out: queued/submitting/Pending/Sent/Delivered/Failed/unknown; in: received
  recipient TEXT,                     -- out only: number actually used
  offer_ref TEXT,                     -- in: the out message id this reply answers
  created_at TEXT NOT NULL, sent_at TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS events (   -- append-only audit trail: nothing is overwritten silently
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, patient_id INTEGER, type TEXT NOT NULL, detail TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, patient_id INTEGER REFERENCES patients(id), step TEXT NOT NULL,
  state TEXT NOT NULL, waiting_for TEXT, output TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL, started TEXT, finished TEXT, flow INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_active ON tasks(COALESCE(patient_id, -1), step)
  WHERE state IN ('queued','running','waiting');
"""

# state -> states it may move to. hold/declined/expired are reachable from any pre-visit state.
_PRE = ('new', 'pooled', 'offered', 'confirmed', 'pathology_ready', 'sheet_ready', 'hold')
STATES = {
    'new': ('pooled',), 'pooled': ('offered',), 'offered': ('confirmed', 'pooled'),
    'confirmed': ('pathology_ready', 'sheet_ready', 'visited', 'offered', 'pooled'),
    'pathology_ready': ('sheet_ready', 'visited', 'offered', 'pooled'),
    'sheet_ready': ('visited', 'offered', 'pooled'),
    'visited': ('report_drafted',), 'report_drafted': ('signed_off',), 'signed_off': ('sent',),
    'sent': ('claimed',), 'claimed': (),
    'hold': ('pooled', 'offered', 'confirmed'), 'declined': ('pooled',), 'expired': ('pooled',),
}


SCHEMA_VERSION = 1

# Migration 1 preserves historical table contents and upgrades only missing columns.
# Future migrations must be appended as new numbered steps; never edit an applied step.
_ADDITIVE_COLUMNS = (
    ('tasks', 'format', "TEXT NOT NULL DEFAULT 'docx'"),
    ('patients', 'is_test', 'INTEGER NOT NULL DEFAULT 0'),
    ('patients', 'call_list', 'INTEGER NOT NULL DEFAULT 0'),
    ('patients', 'archived_at', 'TEXT'),
    ('patients', 'hold_from', 'TEXT'),
    ('messages', 'visit_date', 'TEXT'),
    ('messages', 'visit_time', 'TEXT'),
    ('messages', 'ai_intent', 'TEXT'),
    ('messages', 'ai_summary', 'TEXT'),
    ('messages', 'ai_confidence', 'REAL'),
    ('messages', 'ai_reply', 'TEXT'),
    ('messages', 'ai_draft_id', 'TEXT'),
)


def migrate_schema(conn):
    """Idempotent, versioned SQLite migration with atomic additive changes.

    PRAGMA user_version is updated in the SAME transaction as ALTER TABLE.
    A future database is refused rather than silently downgraded. The baseline
    schema is created separately before this migration for older installations.
    """
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError('Database schema is newer than this version of HMR Desk; upgrade the application')
    if version == SCHEMA_VERSION:
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if version < 1:
            for table, column, definition in _ADDITIVE_COLUMNS:
                names = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
                if column not in names:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            conn.execute('PRAGMA user_version = 1')
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def preserve_legacy_sqlite(conn):
    """Create a verified rollback snapshot before changing a historical database.

    SQLite's backup API includes WAL state. The snapshot stays in the user's
    private application-data directory; it is not a portable encrypted backup.
    """
    root = os.path.join(DATA_DIR, '.migration-snapshots')
    os.makedirs(root, mode=0o700, exist_ok=True)
    fd, target = tempfile.mkstemp(prefix='before-schema-', suffix='.db', dir=root)
    os.close(fd)
    try:
        with closing(open_encrypted(target, key=conn.hmr_key)) as snapshot:
            conn.backup(snapshot)
            if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Migration rollback snapshot failed SQLite integrity')
        return target
    except Exception:
        if os.path.exists(target):
            os.unlink(target)
        raise


# ---------------------------------------------------------------------------
# Encrypted storage (SQLCipher). Key handling lives in dbkey.py.
# ---------------------------------------------------------------------------
class Connection(sqlite3.Connection):
    """sqlite3 connection that remembers the key it was opened with (for snapshots)."""
    hmr_key = None


def _sql_key(key):
    return "x'%s'" % key.hex()


def open_encrypted(path, key=None, readonly=False, timeout=30):
    """Open an encrypted database file. No schema work. Raises KeyUnavailable if no key opens it."""
    path = str(path)
    keys = [key] if key else dbkey.candidates(path)
    if not keys:
        raise dbkey.KeyUnavailable('No database key is available on this PC. Use your recovery key.')
    for candidate in keys:
        target = Path(path).resolve().as_uri() + '?mode=ro' if readonly else path
        conn = sqlite3.connect(target, timeout=timeout, uri=readonly, factory=Connection)
        try:
            conn.execute('PRAGMA key = "%s"' % _sql_key(candidate))
            conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
        except sqlite3.DatabaseError:
            conn.close()
            continue
        conn.hmr_key = candidate
        return conn
    raise dbkey.KeyUnavailable('The key on this PC does not open this database. Use your recovery key.')


def plain_connect(path):
    """Unencrypted SQLite file. Only for the inside of a passphrase-encrypted backup bundle."""
    return sqlite3.connect(str(path), factory=Connection)


def plain_snapshot(conn, target):
    """Copy an encrypted database into a plain SQLite file (backup bundles encrypt the whole archive)."""
    target = str(target)
    if os.path.exists(target):
        os.unlink(target)
    conn.commit()  # ATTACH cannot run inside an open transaction
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    conn.execute("ATTACH DATABASE ? AS plaintext KEY ''", (target,))
    try:
        conn.execute("SELECT sqlcipher_export('plaintext')")
        conn.execute('PRAGMA plaintext.user_version = %d' % version)
    finally:
        conn.execute('DETACH DATABASE plaintext')
    with closing(plain_connect(target)) as snapshot:
        if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup snapshot failed SQLite integrity')


def _wipe_and_remove(path):
    """Overwrite then delete a file that held patient data. Best effort: SSD wear levelling can keep old blocks."""
    for suffix in ('', '-wal', '-shm', '-journal'):
        target = path + suffix
        try:
            size = os.path.getsize(target)
            with open(target, 'r+b') as handle:
                left = size
                while left > 0:
                    chunk = min(left, 1 << 20)
                    handle.write(b'\0' * chunk)
                    left -= chunk
                handle.flush()
                os.fsync(handle.fileno())
            os.unlink(target)
        except OSError:
            try:
                os.unlink(target)
            except OSError:
                pass


_MIGRATION_LOCK_STALE = 600


class _migration_lock:
    def __init__(self, path):
        self.path = path + '.migrating'

    def __enter__(self):
        deadline = time.time() + 120
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > _MIGRATION_LOCK_STALE:
                        os.unlink(self.path)
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError('Another HMR Desk process is encrypting the database')
                time.sleep(0.25)

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass


def _user_tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _replace_retry(source, target, seconds=10):
    """os.replace that waits briefly when Windows still has the file open (antivirus, indexer, a stale handle)."""
    deadline = time.time() + seconds
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.time() > deadline:
                raise
            time.sleep(0.3)


def encrypt_plain_file(path, key, keep_original=False):
    """Encrypt an unencrypted SQLite file in place and verify it before the original is destroyed.

    Steps: checkpoint and integrity-check the original, export to a sibling file with sqlcipher_export,
    reopen it with the key, compare the schema version and every table's row count, swap the files, then
    overwrite and delete the original (it held patient data). Any failure leaves the original untouched.
    """
    path = str(path)
    tmp = path + '.encrypting'
    for leftover in (tmp, tmp + '-wal', tmp + '-shm', tmp + '-journal'):
        if os.path.exists(leftover):
            os.unlink(leftover)
    src = plain_connect(path)
    try:
        src.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('The database failed its integrity check, so it was not encrypted')
        version = src.execute('PRAGMA user_version').fetchone()[0]
        counts = {t: src.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0] for t in _user_tables(src)}
        src.execute('ATTACH DATABASE ? AS enc KEY ?', (tmp, _sql_key(key)))
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute('PRAGMA enc.user_version = %d' % version)
        src.execute('DETACH DATABASE enc')
    except Exception:
        src.close()
        for leftover in (tmp, tmp + '-wal', tmp + '-shm', tmp + '-journal'):
            if os.path.exists(leftover):
                os.unlink(leftover)
        raise
    src.close()
    try:
        with closing(open_encrypted(tmp, key=key)) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Encrypted copy failed its integrity check')
            if check.execute('PRAGMA user_version').fetchone()[0] != version:
                raise ValueError('Encrypted copy has a different schema version')
            if {t: check.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0] for t in _user_tables(check)} != counts:
                raise ValueError('Encrypted copy does not match the original')
        old = path + '.plain-old'
        for suffix in ('-wal', '-shm', '-journal'):
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        _replace_retry(path, old)
        _replace_retry(tmp, path)
    except Exception:
        for leftover in (tmp, tmp + '-wal', tmp + '-shm', tmp + '-journal'):
            if os.path.exists(leftover):
                os.unlink(leftover)
        raise
    if not keep_original:
        _wipe_and_remove(old)
    return {'tables': len(counts), 'rows': sum(counts.values())}


def _encrypt_siblings(path, key):
    """Older rolling backups and migration snapshots may still be plain files with patient data."""
    folder = os.path.dirname(os.path.abspath(path))
    found = []
    for pattern_dir, prefix in ((folder, 'hmr-backup-'), (os.path.join(folder, '.migration-snapshots'), '')):
        if not os.path.isdir(pattern_dir):
            continue
        for name in os.listdir(pattern_dir):
            full = os.path.join(pattern_dir, name)
            if name.endswith('.db') and name.startswith(prefix) and full != os.path.abspath(path) and dbkey.is_plain_file(full):
                found.append(full)
    for full in found:
        try:
            encrypt_plain_file(full, key)
        except Exception as exc:
            logging.warning('Could not encrypt %s (%s)', os.path.basename(full), type(exc).__name__)


def ensure_encrypted(path):
    """Make sure the database file at `path` is encrypted and a key exists for it.

    New file: create a key. Plain file (existing installation or a restored backup): encrypt it.
    Encrypted file: nothing to do; open_encrypted raises KeyUnavailable when the key is missing.
    """
    kind = dbkey.file_kind(path)
    if kind == 'encrypted':
        return 'encrypted'
    with _migration_lock(path):
        kind = dbkey.file_kind(path)
        if kind == 'encrypted':
            return 'encrypted'
        keys = dbkey.candidates(path) if dbkey.has_key_file(path) else []
        key = keys[0] if keys else dbkey.create_key(path)
        if kind == 'plain':
            encrypt_plain_file(path, key)
            _encrypt_siblings(path, key)
            return 'migrated'
        return 'new'


def rotate_key(conn):
    """Give the database a brand new key and return its recovery key text.

    Other open connections still hold the old key and stop working, so callers must restart the engine.
    """
    path = next(r[2] for r in conn.execute('PRAGMA database_list') if r[1] == 'main')
    new = dbkey.begin_rotation(path)
    try:
        conn.commit()
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.execute('PRAGMA rekey = "%s"' % _sql_key(new))
    except Exception:
        dbkey.abort_rotation(path)
        raise
    dbkey.finish_rotation(path)
    conn.hmr_key = new
    return dbkey.recovery_text(new)


def storage_status(path=None):
    path = path or db_path()
    info = dbkey.status(path)
    info['encrypted'] = info['database'] != 'plain'
    return info


def recover_key(text, path=None):
    """Seal a typed recovery key for this Windows account once it is proven to open the database."""
    path = path or db_path()

    def opens(key):
        try:
            open_encrypted(path, key=key).close()
            return True
        except dbkey.KeyUnavailable:
            return False
    if dbkey.file_kind(path) != 'encrypted':
        raise ValueError('There is no encrypted database to recover')
    return dbkey.install_recovery_key(path, text, opens)


def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    ensure_encrypted(path)
    conn = open_encrypted(path)
    conn.row_factory = sqlite3.Row
    try:
        dbkey.settle_pending(path, conn.hmr_key)
        conn.execute('PRAGMA journal_mode=WAL')
        # executescript has its own transaction boundary; never start a schema
        # migration transaction until the historical base tables exist.
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('Database schema is newer than this HMR Desk application')
        if version < SCHEMA_VERSION and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='patients'").fetchone():
            preserve_legacy_sqlite(conn)
        conn.executescript(SCHEMA)
        migrate_schema(conn)
        import_meetings(conn)
        return conn
    except Exception:
        conn.close()
        raise


def import_meetings(conn):
    from pathlib import Path
    from places import MEET
    if conn.execute("SELECT 1 FROM meta WHERE key='meetings_imported'").fetchone():
        return
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM meta WHERE key='meetings_imported'").fetchone():
            return
        plan = max(Path(BASE).glob('Appointment_Plan_*.json'), key=lambda p: p.stat().st_mtime, default=None)
        if plan:
            data = json.loads(plan.read_text(encoding='utf-8-sig'))
            for day, start, end, title in data.get('meetings', []):
                if day < datetime.date.today().isoformat():
                    continue
                conn.execute('''INSERT INTO appointments(date,start,end,title,place,note,created_at)
                    SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS
                    (SELECT 1 FROM appointments WHERE date=? AND start=? AND title=?)''',
                    (day, start, end, title, MEET.get(title), '', now(), day, start, title))
        conn.execute("INSERT INTO meta(key,value) VALUES ('meetings_imported','1')")


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def patient_key(name):
    """'Mr Alex Quinn Example' and 'alex example' -> 'alex example' (first + last word, letters only)."""
    original = unicodedata.normalize('NFKC', str(name or '')).casefold().strip()
    original = re.sub(r'^(?:mr|mrs|ms|miss|dr)\.?\s+', '', original)
    tokens = []
    for fragment in original.split():
        clean = ''.join(char for char in fragment
                        if char.isalpha() or char in ("'", '-')).strip("'-")
        if clean:
            tokens.append(clean)
    return f'{tokens[0]} {tokens[-1]}' if len(tokens) > 1 else (tokens[0] if tokens else '')


def log(conn, patient_id, type_, detail=None, source='engine'):
    conn.execute('INSERT INTO events (ts, patient_id, type, detail, source) VALUES (?,?,?,?,?)',
                 (now(), patient_id, type_, json.dumps(detail, ensure_ascii=False) if detail is not None else None, source))


def can_move(old, new):
    return new == old or new in STATES.get(old, ()) or (new in ('hold', 'declined', 'expired') and old in _PRE)


def set_state(conn, patient_id, new, status_text=None, source='engine', force=False):
    """Move a patient through the state machine and log it. force=True is for the importer and manual fixes."""
    row = conn.execute('SELECT state, status_text, is_test FROM patients WHERE id=?', (patient_id,)).fetchone()
    if row['is_test'] and status_text and not status_text.startswith('TEST'):
        status_text = 'TEST - ' + status_text
    if new not in STATES:
        raise ValueError(f'unknown state {new}')
    if not force and not can_move(row['state'], new):
        raise ValueError(f"{row['state']} -> {new} is not allowed")
    if row['state'] == new and (status_text is None or status_text == row['status_text']):
        return False
    conn.execute('UPDATE patients SET state=?, status_text=COALESCE(?, status_text), updated_at=? WHERE id=?',
                 (new, status_text, now(), patient_id))
    log(conn, patient_id, 'state', {'from': row['state'], 'to': new, 'text': status_text}, source)
    return True


def _first_sunday(year, month):
    d = datetime.date(year, month, 1)
    return d + datetime.timedelta(days=(6 - d.weekday()) % 7)


def utc_offset_hours(postcode, when=None):
    """Patient-local UTC offset. QLD has no daylight saving (+10). NSW/ACT/VIC/TAS add an hour from the first
    Sunday of October to the first Sunday of April. shortcut: no tzdata on this PC and 3 am edge hours ignored;
    upgrade to zoneinfo if patients outside the east coast are added."""
    when = when or datetime.datetime.now()
    pc = str(postcode or '')[:1]
    if pc in ('2', '3', '7'):
        d = when.date() if isinstance(when, datetime.datetime) else when
        if d >= _first_sunday(d.year, 10) or d < _first_sunday(d.year, 4):
            return 11
    return 10


def in_sending_window(postcode, when=None):
    """08:00-20:00 in the patient's own clock; `when` is this PC's clock (Queensland time)."""
    when = when or datetime.datetime.now()
    local = when + datetime.timedelta(hours=utc_offset_hours(postcode, when) - 10)
    return datetime.time(8, 0) <= local.time() < datetime.time(20, 0)


def backup(conn=None):
    """Copy the database next to itself as hmr-backup-<weekday>.db (7 rolling copies)."""
    own = conn is None
    conn = conn or connect()
    target = os.path.join(os.path.dirname(db_path()), f'hmr-backup-{datetime.date.today():%a}.db')
    out = open_encrypted(target, key=conn.hmr_key)
    try:
        conn.backup(out)
    finally:
        out.close()
    if own:
        conn.close()
    return target


if __name__ == '__main__':
    import tempfile
    assert patient_key('Mr Alex Quinn Example') == patient_key('alex example') == 'alex example'
    assert patient_key("Patricia D'Agostino") == "patricia d'agostino"
    assert utc_offset_hours('2486', datetime.datetime(2026, 11, 11, 9)) == 11   # NSW summer
    assert utc_offset_hours('2486', datetime.datetime(2026, 6, 1, 9)) == 10     # NSW winter
    assert utc_offset_hours('4216', datetime.datetime(2026, 11, 11, 9)) == 10   # QLD
    assert in_sending_window('4216', datetime.datetime(2026, 11, 11, 19, 30))
    assert not in_sending_window('2486', datetime.datetime(2026, 11, 11, 19, 30))  # 20:30 in NSW
    assert not in_sending_window('4216', datetime.datetime(2026, 11, 11, 7, 59))
    assert in_sending_window('2486', datetime.datetime(2026, 11, 11, 7, 30))       # 08:30 in NSW
    with tempfile.TemporaryDirectory() as t:
        c = connect(os.path.join(t, 'x.db'))
        c.execute("INSERT INTO patients (key, name) VALUES ('a b', 'A B')")
        assert set_state(c, 1, 'pooled') and set_state(c, 1, 'offered') and set_state(c, 1, 'confirmed')
        assert not set_state(c, 1, 'confirmed')            # no change, no event
        try:
            set_state(c, 1, 'claimed'); raise SystemExit('should have refused confirmed -> claimed')
        except ValueError:
            pass
        assert set_state(c, 1, 'declined') and set_state(c, 1, 'pooled')
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 5
        c.close()
    print('db self-check ok')
