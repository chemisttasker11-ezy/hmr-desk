"""Deterministic coverage of the optional portal helper in both modes, with synthetic files and a synthetic stand-in
(wiring and contract only; it is not the licensed helper). Nothing here depends on whether a helper is installed on the machine.

Contract: stopped/taking reconciliation uses the application's whole-name identity in BOTH modes, so a different strength is a
different record and a helper never changes which medicines are treated as stopped. The helper's ingredient names are used
only to build the eMIMS list and to check that a confirmed medicine was covered, after spacing is normalised."""
import importlib.util
import re
import types
from pathlib import Path

import app_paths
import external_helpers
import manual_medicine_names
import medicine_review

HELPER_SOURCE = '''
import re
SKIP = re.compile(r'^(nil|none)', re.I)
ALIASES = {}
def ingredients(text):
    s = re.split(r'\\s\\d', ' ' + text.strip())[0]
    s = re.sub(r'\\b(tablets?|capsules?)\\b', '', s, flags=re.I)
    return [s.strip().lower()] if s.strip() else []
def brand(text): return None
def allergies(text): return []
lists = []
raise SystemExit('the loader must stop before this line')
'''


def fresh_external_helpers(root):
    spec = importlib.util.spec_from_file_location('external_helpers_fresh', external_helpers.__file__)
    module = importlib.util.module_from_spec(spec)
    original = app_paths.resource_root
    app_paths.resource_root = lambda: root
    try:
        spec.loader.exec_module(module)
    finally:
        app_paths.resource_root = original
    return module


def test_without_helper_files_the_application_uses_its_own_names(tmp_path):
    loaded = fresh_external_helpers(tmp_path)
    assert loaded.mims is manual_medicine_names
    assert loaded.claims_helper is None and loaded.record is None
    assert not loaded.MIMS_PATH.is_file()


def test_helper_file_is_loaded_up_to_its_data_assignment_only(tmp_path):
    folder = tmp_path / 'MIMS Interaction Helper'; folder.mkdir()
    (folder / 'make-lists.py').write_text(HELPER_SOURCE, encoding='utf-8')
    loaded = fresh_external_helpers(tmp_path)
    assert loaded.MIMS_PATH.is_file() and loaded.mims is not manual_medicine_names
    assert loaded.mims.ingredients('Synthmed A 10 mg tablet') == ['synthmed a']


def helper_like(monkeypatch):
    module = types.ModuleType('helper_like')
    module.ingredients = lambda text: [re.split(r'\s\d', ' ' + text.strip())[0].strip().lower()] if text.strip() else []
    module.SKIP = re.compile(r'^nil', re.I); module.ALIASES = {}; module.brand = lambda t: None
    monkeypatch.setattr(external_helpers, 'mims', module)
    return module


def usage(name, status):
    return {'name': name, 'status': status, 'detail': '', 'source': 'Referral medicine', 'directions': ['', '']}


def test_different_strength_without_a_helper_is_a_different_record(monkeypatch):
    monkeypatch.setattr(external_helpers, 'mims', manual_medicine_names)
    stopped = usage('Synthmed A 10 mg tablet', 'not_using'); taking = usage('Synthmed A 20 mg tablet', 'taking')
    meds = [['Synthmed A 20 mg tablet', '']]
    assert external_helpers.ingredient_names('Synthmed A 10 mg tablet') != external_helpers.ingredient_names('Synthmed A 20 mg tablet')
    assert medicine_review.valid_alternatives(meds, medicine_review.relevant_usage([stopped, taking], meds), [None]) is True


def test_different_strength_with_a_dose_stripping_helper_needs_the_pharmacist_to_resolve_it(monkeypatch):
    helper_like(monkeypatch)
    stopped = usage('Synthmed A 10 mg tablet', 'not_using'); taking = usage('Synthmed A 20 mg tablet', 'taking')
    meds = [['Synthmed A 20 mg tablet', '']]
    relevant = medicine_review.relevant_usage([stopped, taking], meds)
    assert relevant == [stopped, taking]
    assert medicine_review.valid_alternatives(meds, relevant, [None]) is False          # nothing chosen: held
    assert medicine_review.valid_alternatives(meds, relevant, [taking]) is True         # explicit choice of the taking record
    assert medicine_review.valid_alternatives(meds, relevant, [stopped]) is False       # the stopped record cannot be chosen


def test_same_name_as_a_stopped_medicine_needs_resolution_and_no_choice_clears_it_in_both_modes(monkeypatch):
    stopped = usage('Synthmed A 10 mg tablet', 'not_using')
    taking = usage('synthmed  a 10 mg   TABLET', 'taking')
    meds = [['synthmed  a 10 mg   TABLET', '']]
    for mode in ('absent', 'helper'):
        if mode == 'helper': helper_like(monkeypatch)
        relevant = medicine_review.relevant_usage([stopped, taking], meds)
        assert medicine_review.valid_alternatives(meds, relevant, [None]) is False, mode
        assert medicine_review.valid_alternatives(meds, relevant, [taking]) is False, mode


def test_helper_names_have_spacing_normalised(monkeypatch):
    module = helper_like(monkeypatch)
    module.ingredients = lambda text: ['synthmed  a']
    assert external_helpers.ingredient_names('Synthmed A 10 mg') == ['synthmed a']
