"""Windows packaged engine must not require missing paid portal helper scripts."""
import agents
import api
import manual_medicine_names


def test_missing_browser_helper_code_does_not_prevent_manual_api_import(tmp_path):
    # Deterministic: an empty resource folder, not whatever helper files this machine happens to hold.
    import test_helper_modes
    loaded = test_helper_modes.fresh_external_helpers(tmp_path)
    assert loaded.mims is manual_medicine_names
    assert not loaded.MIMS_PATH.exists()
    assert loaded.claims_helper is None
    assert loaded.record is None


def test_offline_medicine_names_do_not_claim_therapeutic_equivalence():
    assert manual_medicine_names.ingredients('Example Drug 5 mg') != manual_medicine_names.ingredients('Example Drug 10 mg')
    assert manual_medicine_names.ingredients('Synthetic combination 2/5 mg') != manual_medicine_names.ingredients('Synthetic 5 mg')
    assert manual_medicine_names.ingredients('') == []


def test_new_installation_has_no_unlicensed_agent_or_external_dev_paths():
    data = agents.defaults()
    assert data == {'default': '', 'per_step': {}, 'agents': []}


def test_missing_helpers_are_reported_plainly_and_keep_the_existing_response_keys(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, 'BASE', str(tmp_path)); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path))
    # Absent helpers, whatever this machine holds.
    monkeypatch.setattr(api, 'MIMS_PATH', tmp_path / 'absent' / 'make-lists.py')
    monkeypatch.setattr(api, 'claims_helper', None); monkeypatch.setattr(api, 'record', None)
    conn = db.connect(str(tmp_path / 'h.db'))
    try:
        status, lists = api.handle(conn, 'GET', '/api/mims/lists', {}, None)
        assert status == 200 and lists['lists'] == [] and lists['helper_available'] is False and 'not installed' in lists['message']
        status, claims = api.handle(conn, 'GET', '/api/claims', {}, None)
        assert status == 200 and claims['claims'] == [] and claims['helper_available'] is False and 'not installed' in claims['message']
        monkeypatch.setattr(api, 'MIMS_PATH', __import__('pathlib').Path(__file__))
        assert 'message' not in api.handle(conn, 'GET', '/api/mims/lists', {}, None)[1]
    finally:
        conn.close()
