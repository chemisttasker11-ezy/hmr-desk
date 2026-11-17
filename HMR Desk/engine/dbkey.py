"""Database key handling for the encrypted HMR Desk database (SQLCipher).

The 32 byte key lives in `hmr.key` beside the database. On Windows it is wrapped with DPAPI, so it only
opens for the same Windows user. A recovery key (the same key as grouped Base32 text with a checksum) is
shown once at setup so a backup restored on a new PC can still be opened.

Everything about key storage is in this module so a first-launch guard can be added later
(see desktop/src/draft-vault.js) without touching the database code.
"""
import base64, binascii, hashlib, json, os, secrets, sys

KEY_FILE = 'hmr.key'
PENDING_FILE = 'hmr.key.pending'
ENV_KEY = 'HMR_DB_KEY'
_ENTROPY = b'HMR Desk database key v1'
_PLAIN_HEADER = b'SQLite format 3\x00'


class KeyUnavailable(Exception):
    """The database is encrypted and no working key is available on this PC."""


class RecoveryKeyError(ValueError):
    pass


# --- DPAPI ----------------------------------------------------------------
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def make(raw):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf
    src, keep1 = make(data)
    ent, keep2 = make(_ENTROPY)
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise KeyUnavailable('Windows could not unlock the database key for this user.')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _wrap(key):
    if sys.platform == 'win32':
        return 'dpapi', _dpapi(key, True)
    return 'file', key  # development and Linux CI only; the product is Windows only


def _unwrap(protection, blob):
    if protection == 'dpapi':
        return _dpapi(blob, False)
    if protection == 'file':
        return blob
    raise KeyUnavailable('Unknown key protection.')


# --- paths and files --------------------------------------------------------
def _dir(path):
    folder = os.path.dirname(os.path.abspath(str(path)))
    if os.path.basename(folder) == '.migration-snapshots':  # snapshots share the database's key
        folder = os.path.dirname(folder)
    return folder


def key_path(path):
    return os.path.join(_dir(path), KEY_FILE)


def pending_path(path):
    return os.path.join(_dir(path), PENDING_FILE)


def _env_key():
    raw = os.environ.get(ENV_KEY, '').strip()
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        raise KeyUnavailable('%s must be 64 hex characters.' % ENV_KEY)
    if len(key) != 32:
        raise KeyUnavailable('%s must be 64 hex characters.' % ENV_KEY)
    return key


def _write_private(path, data):
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _store(path, key, recovery_pending):
    protection, blob = _wrap(key)
    doc = {'v': 1, 'protection': protection, 'key': base64.b64encode(blob).decode(),
           'recovery_pending': bool(recovery_pending)}
    _write_private(path, json.dumps(doc).encode())


def _load(path):
    """Returns (key, doc) from a key file."""
    try:
        with open(path, 'rb') as handle:
            doc = json.loads(handle.read().decode())
        key = _unwrap(doc['protection'], base64.b64decode(doc['key']))
    except KeyUnavailable:
        raise
    except Exception:
        raise KeyUnavailable('The database key file could not be read.')
    if len(key) != 32:
        raise KeyUnavailable('The database key file is damaged.')
    return key, doc


def has_key_file(path):
    return os.path.exists(key_path(path))


def candidates(path):
    """Keys worth trying, newest first (a rotation may have been interrupted)."""
    env = _env_key()
    if env:
        return [env]
    found = []
    for target in (pending_path(path), key_path(path)):
        if os.path.exists(target):
            try:
                key = _load(target)[0]
            except KeyUnavailable:
                if target == key_path(path):
                    raise
                continue
            if key not in found:
                found.append(key)
    return found


def create_key(path):
    env = _env_key()
    if env:
        return env
    key = secrets.token_bytes(32)
    _store(key_path(path), key, recovery_pending=True)
    return key


# --- file kind --------------------------------------------------------------
def is_plain_file(path):
    try:
        with open(path, 'rb') as handle:
            return handle.read(16) == _PLAIN_HEADER
    except OSError:
        return False


def file_kind(path):
    """'missing' (no file or empty), 'plain' (unencrypted SQLite) or 'encrypted'."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 'missing'
    if size == 0:
        return 'missing'
    return 'plain' if is_plain_file(path) else 'encrypted'


# --- recovery key -----------------------------------------------------------
def _check(key):
    return hashlib.sha256(b'hmr-recovery' + key).digest()[:2]


def recovery_text(key):
    raw = base64.b32encode(key + _check(key)).decode().rstrip('=')
    return '-'.join(raw[i:i + 5] for i in range(0, len(raw), 5))


def parse_recovery(text):
    cleaned = ''.join(ch for ch in str(text).upper() if ch.isalnum())
    cleaned = cleaned.replace('0', 'O').replace('1', 'I').replace('8', 'B')
    try:
        raw = base64.b32decode(cleaned + '=' * (-len(cleaned) % 8))
    except (binascii.Error, ValueError):
        raise RecoveryKeyError('That recovery key is not valid. Check it and try again.')
    if len(raw) != 34 or raw[32:] != _check(raw[:32]):
        raise RecoveryKeyError('That recovery key is not valid. Check it and try again.')
    return raw[:32]


def _current(path):
    cands = candidates(path)
    if not cands:
        raise KeyUnavailable('No database key is available on this PC.')
    return cands[0]


def status(path):
    env = _env_key()
    info = {'database': file_kind(path), 'key_file': has_key_file(path), 'protection': 'none',
            'recovery_pending': False}
    if env:
        info.update(protection='env', key_file=False)
        return info
    if info['key_file']:
        try:
            _, doc = _load(key_path(path))
            info['protection'] = doc.get('protection', 'unknown')
            info['recovery_pending'] = bool(doc.get('recovery_pending'))
        except KeyUnavailable:
            info['protection'] = 'unreadable'
    info['locked'] = info['database'] == 'encrypted' and info['protection'] in ('none', 'unreadable')
    return info


def reveal_recovery_key(path):
    """Recovery key text, only until the user confirms they have stored it."""
    if not has_key_file(path):
        raise KeyUnavailable('No database key on this PC.')
    key, doc = _load(key_path(path))
    if not doc.get('recovery_pending'):
        raise RecoveryKeyError('The recovery key was already confirmed. Make a new one to see it again.')
    return recovery_text(key)


def acknowledge_recovery_key(path):
    key, doc = _load(key_path(path))
    if doc.get('recovery_pending'):
        _store(key_path(path), key, recovery_pending=False)
    return status(path)


def install_recovery_key(path, text, opens):
    """Use a typed recovery key on a new PC: prove it opens the database, then seal it for this user."""
    key = parse_recovery(text)
    if not opens(key):
        raise RecoveryKeyError('That recovery key does not open this database.')
    if not _env_key():
        _store(key_path(path), key, recovery_pending=False)
    return status(path)


# --- rotation ---------------------------------------------------------------
def begin_rotation(path):
    """Write the new key beside the old one before the database is re-keyed. Returns the new key."""
    if _env_key():
        raise KeyUnavailable('The key is set by %s and cannot be rotated here.' % ENV_KEY)
    key = secrets.token_bytes(32)
    _store(pending_path(path), key, recovery_pending=True)
    return key


def finish_rotation(path):
    os.replace(pending_path(path), key_path(path))


def abort_rotation(path):
    try:
        os.unlink(pending_path(path))
    except OSError:
        pass


def settle_pending(path, opened_with):
    """After connecting: finish or drop a rotation that was interrupted."""
    if not os.path.exists(pending_path(path)):
        return
    try:
        new_key = _load(pending_path(path))[0]
    except KeyUnavailable:
        abort_rotation(path)
        return
    if opened_with == new_key:
        finish_rotation(path)
    else:
        abort_rotation(path)
