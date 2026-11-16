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


def search(db, text, limit=20):
    """Contains match with bound SQL and escaped LIKE wildcards, not clinical matching.

    Caller displays source/release and requires human selection. No fuzzy merges.
    """
    query = normalise(text)
    if len(query) < 2:
        return []
    if not 1 <= limit <= 100:
        raise ValueError('limit must be 1..100')
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    db.row_factory = sqlite3.Row
    rows = db.execute("""SELECT m.*, r.release, r.imported_at FROM medicine m
      JOIN source_release r USING(source)
      WHERE search_text LIKE ? ESCAPE '\\'
      ORDER BY CASE WHEN search_text LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
               display, source, code LIMIT ?""", ('%' + escaped + '%', escaped + '%', limit))
    return [dict(row) for row in rows]
