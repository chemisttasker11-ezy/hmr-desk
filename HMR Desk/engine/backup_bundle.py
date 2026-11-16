"""Authenticated, passphrase-encrypted, full-workspace HMR backup and isolated restore.

Format: HMRBKP1 + 16 byte scrypt salt + 12 byte AES-256-GCM nonce +
streamed ciphertext + 16 byte GCM tag. No key or password is written to disk.
"""
import hashlib
from contextlib import closing
import json
import os
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
    with tempfile.TemporaryDirectory(prefix='hmr-backup-') as directory:
        root = Path(directory)
        database = root / 'hmr.db'
        with closing(sqlite3.connect(database)) as snapshot:
            conn.backup(snapshot)
        zipped = root / 'snapshot.zip'
        index = {}
        paths = [('data/hmr.db', database)]
        for item in sorted(workspace.rglob('*')):
            if item.is_symlink():
                raise ValueError('Workspace contains a symlink; remove it before backup')
            if item.is_file():
                paths.append(('workspace/' + item.relative_to(workspace).as_posix(), item))
        # Capture the complete file set and metadata. If a parallel interview,
        # referral or report save changes anything, abort rather than publish
        # a deceptively successful but inconsistent multi-file archive.
        before = {name: (item.stat().st_size, item.stat().st_mtime_ns)
                  for name, item in paths[1:]}
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
            current = {('workspace/' + item.relative_to(workspace).as_posix()):
                       (item.stat().st_size, item.stat().st_mtime_ns)
                       for item in workspace.rglob('*') if item.is_file() and not item.is_symlink()}
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


def restore(source, destination, password):
    """Restore only to a NEW empty folder after authenticating and verifying every file."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Backup file not found')
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
        with tempfile.TemporaryDirectory(prefix='hmr-restore-') as directory:
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
                    if part.is_absolute() or '..' in part.parts or part.parts[0] not in ('data', 'workspace'):
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
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stage), str(destination))
    return {'restored': True, 'destination': str(destination)}
