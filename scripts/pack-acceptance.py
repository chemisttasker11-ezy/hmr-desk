"""Package the already-built app for isolated engineering checks, without running NSIS.

Contains application resources only. Never include an operator profile or workspace.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pack(root, output, provenance):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir() or root == output or root in output.parents:
        raise ValueError('Output must be outside the built app folder')
    for name in ('HMR Desk.exe', 'resources/app.asar', 'resources/engine/hmr-engine/hmr-engine.exe',
                 'resources/converter/libreoffice/program/soffice.exe'):
        if not (root / name).is_file(): raise ValueError('Missing packaged resource: ' + name)
    files = sorted(p for p in root.rglob('*') if p.is_file())
    if any(p.is_symlink() or root not in p.resolve().parents for p in files):
        raise ValueError('Unexpected link in packaged app')
    records = [{'path': p.relative_to(root).as_posix(), 'size_bytes': p.stat().st_size, 'sha256': sha(p)} for p in files]
    manifest = {'format': 1, 'product': 'HMR Desk', 'purpose': 'isolated synthetic engineering acceptance, not a clinical release',
                'signing': 'unsigned', 'pull_request_head_sha': provenance['pull_request_head_sha'],
                'checkout_merge_sha': provenance['checkout_merge_sha'], 'files': records}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        for path, item in zip(files, records): out.write(path, 'app/' + item['path'])
        out.writestr('app/acceptance-manifest.json', json.dumps(manifest, indent=2) + '\n')
    checksum = sha(output)
    output.with_suffix('.zip.sha256').write_text(checksum + '  ' + output.name + '\n', encoding='ascii')
    # Separate manifest allows provenance inspection before extraction; no user data in this archive.
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Unsigned engineering app archive:', output.name)
    print('PR head:', manifest['pull_request_head_sha'])
    print('Files:', len(records), 'ZIP SHA256:', checksum)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='desktop/dist/win-unpacked')
    parser.add_argument('--output', default='desktop/dist/hmr-isolated-acceptance.zip')
    parser.add_argument('--provenance', default='desktop/dist/installer-manifest.json')
    args = parser.parse_args()
    pack(args.root, args.output, json.loads(Path(args.provenance).read_text(encoding='utf-8-sig')))
