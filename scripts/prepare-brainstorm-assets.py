#!/usr/bin/env python3
"""Stage and verify the existing tracked Brainstorm extraction in Windows builds.

Local and CI builders call the same stdlib-only command. This only packages
existing bytes and a SHA-256 manifest; it does not interpret clinical content.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_NAME = 'brainstorm-mmr-v2.0-tables.json'
MANIFEST_NAME = 'brainstorm-tables-manifest.json'
REFERENCE_RELATIVE = Path('references') / DATA_NAME
STAGED_RELATIVE = Path('HMR Desk') / 'engine' / 'assets'


class AssetPackagingError(RuntimeError):
    """A required, checked reference asset is absent or inconsistent."""


def _reference_hash(repo_root):
    source = repo_root / REFERENCE_RELATIVE
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as exc:
        raise AssetPackagingError(f'Required tracked reference is missing or unreadable: {source} ({exc})') from exc
    return source, digest


def _verify_directory(repo_root, assets_dir, description):
    _, expected = _reference_hash(repo_root)
    table = assets_dir / DATA_NAME
    manifest_file = assets_dir / MANIFEST_NAME
    try:
        packaged_digest = hashlib.sha256(table.read_bytes()).hexdigest()
    except OSError as exc:
        raise AssetPackagingError(f'{description}: required table data missing or unreadable: {table} ({exc})') from exc
    try:
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssetPackagingError(f'{description}: required checksum manifest missing or invalid: {manifest_file} ({exc})') from exc
    if not isinstance(manifest, dict) or manifest.get('file') != DATA_NAME:
        raise AssetPackagingError(f'{description}: manifest must identify {DATA_NAME}')
    if packaged_digest != expected:
        raise AssetPackagingError(f'{description}: table data SHA-256 does not match tracked reference')
    if manifest.get('sha256') != expected:
        raise AssetPackagingError(f'{description}: manifest SHA-256 does not match tracked reference')
    return expected


def stage(repo_root):
    source, expected = _reference_hash(repo_root)
    assets_dir = repo_root / STAGED_RELATIVE
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / DATA_NAME).write_bytes(source.read_bytes())
        # Exact file/sha256 keys are consumed by brainstorm_tables_lookup.load().
        manifest = {'file': DATA_NAME, 'sha256': expected}
        (assets_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n', encoding='ascii'
        )
    except OSError as exc:
        raise AssetPackagingError(f'Could not stage required Brainstorm assets: {exc}') from exc
    _verify_directory(repo_root, assets_dir, 'Staged engine assets')
    print(f'PASS: staged tracked Brainstorm tables and loader-compatible manifest (SHA-256 {expected})')


def verify(repo_root, engine_dir):
    """Check a frozen PyInstaller onedir engine or its Electron-installed copy."""
    engine_dir = Path(engine_dir)
    if not engine_dir.is_absolute():
        engine_dir = repo_root / engine_dir
    assets_dir = engine_dir / '_internal' / 'assets'
    expected = _verify_directory(repo_root, assets_dir, f'Packaged engine at {engine_dir}')
    print(f'PASS: packaged Brainstorm tables and manifest match tracked source (SHA-256 {expected})')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=REPO_ROOT,
                        help='Repository root (defaults to this script\'s parent repository)')
    subcommands = parser.add_subparsers(dest='command', required=True)
    subcommands.add_parser('stage', help='Stage the tracked table bytes and generate checksum manifest')
    verify_command = subcommands.add_parser('verify', help='Verify assets inside a built frozen engine folder')
    verify_command.add_argument('engine_directory', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'stage':
            stage(args.repo_root.resolve())
        else:
            verify(args.repo_root.resolve(), args.engine_directory)
    except AssetPackagingError as exc:
        print(f'FAIL: required Brainstorm reference assets: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
