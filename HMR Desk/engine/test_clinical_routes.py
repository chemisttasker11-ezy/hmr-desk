"""Regression for previously double-escaped clinical routes in actual API dispatch."""
import db
import api
import jobs


def test_pathology_and_reconciliation_routes_match_numeric_patient_id(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    folder = root / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(root))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                           ('synthetic example', 'Synthetic Example', 'TO SORT/Synthetic')).lastrowid
    status, pathology = api.handle(conn, 'GET', f'/api/patients/{pid}/pathology-records', {}, None)
    assert status == 200 and pathology['records'] == []
    status, versions = api.handle(conn, 'GET', f'/api/patients/{pid}/report-versions', {}, None)
    assert status == 200 and versions['versions'] == []
    status, reconciliation = api.handle(conn, 'GET', f'/api/patients/{pid}/reconciliation', {}, None)
    assert status == 200 and 'flags' in reconciliation
    conn.close()


def test_health_uses_actual_schema_version_and_refuses_unapproved_template(tmp_path, monkeypatch):
    monkeypatch.setattr(api.app_paths, 'engine_assets', lambda: tmp_path)
    import template_report_builder
    monkeypatch.setattr(template_report_builder, 'active_template_root', lambda: tmp_path)
    conn = db.connect(str(tmp_path / 'check.db'))
    status, health = api.handle(conn, 'GET', '/api/health', {}, None)
    assert status == 200
    assert health['schema_version'] == db.SCHEMA_VERSION
    assert health['capabilities']['approved_template_available'] is False
    conn.close()
