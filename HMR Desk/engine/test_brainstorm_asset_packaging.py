"""Synthetic asset-packaging regression; no real clinical reference data."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import brainstorm_tables
import brainstorm_tables_lookup as lookup


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'prepare-brainstorm-assets.py'
SPEC = importlib.util.spec_from_file_location('prepare_brainstorm_assets', SCRIPT)
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


@pytest.fixture
def sample_repo(tmp_path):
    reference = tmp_path / 'references'
    reference.mkdir()
    entry = {'ordinal': 0, 'title': 'Synthetic Placeholder', 'page_start': 1,
             'page_end': 1, 'fields': [{'label': 'Issue to Consider',
                                       'text': 'Fictional example for testing only'}]}
    entry['content_sha256'] = brainstorm_tables._entry_digest(entry)
    structure = {'citation_version': brainstorm_tables.CITATION_VERSION,
                 'source': {'pdf_sha256': 'ab' * 32, 'page_count': 1,
                            'edition': 'Synthetic fixture'},
                 'entries': [entry]}
    raw = json.dumps(structure, ensure_ascii=False).encode('utf-8')
    (reference / packager.DATA_NAME).write_bytes(raw)
    return tmp_path, structure, raw


def _frozen_assets(root, folder='frozen-engine'):
    engine = root / folder
    shutil.copytree(root / packager.STAGED_RELATIVE, engine / '_internal' / 'assets')
    return engine, engine / '_internal' / 'assets'


def test_staging_produces_loader_compatible_manifest_and_exact_bytes(sample_repo, monkeypatch):
    root, structure, raw = sample_repo
    packager.stage(root)
    assets = root / packager.STAGED_RELATIVE
    assert (assets / packager.DATA_NAME).read_bytes() == raw
    assert json.loads((assets / packager.MANIFEST_NAME).read_text(encoding='utf-8')) == {
        'file': lookup.DATA_FILENAME, 'sha256': hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(lookup.app_paths, 'engine_assets', lambda: assets)
    lookup.reset_cache()
    try:
        assert lookup.load() == structure
        assert lookup.search('fictional')['results'][0]['title'] == 'Synthetic Placeholder'
    finally:
        lookup.reset_cache()
    frozen, _ = _frozen_assets(root)
    packager.verify(root, frozen)
    installed, _ = _frozen_assets(root, 'installed-desktop/resources/engine/hmr-engine')
    packager.verify(root, installed)


@pytest.mark.parametrize('damage', ['table-missing', 'manifest-missing', 'table-corrupt',
                                    'manifest-corrupt', 'self-consistent-but-not-source'])
def test_frozen_build_verification_fails_closed(sample_repo, damage):
    root, _, raw = sample_repo
    packager.stage(root)
    engine, assets = _frozen_assets(root)
    data_path = assets / packager.DATA_NAME
    manifest_path = assets / packager.MANIFEST_NAME
    if damage == 'table-missing':
        data_path.unlink()
    elif damage == 'manifest-missing':
        manifest_path.unlink()
    elif damage == 'table-corrupt':
        data_path.write_bytes(raw + b'altered')
    elif damage == 'manifest-corrupt':
        manifest_path.write_text('{broken', encoding='utf-8')
    else:
        changed = raw + b' '
        data_path.write_bytes(changed)
        manifest_path.write_text(json.dumps({'file': packager.DATA_NAME,
            'sha256': hashlib.sha256(changed).hexdigest()}), encoding='utf-8')
    with pytest.raises(packager.AssetPackagingError, match='missing|invalid|does not match'):
        packager.verify(root, engine)


def test_missing_tracked_reference_fails_without_creating_assets(tmp_path):
    with pytest.raises(packager.AssetPackagingError, match='Required tracked reference'):
        packager.stage(tmp_path)
    assert not (tmp_path / packager.STAGED_RELATIVE).exists()


def test_cli_stages_verifies_and_returns_nonzero_for_missing_packaged_assets(sample_repo):
    root, _, _ = sample_repo
    def call(*args):
        return subprocess.run([sys.executable, str(SCRIPT), '--repo-root', str(root), *args],
                              capture_output=True, text=True, check=False)
    stage = call('stage')
    assert stage.returncode == 0, stage.stderr
    engine, assets = _frozen_assets(root)
    passed = call('verify', str(engine))
    assert passed.returncode == 0, passed.stderr
    (assets / packager.MANIFEST_NAME).unlink()
    failed = call('verify', str(engine))
    assert failed.returncode != 0
    assert 'FAIL: required Brainstorm reference assets:' in failed.stderr
    assert 'manifest' in failed.stderr


def test_local_and_ci_call_same_stage_and_verify_script_in_order():
    ps = (ROOT / 'scripts' / 'build-windows.ps1').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'm2-standalone.yml').read_text(encoding='utf-8')
    script = 'prepare-brainstorm-assets.py'
    assert ps.count(script) == 3
    assert workflow.count(script) == 4  # stage, engine, desktop, installed
    assert ps.index("'Brainstorm asset staging'") < ps.index("'Engine packaging'")
    assert ps.index("'Frozen engine Brainstorm asset verification'") > ps.index("'Engine packaging'")
    assert ps.index("'Packaged desktop Brainstorm asset verification'") > ps.index("'NSIS build'")
    assert workflow.index(f'python scripts/{script} stage') < workflow.index('python -m PyInstaller')
    assert workflow.index(f'python scripts/{script} verify "HMR Desk/engine/dist/hmr-engine"') > workflow.index('python -m PyInstaller')
    assert workflow.index(f'python scripts/{script} verify "desktop/dist/win-unpacked/resources/engine/hmr-engine"') > workflow.index('npm run dist')
    # The private helper scripts remain optional. This change does not add them.
    assert 'Optional helper not found' in ps
