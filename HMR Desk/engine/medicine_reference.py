"""Read-only lookup over the separate medicine reference database.

The reference file is licensed terminology the operator loads themselves. It is never
bundled, never opened for writing here, and never mixed with the patient database.
A missing file is a normal state: the interview keeps working with free text.
"""
import os
from pathlib import Path
import shutil
import sqlite3
import db
from medicine_data import catalog

FILE_NAME = 'medicine-reference.sqlite'


def reference_path():
    return Path(db.DATA_DIR) / FILE_NAME


def _open():
    path = reference_path()
    if not path.is_file():
        return None
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def status():
    conn = _open()
    if conn is None:
        return {'installed': False, 'sources': [], 'message': 'No medicine reference data is installed. Type medicine names by hand.'}
    try:
        rows = conn.execute('SELECT source, release, row_count FROM source_release ORDER BY source').fetchall()
    except sqlite3.Error:
        return {'installed': False, 'sources': [], 'message': 'The medicine reference file could not be read. Type medicine names by hand.'}
    finally:
        conn.close()
    return {'installed': bool(rows), 'sources': [dict(r) for r in rows], 'message': ''}


def search(text, limit=15):
    """Contains match only. The pharmacist picks; nothing is chosen for them."""
    conn = _open()
    if conn is None:
        return {'installed': False, 'results': []}
    try:
        found = catalog.search(conn, text, limit)
    except sqlite3.Error:
        return {'installed': False, 'results': []}
    finally:
        conn.close()
    return {'installed': True, 'results': [{
        'source': r['source'], 'code': r['code'], 'display': r['display'], 'kind': r['kind'],
        'generic_name': r['generic_name'], 'brand_name': r['brand_name'], 'dose_form': r['dose_form'],
        'release': r['release']} for r in found]}


def pick(source, code):
    """Return the stored reference for one concept, or None. Used to validate a saved choice."""
    conn = _open()
    if conn is None:
        return None
    try:
        r = conn.execute('SELECT m.source, m.code, m.display, s.release FROM medicine m JOIN source_release s USING(source) WHERE m.source=? AND m.code=?', (source, code)).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def suggest_many(queries):
    """Deterministic local proposals only. Never choose or confirm a medicine.

    Exact displayed text is distinguished from broader search candidates. No
    OCR character/unit corrections, equivalence rules or doses are inferred.
    """
    import re
    if not isinstance(queries, list) or len(queries) > 80 or any(not isinstance(q, str) or len(q) > 20000 for q in queries):
        raise ValueError('Invalid medicine suggestion queries')
    conn = _open()
    def result(query, state, rows=(), truncated=False):
        return {'input_text': query, 'state': state, 'truncated': truncated,
                'candidates': [{key: row[key] for key in ('source','code','display','kind','generic_name','brand_name','dose_form','release')} for row in rows]}
    if conn is None:
        return {'installed': False, 'results': [result(q, 'unavailable') for q in queries]}
    try:
        results, cache = [], {}
        for text in queries:
            if text in cache:
                results.append(cache[text]); continue
            query = catalog.normalise(text)
            if len(query) < 2 or len(query) > 400:
                entry = result(text, 'unmatched')
            else:
                exact = conn.execute('''SELECT m.*, r.release FROM medicine m
                    JOIN source_release r USING(source) WHERE lower(display)=?
                    ORDER BY m.source,m.code LIMIT 16''', (query,)).fetchall()
                if exact:
                    entry = result(text, 'exact_candidate' if len(exact) == 1 else 'ambiguous', exact[:15], len(exact) > 15)
                else:
                    found = catalog.search(conn, text, 16)
                    if not found:
                        # Broaden candidate discovery only, never identify from the stripped name.
                        prefix = re.split(r'\d', text, maxsplit=1)[0].strip()
                        if 2 <= len(prefix) <= 80 and prefix != text.strip():
                            found = catalog.search(conn, prefix, 16)
                    entry = result(text, 'review_candidates' if found else 'unmatched', found[:15], len(found) > 15)
            cache[text] = entry; results.append(entry)
        return {'installed': True, 'results': results}
    except sqlite3.Error:
        return {'installed': False, 'results': [result(q, 'unavailable') for q in queries]}
    finally:
        conn.close()


MAX_REFERENCE_BYTES = 4 * 1024 * 1024 * 1024
REQUIRED_TABLES = {'source_release', 'medicine', 'source_row'}


def _validate_candidate(source):
    """Open the candidate read-only and prove it is a usable reference before any replace."""
    try:
        conn = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error:
        raise ValueError('The selected file could not be opened as a readable reference database')
    try:
        quick = conn.execute('PRAGMA quick_check').fetchone()
        if quick is None or quick[0] != 'ok':
            raise ValueError('The medicine reference file failed its integrity check')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES <= tables:
            raise ValueError('The file is not a HMR Desk medicine reference database (missing required tables)')
        releases = conn.execute(
            'SELECT source, release, row_count FROM source_release ORDER BY source').fetchall()
        if not releases:
            raise ValueError('The reference file records no imported sources')
        count = conn.execute('SELECT count(*) FROM medicine').fetchone()[0]
        if count < 1:
            raise ValueError('The reference file contains no medicine records')
        if sum(int(r[2]) for r in releases) != count:
            raise ValueError('The reference file source counts do not match its medicine records')
    except sqlite3.Error:
        raise ValueError('The selected file could not be read as a valid medicine reference database')
    finally:
        conn.close()
    return [{'source': r[0], 'release': r[1], 'row_count': r[2]} for r in releases]


def install(source_path):
    """Install an operator-supplied licensed reference database.

    The candidate is fully validated read-only before anything is replaced; a rejected
    candidate leaves the current working reference untouched. On a successful install
    the previous reference is kept as medicine-reference.previous.sqlite for rollback.
    The file is licensed operator data: copied verbatim, never modified or bundled.
    """
    source = Path(source_path)
    if (not source.is_absolute() or source.is_symlink() or not source.is_file()
            or source.suffix.lower() != '.sqlite'):
        raise ValueError('Select the medicine reference SQLite file')
    if source.stat().st_size > MAX_REFERENCE_BYTES:
        raise ValueError('The medicine reference file is too large')
    target = reference_path()
    if source.resolve() == target.resolve():
        raise ValueError('The selected file is already the installed reference')
    sources = _validate_candidate(source)
    data_dir = Path(db.DATA_DIR)
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if data_dir.is_symlink():
        raise ValueError('Unsafe data folder')
    temp = data_dir / (FILE_NAME + '.incoming')
    try:
        with open(source, 'rb') as src, open(temp, 'wb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if temp.stat().st_size != source.stat().st_size:
            raise ValueError('The reference copy did not complete; current reference unchanged')
        previous = data_dir / 'medicine-reference.previous.sqlite'
        if previous.is_symlink() or target.is_symlink():
            raise ValueError('Unsafe reference files')
        if target.exists():
            os.replace(target, previous)
        os.replace(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    installed = status()
    if not installed['installed']:
        previous = data_dir / 'medicine-reference.previous.sqlite'
        if previous.exists():
            os.replace(previous, target)
        else:
            target.unlink(missing_ok=True)
        raise ValueError('Installed reference failed verification; previous reference restored')
    return {'installed': True, 'sources': installed['sources']}
