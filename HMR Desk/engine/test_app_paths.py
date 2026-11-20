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


def test_database_override_alone_keeps_log_token_and_outputs_beside_it(tmp_path, monkeypatch):
    # HMR_DB without HMR_DATA_DIR used to leave engine.log, api_token and the rest in the user's default folder.
    monkeypatch.delenv('HMR_DATA_DIR', raising=False)
    monkeypatch.delenv('HMR_WORKSPACE', raising=False)
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'scratch' / 'hmr.db'))
    assert app_paths.data_root() == (tmp_path / 'scratch').resolve()
    assert app_paths.workspace_root() == (tmp_path / 'scratch' / 'workspace').resolve()


def test_explicit_data_dir_wins_over_database_override_and_default_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'scratch' / 'hmr.db'))
    monkeypatch.setenv('HMR_DATA_DIR', str(tmp_path / 'explicit'))
    assert app_paths.data_root() == (tmp_path / 'explicit').resolve()
    monkeypatch.delenv('HMR_DATA_DIR')
    monkeypatch.delenv('HMR_DB')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'home'))
    assert app_paths.data_root() == (tmp_path / 'home' / 'HMR-Desk-data').resolve()


def test_engine_with_database_and_workspace_overrides_touches_nothing_in_the_default_home(tmp_path):
    import subprocess, sys
    home = tmp_path / 'home'; home.mkdir()
    scratch = tmp_path / 'scratch'; scratch.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ('HMR_DATA_DIR',)}
    env.update(HOME=str(home), USERPROFILE=str(home), HMR_DB=str(scratch / 'hmr.db'), HMR_WORKSPACE=str(scratch / 'ws'))
    code = ("import db; print(db.DATA_DIR); print(db.BASE); print(db.db_path())")
    out = subprocess.run([sys.executable, '-c', code], cwd=os.path.dirname(os.path.abspath(__file__)), env=env,
                         capture_output=True, text=True, timeout=60, check=True).stdout.split('\n')
    assert Path(out[0]).resolve() == scratch.resolve()
    assert Path(out[1]).resolve() == (scratch / 'ws').resolve()
    assert Path(out[2]).resolve() == (scratch / 'hmr.db').resolve()
    assert not list(home.iterdir())
