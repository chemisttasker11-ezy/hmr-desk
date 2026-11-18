"""Run the older script-style engine tests under pytest.

These files assert at import time and define no test functions, so `pytest file.py` collected
nothing ("no tests ran") and CI never executed them. Running each as a script makes an assertion
failure fail a real test. Each script creates its own temporary data directory.
Not included yet (error or fail on a Linux checkout; each needs diagnosis, not a wrapper):
test_actions (stale call fixed, then claim_list is empty here), test_api, test_autopilot, test_importer,
test_independent_repairs, test_interview, test_manual_workflow, test_messaging, test_planner,
test_referral_fields, test_replies, test_revision4, test_scenarios, and one case in test_referral_entry.
"""
import runpy
from pathlib import Path

import pytest

import db

HERE = Path(__file__).resolve().parent
SCRIPTS = ['test_lifecycle.py', 'test_days.py', 'test_consent_sign.py', 'test_mims_binding.py', 'test_proda_sms.py',
           'test_engine.py', 'test_referral.py', 'test_run_catalog.py', 'test_suggest.py', 'test_timeline.py',
           'test_tracking_followon.py']


@pytest.mark.parametrize('script', SCRIPTS)
def test_legacy_script_passes(script, monkeypatch):
    saved = db.BASE
    try:
        runpy.run_path(str(HERE / script), run_name='legacy_' + script[:-3])
    finally:
        db.BASE = saved
