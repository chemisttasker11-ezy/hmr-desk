"""Private suggestion inputs are loaded at runtime from the data folder and never packaged. Synthetic files only."""
import importlib.util
from pathlib import Path

import pytest

import db
import jobs

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('prepare_assets_priv', ROOT / 'scripts' / 'prepare-brainstorm-assets.py')
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


def test_references_dir_defaults_to_application_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    assert jobs.references_dir() == jobs.SKILL / 'references'


def test_private_runtime_folder_wins_only_when_it_holds_an_expected_file(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    private = tmp_path / jobs.PRIVATE_REFERENCES
    private.mkdir()
    (private / 'unrelated.txt').write_text('x')
    assert jobs.references_dir() == jobs.SKILL / 'references'
    (private / 'finding-library.md').write_text('## Synthetic\nplaceholder\n')
    assert jobs.references_dir() == private


@pytest.mark.parametrize('name', ['case-index.jsonl', 'finding-library.md', 'brainstorm-index.md', 'brainstorm-v2.pdf'])
def test_packaged_engine_with_a_private_file_is_rejected(tmp_path, name):
    engine = tmp_path / 'hmr-engine'
    (engine / '_internal' / 'assets' / 'references').mkdir(parents=True)
    (engine / '_internal' / 'assets' / 'references' / name).write_text('synthetic')
    with pytest.raises(packager.AssetPackagingError, match='private reference files must not be packaged'):
        packager.verify(tmp_path, engine)


def test_staging_refuses_when_private_files_sit_under_engine_assets(tmp_path):
    assets = tmp_path / packager.STAGED_RELATIVE / 'references'
    assets.mkdir(parents=True)
    (assets / 'case-index.jsonl').write_text('synthetic')
    with pytest.raises(packager.AssetPackagingError, match='private reference files'):
        packager.stage(tmp_path)
