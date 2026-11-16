"""Encrypted clinical record store (stage 1: store, import, export; nothing calls it yet).

Saved clinical records (interview, report spec, confirmed medicines) move from plain files in the patient
folder into the SQLCipher database, keyed by patient id so a folder move does not matter.

Rules that keep records safe:
  * Import only copies. A file is never overwritten into a newer database record, and never removed here.
  * If the database already holds a different record, the file is left alone and reported as a conflict.
  * Export writes an ordinary copy of the records to a folder the user picks. That copy is OUTSIDE the
    app's encryption. Export never overwrites an existing file.
Word, PDF and source-file outputs are not stored here and stay plain files.
"""
import datetime, hashlib, json, os, re
from pathlib import Path

# Patient-folder files that hold patient-specific clinical content. Fixed templates, reference data and the
# Word/PDF/consent/source documents are NOT records here.
RECORD_PATTERNS = (
    r'interview\.json(\.bak)?',
    r'report_spec(\.ai)?\.json(\.bak)?',
    r'confirmed_meds\.json',
    r'followup[12]\.json',
    r'pathology_sources\.json',
    r'pathology_records\.json',
    r'reconciliation_review\.json',
    r'MIMS interactions[^/\\]{0,200}\.txt',
)
_RECORD_RE = re.compile('(?:' + '|'.join(RECORD_PATTERNS) + ')')
EXPORT_NOTE = 'README - exported records.txt'
EXPORT_NOTE_TEXT = (
    'These files are a copy of saved HMR Desk clinical records.\n'
    'This copy is OUTSIDE the encryption HMR Desk applies to its own storage. Anyone who can open this folder\n'
    'can read it. Keep it somewhere you trust and delete it when you no longer need it. Deleting a file\n'
    'normally does not guarantee the data is unrecoverable from the disk.\n'
    'Files named "MIMS interactions ..." contain MIMS content. Keep them within your MIMS licence terms\n'
    'and do not share them outside it.\n'
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  patient_id INTEGER NOT NULL, name TEXT NOT NULL, body BLOB NOT NULL,
  revision TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (patient_id, name)
);
"""


class Conflict(Exception):
    pass


def _now():
    return datetime.datetime.now().isoformat(timespec='microseconds')


def is_record_name(name):
    return isinstance(name, str) and _RECORD_RE.fullmatch(name) is not None


def _check(name):
    if not is_record_name(name):
        raise ValueError('not a record name')
    return name


def digest(body):
    """Same token the file-based code used: sha256 of the exact bytes, or 'missing'."""
    return hashlib.sha256(body).hexdigest() if body is not None else 'missing'


def ensure(conn):
    conn.execute(SCHEMA)  # not executescript: that would commit the caller's open transaction


def get(conn, patient_id, name):
    ensure(conn)
    row = conn.execute('SELECT body FROM records WHERE patient_id=? AND name=?', (patient_id, _check(name))).fetchone()
    return bytes(row[0]) if row else None


def exists(conn, patient_id, name):
    return get(conn, patient_id, name) is not None


def revision(conn, patient_id, name):
    return digest(get(conn, patient_id, name))


def put(conn, patient_id, name, body, expected_revision=None):
    """Write inside the caller's transaction (the caller commits). A stale expected revision raises Conflict."""
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError('record body must be bytes')
    body = bytes(body)
    ensure(conn)
    if expected_revision is not None and expected_revision != revision(conn, patient_id, name):
        raise Conflict('record changed since it was read')
    conn.execute(
        'INSERT INTO records(patient_id,name,body,revision,updated_at) VALUES(?,?,?,?,?) '
        'ON CONFLICT(patient_id,name) DO UPDATE SET body=excluded.body, revision=excluded.revision, updated_at=excluded.updated_at',
        (patient_id, _check(name), body, digest(body), _now()))
    return digest(body)


def delete(conn, patient_id, name):
    ensure(conn)
    conn.execute('DELETE FROM records WHERE patient_id=? AND name=?', (patient_id, _check(name)))


def names(conn, patient_id):
    ensure(conn)
    return [r[0] for r in conn.execute('SELECT name FROM records WHERE patient_id=? ORDER BY name', (patient_id,))]


def import_folder(conn, patient_id, folder):
    """Copy record files from a patient folder into the database, verified by read-back.

    Returns {name: 'imported' | 'already' | 'conflict'} for files that exist. Repeating it is safe: an existing
    database record is never replaced by a file. Files are not changed or removed."""
    ensure(conn)
    folder = Path(folder)
    result = {}
    for name in sorted(n for n in os.listdir(folder) if is_record_name(n)):
        path = folder / name
        if not path.is_file():
            continue
        body = path.read_bytes()
        current = get(conn, patient_id, name)
        if current is None:
            put(conn, patient_id, name, body)
            conn.commit()
            if get(conn, patient_id, name) != body:
                raise RuntimeError('record import did not verify: ' + name)
            result[name] = 'imported'
        elif current == body:
            result[name] = 'already'
        else:
            result[name] = 'conflict'
    return result


def export_folder(conn, patient_id, destination):
    """Write a plain copy of the patient's records into destination. Never overwrites.

    Returns {name: 'written' | 'exists'}. The copy is outside the app's encryption (see EXPORT_NOTE)."""
    ensure(conn)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in names(conn, patient_id):
        target = destination / name
        try:
            with open(target, 'xb') as out:
                out.write(get(conn, patient_id, name))
                out.flush(); os.fsync(out.fileno())
            result[name] = 'written'
        except FileExistsError:
            result[name] = 'exists'
    note = destination / EXPORT_NOTE
    if not note.exists():
        note.write_text(EXPORT_NOTE_TEXT, encoding='utf-8')
    return result


def removable_files(conn, patient_id, folder):
    """Record files whose bytes match the database exactly (safe to retire in a later stage)."""
    folder = Path(folder)
    return [folder / n for n in sorted(os.listdir(folder))
            if is_record_name(n) and (folder / n).is_file() and get(conn, patient_id, n) == (folder / n).read_bytes()]


def stamp(conn, patient_id, name):
    """When the record was last written (sortable text), or None. Replaces file modification times."""
    ensure(conn)
    row = conn.execute('SELECT updated_at FROM records WHERE patient_id=? AND name=?', (patient_id, _check(name))).fetchone()
    return row[0] if row else None


def names_like(conn, patient_id, prefix):
    """Record names for a patient that start with prefix, case-insensitively."""
    return [n for n in names(conn, patient_id) if n.lower().startswith(prefix.lower())]


def get_json(conn, patient_id, name):
    body = get(conn, patient_id, name)
    return None if body is None else json.loads(body.decode('utf-8'))


def dumps(data):
    """Same layout the file-based code wrote (indent 2, real characters)."""
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


def put_json(conn, patient_id, name, data):
    return put(conn, patient_id, name, dumps(data))


def migrate_all(conn, folder_for):
    """Copy every patient's plain record files into the encrypted store (verify-then-keep).

    folder_for(patient_row) returns the patient's folder or None. A repeat is safe: an existing database record is
    never overwritten, and a differing plain file is reported as a conflict and left alone. Plain files are not
    deleted here. Returns a summary with no patient details."""
    ensure(conn)
    summary = {'patients': 0, 'imported': 0, 'already': 0, 'conflict': 0, 'no_folder': 0, 'errors': 0}
    for patient in conn.execute('SELECT * FROM patients').fetchall():
        summary['patients'] += 1
        try:
            folder = folder_for(patient)
        except Exception:
            folder = None
        if not folder or not Path(folder).is_dir():
            summary['no_folder'] += 1
            continue
        try:
            for outcome in import_folder(conn, patient['id'], folder).values():
                summary[outcome] += 1
        except Exception:
            summary['errors'] += 1
    return summary


def status(conn, folder_for):
    """Where saved records live right now. Plain copies count as unprotected until they are retired."""
    ensure(conn)
    stored = conn.execute('SELECT COUNT(*) FROM records').fetchone()[0]
    plain_same = plain_other = 0
    for patient in conn.execute('SELECT * FROM patients').fetchall():
        try:
            folder = folder_for(patient)
        except Exception:
            continue
        if not folder or not Path(folder).is_dir():
            continue
        for name in os.listdir(folder):
            if not is_record_name(name) or not (Path(folder) / name).is_file():
                continue
            if get(conn, patient['id'], name) == (Path(folder) / name).read_bytes():
                plain_same += 1
            else:
                plain_other += 1
    return {'records_in_encrypted_store': stored, 'plain_copies_matching_store': plain_same,
            'plain_files_differing_or_not_stored': plain_other,
            'saved_records_protected': False,
            'note': 'Plain record files remain in patient folders until they are removed. Word, PDF and source '
                    'documents are not encrypted by the app.'}
