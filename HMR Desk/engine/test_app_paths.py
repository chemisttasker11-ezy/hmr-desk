"""Synthetic filesystem regression tests for portable runtime paths."""
import os
from pathlib import Path
import app_paths
import engine_main


def test_writable_path_is_distinct_from_installed_assets(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DATA_DIR', str(tmp_path / 'user data'))
    monkeypatch.setenv('HMR_WORKSPACE', str(tmp_path / 'case workspace'))
    assert app_paths.ensure_writable(app_paths.data_root()).is_dir()
    assert app_paths.ensure_writable(app_paths.workspace_root()).is_dir()
    assert app_paths.workspace_root() != app_paths.resource_root()
    assert not list(tmp_path.rglob('.hmr-write-check-*'))


def test_engine_version_without_starting_server(capsys):
    assert engine_main.main(['--version']) == 0
    assert 'hmr-engine' in capsys.readouterr().out
