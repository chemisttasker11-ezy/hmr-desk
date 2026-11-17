"""Dev-only synthetic seed: off by default, synthetic, and gets a patient to the report step."""
import contextlib
import json

import pytest

import db, dev_seed, engine_main, steps


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    (tmp_path / 'workspace').mkdir()
    (tmp_path / 'userdata').mkdir()
    monkeypatch.delenv('HMR_DB_KEY', raising=False)
    return str(tmp_path / 'userdata' / 'hmr.db')


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(dev_seed.ENV_FLAG, raising=False)
    with contextlib.closing(db.connect(_setup(tmp_path, monkeypatch))) as conn:
        with pytest.raises(dev_seed.DevToolsDisabled):
            dev_seed.seed_visit(conn)
        assert conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 0


@pytest.mark.parametrize('value', ['', '0', 'true', 'yes', ' 1'])
def test_only_exact_flag_enables(monkeypatch, value):
    monkeypatch.setenv(dev_seed.ENV_FLAG, value)
    assert not dev_seed.enabled()


def test_cli_refuses_without_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(dev_seed.ENV_FLAG, raising=False)
    code = engine_main.main(['--data-dir', str(tmp_path / 'd'), '--workspace', str(tmp_path / 'w'), '--dev-seed-visit'])
    assert code == 5
    assert not (tmp_path / 'd' / 'hmr.db').exists()


def test_seed_is_synthetic_and_ready_for_report(tmp_path, monkeypatch):
    monkeypatch.setenv(dev_seed.ENV_FLAG, '1')
    with contextlib.closing(db.connect(_setup(tmp_path, monkeypatch))) as conn:
        result = dev_seed.seed_visit(conn)
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (result['patient_id'],)).fetchone()
        assert patient['name'].startswith('DEV SEED') and patient['state'] == 'visited'
        assert steps.done('confirm_medicines', conn, patient) and steps.done('interactions', conn, patient)
        assert steps.ready('report_start', conn, patient)[0]
        second = dev_seed.seed_visit(conn)
        assert second['patient_id'] != result['patient_id'] and second['name'] != result['name']
        import report
        spec = report.start(conn, patient)
        assert spec['name'] == result['name']
        assert conn.execute("SELECT COUNT(*) FROM events WHERE type='dev_seed'").fetchone()[0] == 2
