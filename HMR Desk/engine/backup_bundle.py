"""Authenticated, passphrase-encrypted, full-workspace HMR backup and isolated restore.

A backup holds the SQLite database (which also stores every app setting), the
whole patient workspace, and the locally registered approved report template
folder (approved template, its approval manifest and revision history) under
``data/templates/``. Machine-specific files such as app-config.json (an
absolute workspace path) and the per-session API token are deliberately not
included.

Format: HMRBKP1 + 16 byte scrypt salt + 12 byte AES-256-GCM nonce +
streamed ciphertext + 16 byte GCM tag. No key or password is written to disk.
"""
import hashlib
from contextlib import closing
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import tempfile
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

import db

MAGIC = b'HMRBKP1'
CHUNK = 1024 * 1024
MAX_FILES = 25000
MAX_UNPACKED = 16 * 1024 ** 3
TEMPLATE_PREFIX = ('data', 'templates')


def _safe_data_entry(parts):
    """Only the database and the approved-template folder may live under data/."""
    if parts[0] == 'workspace':
        return True
    return parts == ('data', 'hmr.db') or (len(parts) >= 3 and parts[:2] == TEMPLATE_PREFIX)


def _template_files(data_root):
    folder = data_root / 'templates'
    if folder.is_symlink():
        raise ValueError('Unsafe template folder')
    found = []
    if folder.is_dir():
        for item in sorted(folder.rglob('*')):
            if item.is_symlink():
                raise ValueError('Template folder contains a symlink; remove it before backup')
            if item.is_file() and not item.name.startswith('.approved-'):
                found.append(('data/templates/' + item.relative_to(folder).as_posix(), item))
    return found


def _scan(workspace, templates):
    scanned = {('workspace/' + item.relative_to(workspace).as_posix()):
               (item.stat().st_size, item.stat().st_mtime_ns)
               for item in workspace.rglob('*') if item.is_file() and not item.is_symlink()}
    scanned.update({name: (path.stat().st_size, path.stat().st_mtime_ns) for name, path in templates})
    return scanned


def key_for(password, salt):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 512:
        raise ValueError('Backup passphrase must contain at least 12 characters')
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode('utf-8'))


def _within(parent, child):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False



def _private_stage_root():
    """Keep plaintext backup/restore intermediates in the per-user app data area.

    The default shared OS temp directory is not an acceptable place for clinical
    SQLite snapshots, decrypted ZIPs, or patient files. Windows ACL inheritance
    from the application's per-user data root still needs an installed-VM audit.
    """
    root = Path(db.DATA_DIR).resolve() / '.protected-backup-staging'
    if root.is_symlink():
        raise ValueError('Unsafe staging directory')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Unsafe staging directory')
    if os.name != 'nt':
        root.chmod(0o700)
    return root


def create(conn, workspace, output, password):
    """Snapshot SQLite via backup API; add all non-symlink workspace files, then encrypt."""
    workspace = Path(workspace).resolve()
    output = Path(output).resolve()
    data_root = Path(db.DATA_DIR).resolve()
    if not workspace.is_dir():
        raise ValueError('Workspace does not exist')
    if _within(workspace, output) or _within(data_root, output):
        raise ValueError('Store backups outside the patient workspace and application data')
    if output.exists():
        raise FileExistsError('Backup destination already exists')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = key_for(password, salt)
    output.parent.mkdir(parents=True, exist_ok=True)
    data_version = conn.execute('PRAGMA data_version').fetchone()[0]
    total_changes = conn.total_changes
    with tempfile.TemporaryDirectory(prefix='hmr-backup-', dir=_private_stage_root()) as directory:
        root = Path(directory)
        database = root / 'hmr.db'
        # The snapshot inside the passphrase-encrypted bundle is plain SQLite on purpose: a restore on a
        # new PC then needs only the passphrase. The engine encrypts it with that PC's key on first connect.
        db.plain_snapshot(conn, database)
        zipped = root / 'snapshot.zip'
        index = {}
        paths = [('data/hmr.db', database)]
        templates = _template_files(data_root)
        paths.extend(templates)
        for item in sorted(workspace.rglob('*')):
            if item.is_symlink():
                raise ValueError('Workspace contains a symlink; remove it before backup')
            if item.is_file():
                paths.append(('workspace/' + item.relative_to(workspace).as_posix(), item))
        # Capture the complete file set and metadata. If a parallel interview,
        # referral or report save changes anything, abort rather than publish
        # a deceptively successful but inconsistent multi-file archive.
        before = _scan(workspace, templates)
        if len(paths) > MAX_FILES:
            raise ValueError('Too many files to back up')
        with zipfile.ZipFile(zipped, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for name, path in paths:
                if not path.is_file():
                    raise ValueError('Source file disappeared during backup')
                hasher = hashlib.sha256()
                length = 0
                with path.open('rb') as source, archive.open(name, 'w') as dest:
                    while chunk := source.read(CHUNK):
                        hasher.update(chunk)
                        length += len(chunk)
                        dest.write(chunk)
                index[name] = {'sha256': hasher.hexdigest(), 'size': length}
            archive.writestr('manifest.json', json.dumps({'format': 1, 'files': index},
                                                         sort_keys=True))
        fd, temp = tempfile.mkstemp(prefix='.hmr-encrypt-', dir=output.parent)
        try:
            with os.fdopen(fd, 'wb') as encrypted, zipped.open('rb') as original:
                encrypted.write(MAGIC + salt + nonce)
                encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
                while chunk := original.read(CHUNK):
                    encrypted.write(encryptor.update(chunk))
                encrypted.write(encryptor.finalize())
                encrypted.write(encryptor.tag)
                encrypted.flush()
                os.fsync(encrypted.fileno())
            current = _scan(workspace, _template_files(data_root))
            if current != before or conn.total_changes != total_changes or (
                    conn.execute('PRAGMA data_version').fetchone()[0] != data_version):
                raise ValueError('Patient workspace or database changed during backup; retry when no edits are pending')
            if output.exists():
                raise FileExistsError('Backup destination already exists')
            os.replace(temp, output)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {'created': True, 'bytes': output.stat().st_size}


def restore(source, destination, password, preview_only=False):
    """Verify a backup and optionally preview without writing to any live destination.

    Restoration always targets a NEW isolated folder; preview uses the same
    encrypted authentication, file digest and database integrity checks.
    """
    source = Path(source).resolve()
    destination = Path(destination).resolve() if not preview_only else None
    if not source.is_file():
        raise ValueError('Backup file not found')
    if not preview_only:
        if destination.exists():
            raise FileExistsError('Restore destination must not already exist')
        if _within(Path(db.BASE).resolve(), destination) or _within(Path(db.DATA_DIR).resolve(), destination):
            raise ValueError('Restore into a separate folder outside the active workspace')
    with source.open('rb') as raw:
        prefix = raw.read(len(MAGIC) + 16 + 12)
        if len(prefix) != len(MAGIC) + 28 or not prefix.startswith(MAGIC):
            raise ValueError('Not an HMR encrypted backup')
        salt = prefix[len(MAGIC):len(MAGIC) + 16]
        nonce = prefix[-12:]
        key = key_for(password, salt)
        length = source.stat().st_size
        if length <= len(prefix) + 16:
            raise ValueError('Invalid backup length')
        raw.seek(-16, os.SEEK_END)
        tag = raw.read(16)
        raw.seek(len(prefix))
        remaining = length - len(prefix) - 16
        with tempfile.TemporaryDirectory(prefix='hmr-restore-', dir=_private_stage_root()) as directory:
            temp = Path(directory)
            zipped = temp / 'data.zip'
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            try:
                with zipped.open('wb') as out:
                    while remaining:
                        chunk = raw.read(min(CHUNK, remaining))
                        if not chunk:
                            raise ValueError('Truncated encrypted backup')
                        remaining -= len(chunk)
                        out.write(decryptor.update(chunk))
                    out.write(decryptor.finalize())
            except (ValueError, InvalidTag) as exc:
                raise ValueError('Wrong passphrase or corrupt encrypted backup') from exc
            stage = temp / 'restored'
            stage.mkdir()
            with zipfile.ZipFile(zipped) as archive:
                names = archive.namelist()
                if not names or names[-1] != 'manifest.json' or len(names) > MAX_FILES + 1:
                    raise ValueError('Invalid backup manifest')
                manifest = json.loads(archive.read('manifest.json'))
                files = manifest.get('files')
                if manifest.get('format') != 1 or not isinstance(files, dict) or set(names[:-1]) != set(files):
                    raise ValueError('Backup manifest does not match archive')
                if 'data/hmr.db' not in files:
                    raise ValueError('Backup has no database')
                size = 0
                for name in names[:-1]:
                    part = Path(name)
                    if (part.is_absolute() or '..' in part.parts or len(part.parts) < 2 or
                            part.parts[0] not in ('data', 'workspace') or not _safe_data_entry(part.parts)):
                        raise ValueError('Unsafe archive path')
                    size += archive.getinfo(name).file_size
                    if size > MAX_UNPACKED:
                        raise ValueError('Backup exceeds maximum uncompressed size')
                    target = stage.joinpath(*part.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    copied = 0
                    with archive.open(name) as source_file, target.open('xb') as out:
                        while chunk := source_file.read(CHUNK):
                            copied += len(chunk)
                            h.update(chunk)
                            out.write(chunk)
                    if copied != files[name]['size'] or h.hexdigest() != files[name]['sha256']:
                        raise ValueError('Backup checksum mismatch')
            with closing(sqlite3.connect(stage / 'data' / 'hmr.db')) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Restored database failed integrity check')
                if preview_only:
                    patients = check.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
                    return {
                        'verified': True,
                        'format': manifest['format'],
                        'patients': patients,
                        'files': len(files),
                        'bytes_uncompressed': size,
                        'workspace_files': sum(name.startswith('workspace/') for name in files),
                        'template_files': sum(name.startswith('data/templates/') for name in files),
                        'will_activate': False,
                    }
            # The independently restored directory carries the authenticated
            # manifest for a later explicit, hash-checked activation. It never
            # affects the live workspace or SQLite database during restore.
            (stage / 'restore-manifest.json').write_text(
                json.dumps(manifest, sort_keys=True), encoding='utf-8')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stage), str(destination))
    return {'restored': True, 'destination': str(destination)}


def verify_isolated(destination):
    """Read-only manifest, file hash and SQLite integrity checks before activation.

    Cannot operate on active workspace or data. Original encrypted passphrase
    authentication was already performed during the isolated restore.
    """
    destination = Path(destination).resolve()
    if _within(Path(db.BASE).resolve(), destination) or _within(Path(db.DATA_DIR).resolve(), destination):
        raise ValueError('Cannot verify active clinical storage as an isolated recovery')
    marker = destination / 'restore-manifest.json'
    if not marker.is_file() or marker.is_symlink():
        raise ValueError('Isolated restore manifest missing')
    manifest = json.loads(marker.read_text(encoding='utf-8'))
    entries = manifest.get('files')
    if manifest.get('format') != 1 or not isinstance(entries, dict) or not 1 <= len(entries) <= MAX_FILES:
        raise ValueError('Invalid isolated recovery manifest')
    if 'data/hmr.db' not in entries:
        raise ValueError('Recovery database missing from manifest')
    total = 0
    for filename, detail in entries.items():
        if not isinstance(filename, str) or not isinstance(detail, dict) or not isinstance(detail.get('size'), int) or (
                not isinstance(detail.get('sha256'), str)) or not re.fullmatch('[a-f0-9]{64}', detail['sha256']):
            raise ValueError('Unsafe recovery entry')
        parts = Path(filename)
        if (parts.is_absolute() or len(parts.parts) < 2 or '..' in parts.parts or
                parts.parts[0] not in ('data', 'workspace') or not _safe_data_entry(parts.parts)):
            raise ValueError('Unsafe recovery file path')
        original = destination.joinpath(*parts.parts)
        if original.is_symlink() or not original.is_file() or not _within(destination, original.resolve()):
            raise ValueError('Recovery source missing or unsafe')
        if original.stat().st_size != detail['size']:
            raise ValueError('Recovery file length mismatch')
        total += detail['size']
        if total > MAX_UNPACKED:
            raise ValueError('Recovery dataset exceeds size limit')
        h = hashlib.sha256()
        with original.open('rb') as file:
            while chunk := file.read(CHUNK):
                h.update(chunk)
        if h.hexdigest() != detail['sha256']:
            raise ValueError('Recovery source hash mismatch')
    database = destination / 'data' / 'hmr.db'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Isolated restored SQLite failed integrity check')
    if not (destination / 'workspace').is_dir():
        raise ValueError('Recovered workspace missing')
    return {'verified': True, 'files': len(entries), 'bytes': total, 'patients': _patient_count(database),
            'template_files': sum(name.startswith('data/templates/') for name in entries)}


def _patient_count(database):
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        return conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
