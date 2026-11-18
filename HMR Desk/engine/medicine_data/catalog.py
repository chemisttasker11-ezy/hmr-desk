"""Separate reference SQLite database; never opens the patient hmr.db.

Each source import is a full snapshot, committed together with its provenance.
An invalid/empty import raises and rolls back, preserving the previous snapshot.
"""
import contextlib
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS source_release (
 source TEXT PRIMARY KEY, release TEXT NOT NULL, imported_at TEXT NOT NULL,
 sha256 TEXT NOT NULL, source_url TEXT NOT NULL, row_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS medicine (
 source TEXT NOT NULL, code TEXT NOT NULL, display TEXT NOT NULL,
 search_text TEXT NOT NULL, kind TEXT NOT NULL, generic_name TEXT,
 brand_name TEXT, dose_form TEXT, strength_json TEXT NOT NULL DEFAULT '[]',
 details_json TEXT NOT NULL, PRIMARY KEY(source,code));
CREATE INDEX IF NOT EXISTS medicine_search ON medicine(search_text);
CREATE TABLE IF NOT EXISTS source_row (
 source TEXT NOT NULL, table_name TEXT NOT NULL, row_number INTEGER NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(source,table_name,row_number));
"""


def normalise(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text)).casefold().split())


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def connect(path):
    path = Path(path)
    # Avoid a typo writing reference tables into the default patient database.
    if path.name.casefold() == 'hmr.db':
        raise ValueError('Use a separate medicine-reference.sqlite database, not hmr.db')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, SCHEMA_VERSION):
        db.close()
        raise ValueError('Unsupported reference database schema')
    if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patients'").fetchone():
        db.close()
        raise ValueError('Refusing to modify a patient database')
    db.executescript(SCHEMA)
    db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
    db.commit()
    return db


@contextlib.contextmanager
def snapshot(db, source, release, path, url):
    if not release.strip() or not url.strip():
        raise ValueError('Explicit source release and provenance URL required')
    with db:
        # Derived search index would go stale under an external-content table; drop it. Rebuilt at install.
        db.execute('DROP TABLE IF EXISTS medicine_fts')
        db.execute('DROP TABLE IF EXISTS search_index_meta')
        db.execute('DELETE FROM medicine WHERE source=?', (source,))
        db.execute('DELETE FROM source_row WHERE source=?', (source,))
        yield
        count = db.execute('SELECT count(*) FROM medicine WHERE source=?', (source,)).fetchone()[0]
        if not count:
            raise ValueError(f'{source}: empty medicine snapshot refused')
        db.execute('INSERT OR REPLACE INTO source_release VALUES (?,?,?,?,?,?)',
                   (source, release, dt.datetime.now(dt.timezone.utc).isoformat(),
                    sha256(path), url, count))


def add_medicine(db, source, code, display, kind, generic=None, brand=None,
                 form=None, strengths=None, details=None, aliases=()):
    if not code or not display:
        raise ValueError('Medicine code and display are required')
    search = normalise(' '.join([display, generic or '', brand or '', *aliases]))
    db.execute('INSERT INTO medicine VALUES (?,?,?,?,?,?,?,?,?,?)',
               (source, code, display, search, kind, generic, brand, form,
                json.dumps(strengths or [], ensure_ascii=False),
                json.dumps(details or {}, ensure_ascii=False)))


def add_raw(db, source, table, number, row):
    db.execute('INSERT INTO source_row VALUES (?,?,?,?)',
               (source, table, number, json.dumps(row, ensure_ascii=False)))


DISPLAY_INDEX = 'medicine_display_lower'
FTS_TABLE = 'medicine_fts'
META_TABLE = 'search_index_meta'
INDEX_VERSION = 1
_DISPLAY_SQL = 'createindex' + DISPLAY_INDEX + 'onmedicine(lower(display))'
_FTS_SQL = ('createvirtualtable' + FTS_TABLE + "usingfts5(search_text,content='medicine',content_rowid='rowid',tokenize='trigram')")
_TRUST = {}


def _sql_norm(sql):
    return ''.join(str(sql or '').lower().replace('"', '').replace('`', '').split())


def _schema_sql(db, name):
    row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
    return _sql_norm(row[0]) if row else None


def content_fingerprint(db):
    """Hash of everything the trigram index is derived from: rowid, source, code, display and search_text."""
    h = hashlib.sha256()
    for row in db.execute('SELECT rowid, source, code, display, search_text FROM medicine ORDER BY rowid'):
        h.update('\x1f'.join(str(x) for x in row).encode('utf-8', 'surrogatepass')); h.update(b'\n')
    return h.hexdigest()


def _fts_check_command_works():
    """Prove by execution that this SQLite supports trigram FTS5 AND that its content check detects a stale index."""
    try:
        t = sqlite3.connect(':memory:')
        t.execute('CREATE TABLE medicine(source, code, search_text)')
        t.execute("INSERT INTO medicine VALUES('s','1','abcdef')")
        t.execute(f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5(search_text, content='medicine', content_rowid='rowid', tokenize='trigram')")
        t.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')")
        t.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rank) VALUES('integrity-check', 1)")  # must pass when fresh
        if t.execute(f"SELECT rowid FROM {FTS_TABLE} WHERE search_text LIKE '%bcd%'").fetchone() is None:
            return False
        t.execute("UPDATE medicine SET search_text='zzzzzz'")  # same row count, different content
        try:
            t.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rank) VALUES('integrity-check', 1)")
        except sqlite3.DatabaseError:
            return True  # stale index was detected
        return False
    except sqlite3.Error:
        return False
    finally:
        try: t.close()
        except Exception: pass


def build_search_index(db):
    """Add derived search indexes to a writable reference copy; medicine rows are never changed.

    Existing objects are inspected, not trusted by name: a differing definition is dropped and rebuilt, and the
    trigram index is always rebuilt from the current rows, checked against them, and recorded with a content
    fingerprint. Returns {'display': bool, 'fts': bool, 'content_sha256': str|None}.
    """
    if _schema_sql(db, DISPLAY_INDEX) not in (None, _DISPLAY_SQL):
        db.execute(f'DROP INDEX {DISPLAY_INDEX}')
    db.execute(f'CREATE INDEX IF NOT EXISTS {DISPLAY_INDEX} ON medicine(lower(display))')
    made = {'display': True, 'fts': False, 'content_sha256': None}
    db.execute(f'DROP TABLE IF EXISTS {META_TABLE}')
    if _schema_sql(db, FTS_TABLE) is not None:
        db.execute(f'DROP TABLE {FTS_TABLE}')  # never reuse an index whose provenance is unknown
    if not _fts_check_command_works():
        db.commit()
        return made
    try:
        db.execute(f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5(search_text, content='medicine', content_rowid='rowid', tokenize='trigram')")
        db.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')")
        db.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rank) VALUES('integrity-check', 1)")
        digest = content_fingerprint(db)
        rows = db.execute('SELECT count(*) FROM medicine').fetchone()[0]
        db.execute(f'CREATE TABLE {META_TABLE}(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.executemany(f'INSERT INTO {META_TABLE} VALUES(?,?)', [
            ('version', str(INDEX_VERSION)), ('rows', str(rows)), ('content_sha256', digest),
            ('fts_sql', _schema_sql(db, FTS_TABLE)), ('display_sql', _schema_sql(db, DISPLAY_INDEX)),
            ('built_at', dt.datetime.now(dt.timezone.utc).isoformat()), ('sqlite_version', sqlite3.sqlite_version)])
        made.update(fts=True, content_sha256=digest)
    except sqlite3.Error:
        db.execute(f'DROP TABLE IF EXISTS {FTS_TABLE}'); db.execute(f'DROP TABLE IF EXISTS {META_TABLE}')
    db.commit()
    return made


def _header_counter(file):
    try:
        with open(file, 'rb') as f:
            f.seek(24); return f.read(4)
    except OSError:
        return None


def _fts_usable(db):
    """The trigram index may narrow results only if it is provably the index of the CURRENT medicine rows:
    recorded definition equals the expected one, version matches, and a fresh fingerprint of the rows equals
    the fingerprint recorded when the index was built and checked. Cached per file state; any doubt means no."""
    try:
        file = db.execute('PRAGMA database_list').fetchone()[2]
        stat = Path(file).stat() if file else None
        key = (file, stat.st_mtime_ns, stat.st_size, _header_counter(file)) if stat else None
        if key is not None and key in _TRUST:
            return _TRUST[key]
        meta = dict(db.execute(f'SELECT key, value FROM {META_TABLE}').fetchall())
        ok = (meta.get('version') == str(INDEX_VERSION) and meta.get('fts_sql') == _FTS_SQL
              and _schema_sql(db, FTS_TABLE) == _FTS_SQL
              and meta.get('rows') == str(db.execute('SELECT count(*) FROM medicine').fetchone()[0])
              and meta.get('content_sha256') == content_fingerprint(db))
        if key is not None:
            _TRUST[key] = ok
        return ok
    except (sqlite3.Error, OSError):
        return False


def search(db, text, limit=20):
    """Contains match with bound SQL and escaped LIKE wildcards, not clinical matching.

    Caller displays source/release and requires human selection. No fuzzy merges.
    When the derived trigram index is present, it only narrows the candidate rows; the original LIKE
    predicate is still applied to them, so the results are identical to the plain scan.
    """
    query = normalise(text)
    if len(query) < 2:
        return []
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    db.row_factory = sqlite3.Row
    def run(use_index):
        narrow = ''
        args = ['%' + escaped + '%']
        if use_index:
            narrow = f' AND m.rowid IN (SELECT rowid FROM {FTS_TABLE} WHERE search_text LIKE ?)'
            args.append('%' + query + '%')
        args += [escaped + '%', limit]
        rows = db.execute(f"""SELECT m.*, r.release, r.imported_at FROM medicine m
          JOIN source_release r USING(source)
          WHERE search_text LIKE ? ESCAPE '\\'{narrow}
          ORDER BY CASE WHEN search_text LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                   display, source, code LIMIT ?""", args).fetchall()
        return [dict(row) for row in rows]
    if len(query) >= 3 and not any(c in query for c in '%_\\') and _fts_usable(db):
        try:
            return run(True)
        except sqlite3.DatabaseError:
            _TRUST.clear()  # an index that errors is not trusted; fall through to the plain scan
    return run(False)
