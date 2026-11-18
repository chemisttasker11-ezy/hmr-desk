"""Run the older script-style engine tests under pytest.

These files assert at import time and define no test functions, so `pytest file.py` collected
nothing ("no tests ran") and CI never executed them. Running each as a script makes an assertion
failure fail a real test. Each script creates its own temporary data directory.
Not included (each fails when run as a script in an isolated data dir on Linux; causes found so far):
- test_messaging, test_scenarios, test_replies, test_referral_fields, test_revision4: they assume a default
  pharmacist name ("Consultant Pharmacist"); the product default is now empty and messages need name and phone.
  Setting both makes test_messaging fail on a literal (the signature now also carries the phone), so the
  expected literals need a deliberate update, not a wrapper. test_autopilot only needed the name and is included.
- test_independent_repairs: steps.built(conn, p) call is stale and the assertion still fails after fixing it.
- test_actions: stale steps.exists call (fixed), then api.claim_list returns [] in this environment.
- test_importer: needs an appointment plan file in the data directory. test_interview: expects an
  interview.json file on disk, but interview records now live in the records store.
- test_api, test_manual_workflow, test_planner: assertion or key mismatch, not yet diagnosed.
- test_referral_entry (pytest): 1 case fails, it needs a scripts/intake folder in the default data directory.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = ['test_lifecycle.py', 'test_days.py', 'test_consent_sign.py', 'test_mims_binding.py', 'test_proda_sms.py',
           'test_engine.py', 'test_referral.py', 'test_run_catalog.py', 'test_suggest.py', 'test_timeline.py',
           'test_tracking_followon.py', 'test_autopilot.py']
# Each script runs in its own interpreter, so module state, environment variables and temp data
# never leak between scripts or into the pytest session. A non-zero exit (any assertion) fails.
BOOT = ("import runpy, sys, types\n"
        "if sys.platform != 'win32': sys.modules.setdefault('msvcrt', types.ModuleType('msvcrt'))\n"
        "sys.path.insert(0, '.')\n"
        "runpy.run_path(sys.argv[1], run_name='__main__')\n")


@pytest.mark.parametrize('script', SCRIPTS)
def test_legacy_script_passes(script, tmp_path):
    env = {**os.environ, 'LOCALAPPDATA': str(tmp_path), 'APPDATA': str(tmp_path), 'USERPROFILE': str(tmp_path),
           'HOME': str(tmp_path), 'HMR_DB': str(tmp_path / 'isolated.db')}
    done = subprocess.run([sys.executable, '-c', BOOT, str(HERE / script)], cwd=str(HERE), env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]


def test_script_runner_propagates_a_failure(tmp_path):
    bad = tmp_path / 'bad_script.py'
    bad.write_text('assert 1 == 2, "deliberate"\n')
    done = subprocess.run([sys.executable, '-c', BOOT, str(bad)], cwd=str(HERE), capture_output=True, text=True)
    assert done.returncode != 0 and 'deliberate' in done.stderr
