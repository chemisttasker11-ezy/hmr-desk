"""Windows packaged engine must not require missing paid portal helper scripts."""
import agents
import api
import manual_medicine_names


def test_missing_browser_helper_code_does_not_prevent_manual_api_import():
    assert api.mims is manual_medicine_names
    assert not api.MIMS_PATH.exists()
    assert api.claims_helper is None
    assert api.record is None


def test_offline_medicine_names_do_not_claim_therapeutic_equivalence():
    assert manual_medicine_names.ingredients('Example Drug 5 mg') != manual_medicine_names.ingredients('Example Drug 10 mg')
    assert manual_medicine_names.ingredients('Synthetic combination 2/5 mg') != manual_medicine_names.ingredients('Synthetic 5 mg')
    assert manual_medicine_names.ingredients('') == []


def test_new_installation_has_no_unlicensed_agent_or_external_dev_paths():
    data = agents.defaults()
    assert data == {'default': '', 'per_step': {}, 'agents': []}
