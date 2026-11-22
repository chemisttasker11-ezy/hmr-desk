"""Offline, read-only referral corpus census; NEVER submit a source or vault to GitHub.

Use from a private Windows terminal with an explicitly authorised folder:
    $env:HMR_CORPUS_SECRET = Read-Host "Private passphrase"
    python scripts/qa/referral_corpus_eval.py --root "D:\\Referrals" --output "D:\\Private-HMR-QA"

Outputs: an encrypted patient-linked manifest and an aggregate-only JSON. This is
an inventory/extraction coverage audit, NOT a clinical gold-standard evaluation.
Never auto-import the source into the application's patient database.
"""
import argparse
from collections import Counter
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

import fitz
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = Path(__file__).resolve().parents[2]
SUPPORTED = {'.pdf': 'pdf', '.tif': 'tiff', '.tiff': 'tiff', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'png'}
MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 150
PREFIX = b'HMR-CORPUS-V1\n'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _linked(path):
    for candidate in (Path(path), *Path(path).parents):
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
            return True
        if getattr(details, 'st_file_attributes', 0) & 0x400:
            return True
    return False


def _validate_paths(root, output):
    root, output = Path(root).absolute(), Path(output).absolute()
    if not root.is_dir() or _linked(root):
        raise ValueError('Source root unavailable or linked')
    if _linked(output):
        raise ValueError('Private output is linked')
    source, private, checkout = root.resolve(strict=True), output.resolve(strict=False), HERE.resolve()
    if source == private or source in private.parents or private in source.parents:
        raise ValueError('Private output must be outside the source directory tree')
    if checkout == private or checkout in private.parents:
        raise ValueError('Never write private manifests inside a Git checkout')
    return source, private


def _key(passphrase, salt):
    if not isinstance(passphrase, str) or len(passphrase) < 16:
        raise ValueError('Set a private passphrase of at least 16 characters in HMR_CORPUS_SECRET')
    return hashlib.scrypt(passphrase.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)


def encrypt(data, passphrase):
    salt, nonce = os.urandom(16), os.urandom(12)
    cipher = AESGCM(_key(passphrase, salt)).encrypt(
        nonce, json.dumps(data, ensure_ascii=False).encode('utf-8'), PREFIX)
    return PREFIX + salt + nonce + cipher


def decrypt(blob, passphrase):
    start = len(PREFIX)
    if not blob.startswith(PREFIX) or len(blob) < start + 44:
        raise ValueError('Invalid private manifest')
    return json.loads(AESGCM(_key(passphrase, blob[start:start+16])).decrypt(
        blob[start+16:start+28], blob[start+28:], PREFIX).decode('utf-8'))


def _atomic_file(path, content):
    if _linked(path):
        raise ValueError('Refusing linked output')
    fd, staged = tempfile.mkstemp(prefix='.hmr-qa-', dir=Path(path).parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def _read_regular(path, root):
    """No-follow best effort; native Windows handle race protection remains open."""
    if _linked(path) or root not in path.resolve().parents:
        raise ValueError('linked_or_outside')
    before = path.lstat()
    if before.st_size > MAX_BYTES:
        raise ValueError('too_large')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise ValueError('changed_during_read')
        with os.fdopen(fd, 'rb', closefd=False) as reader:
            data = reader.read(MAX_BYTES + 1)
    finally:
        os.close(fd)
    after = path.lstat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise ValueError('changed_during_read')
    if len(data) > MAX_BYTES:
        raise ValueError('too_large')
    return data


def _files(root):
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as directory:
            entries = sorted(directory, key=lambda item: item.name.casefold())
        for entry in entries:
            path = Path(entry.path)
            if path.suffix.lower() not in SUPPORTED and not entry.is_dir(follow_symlinks=False):
                continue
            if _linked(path):
                if path.suffix.lower() in SUPPORTED:
                    yield path, 'linked_skipped'
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in SUPPORTED:
                yield path, None


def _error_code(error):
    if isinstance(error, PermissionError):
        return 'permission_denied'
    if isinstance(error, FileNotFoundError):
        return 'file_disappeared'
    if isinstance(error, ValueError) and str(error) in {
            'too_large', 'changed_during_read', 'linked_or_outside'}:
        return str(error)
    if isinstance(error, ValueError) and 'page limit' in str(error):
        return 'page_limit'
    if isinstance(error, ValueError) and 'password protected' in str(error):
        return 'password_protected'
    return 'unreadable_or_unsupported'


def _inspect(data, suffix, intake, referral, page_audit, secret_key):
    kind = SUPPORTED[suffix]
    if kind == 'pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('invalid_pdf')
    with fitz.open(stream=data, filetype=kind) as doc:
        if doc.needs_pass:
            raise ValueError('password protected')
        if not 1 <= doc.page_count <= MAX_PAGES:
            raise ValueError('page limit exceeded')
        pages = [page.get_text('text')[:150000] for page in doc]
        layouts = [page_audit.inspect_page(page) for page in doc]
    raw = '\n'.join(pages)
    document_class, _, flags = intake.classify(raw)
    fields, more = intake.extract_fields('\n'.join(pages[:3])) if document_class == 'referral' else ({}, [])
    identity = (fields.get('name') or '').casefold().strip() + '\x00' + (fields.get('dob') or '')
    patient_hint = hmac.new(secret_key, identity.encode(), hashlib.sha256).hexdigest() if (
        fields.get('name') and fields.get('dob')) else None
    return {
        'status': 'readable', 'document_class': document_class,
        'layout_class': referral.layout(raw), 'page_count': len(pages),
        'pages': layouts, 'scan_pages': sum(p['native_characters'] < 25 for p in layouts),
        'mixed_pages': sum(p['needs_image_review'] for p in layouts),
        'possible_annotated_pages': sum(p['possible_interview_markup'] for p in layouts),
        'raster_handwriting_unassessed_pages': sum(p['raster_handwriting_unassessed'] for p in layouts),
        'fields_proposed_unverified': fields,
        'field_presence': sorted(key for key, value in fields.items() if value),
        'parser_flag_count': len(flags) + len(more),
        'patient_cluster_hint_unverified': patient_hint,
        'manual_review': document_class != 'referral' or any(
            p['needs_image_review'] or p['possible_interview_markup'] or p['native_characters'] < 25 for p in layouts),
    }


def _aggregate(records):
    states = Counter(item['status'] for item in records.values())
    classes = Counter(item.get('document_class', 'not_classified') for item in records.values())
    layouts = Counter(item.get('layout_class', 'not_classified') for item in records.values())
    digests = Counter(item.get('sha256') for item in records.values() if item.get('sha256'))
    times = sorted(item.get('duration_ms', 0) for item in records.values() if item['status'] == 'readable')
    return {
        'schema_version': 'referral-corpus-aggregate-v1',
        'candidate_files': len(records),
        'status_counts': dict(sorted(states.items())),
        'document_classes_unverified': dict(sorted(classes.items())),
        'layout_classes_unverified': dict(sorted(layouts.items())),
        'pages_processed': sum(item.get('page_count', 0) for item in records.values()),
        'native_text_insufficient_pages': sum(item.get('scan_pages', 0) for item in records.values()),
        'mixed_text_image_review_pages': sum(item.get('mixed_pages', 0) for item in records.values()),
        'possible_interview_annotation_pages': sum(item.get('possible_annotated_pages', 0) for item in records.values()),
        'raster_handwriting_not_characterised_pages': sum(item.get('raster_handwriting_unassessed_pages', 0) for item in records.values()),
        'manual_review_files': sum(bool(item.get('manual_review')) for item in records.values()),
        'exact_duplicate_extra_files': sum(max(count - 1, 0) for count in digests.values()),
        'patient_groups': 'NOT VERIFIED - parser identity is only a proposal',
        'real_file_gold_labels': 0,
        'field_accuracy': 'NOT MEASURED - independent pixel truth unavailable',
        'installed_windows_offline': 'NOT TESTED by this command',
        'median_document_ms': statistics.median(times) if times else None,
        'p95_document_ms': times[min(len(times)-1, int((len(times)-1)*0.95))] if times else None,
        'clinical_release': 'HOLD',
    }


def run(root, output, passphrase, *, resume=True):
    root, output = _validate_paths(root, output)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    vault = output / 'referral-corpus-private.enc'
    if _linked(vault):
        raise ValueError('Private manifest must not be a link')
    old = decrypt(vault.read_bytes(), passphrase) if resume and vault.is_file() else None
    if old and (old.get('schema_version') != 1 or old.get('root') != str(root)):
        raise ValueError('Private manifest belongs to another source')
    cache = old.get('records', {}) if old else {}
    intake = _module('private_intake', HERE / 'scripts' / 'intake' / 'intake.py')
    referral = _module('private_referral', HERE / 'HMR Desk' / 'engine' / 'referral.py')
    page_audit = _module('private_page_audit', HERE / 'HMR Desk' / 'engine' / 'referral_page_audit.py')
    secret_key = hashlib.sha256(passphrase.encode()).digest()
    records = {}
    for source, blocked in _files(root):
        relative = source.relative_to(root).as_posix()
        started = time.monotonic()
        if blocked:
            records[relative] = {'status': blocked}
            continue
        try:
            data = _read_regular(source, root)
            digest = hashlib.sha256(data).hexdigest()
            cached = cache.get(relative)
            result = dict(cached) if cached and cached.get('sha256') == digest and (
                cached.get('status') == 'readable') else _inspect(
                    data, source.suffix.lower(), intake, referral, page_audit, secret_key)
            result.update(sha256=digest, byte_size=len(data),
                          duration_ms=int((time.monotonic() - started)*1000))
        except Exception as error:
            result = {'status': _error_code(error),
                      'duration_ms': int((time.monotonic() - started)*1000)}
        records[relative] = result
        if len(records) % 25 == 0:
            _atomic_file(vault, encrypt({'schema_version': 1, 'root': str(root),
                                          'records': {**cache, **records}}, passphrase))
    _atomic_file(vault, encrypt({'schema_version': 1, 'root': str(root),
                                  'records': records}, passphrase))
    aggregate = _aggregate(records)
    _atomic_file(output / 'referral-corpus-AGGREGATE.json', (
        json.dumps(aggregate, indent=2, sort_keys=True) + '\n').encode())
    return aggregate


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private offline HMR referral census; never imports patients')
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args(argv)
    try:
        aggregate = run(args.root, args.output, os.environ.get('HMR_CORPUS_SECRET', ''),
                        resume=not args.no_resume)
    except Exception as error:
        # Avoid exception text: file paths may identify patients.
        print('Local census failed (' + type(error).__name__ +
              '); check access and passphrase privately.', file=sys.stderr)
        return 2
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
