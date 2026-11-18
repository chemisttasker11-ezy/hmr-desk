"""Run the older script-style engine tests under pytest.

These files assert at import time and define no test functions, so `pytest file.py` collected
nothing ("no tests ran") and CI never executed them. Running each as a script makes an assertion
failure fail a real test. Each script creates its own temporary data directory.
Not included (each fails when run as a script in an isolated data dir on Linux; causes found so far):
- test_actions: needs the optional PPA claim helper (PPA Claim Helper/make-claims.py), which is not in the repository,
  so api.claim_list returns [] by design ("PPA integration unavailable").
- test_api, test_manual_workflow, test_independent_repairs: later sections call act('signed_off') and act('report_sent'),
  which now need an explicit pharmacist review, a built owner-approved Word and PDF pair and its checksum
  (report_auth.check_approval). The scripts cannot reach their later checks without that evidence; test_report_auth
  covers the gate itself. Their pre-sign-off parts run as test_*_presignoff.py (copies of the original text up to the
  first signed_off call, with fixtures updated); the sign-off and later checks in the full scripts are NOT run and are
  not counted as passing.
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
           'test_tracking_followon.py', 'test_autopilot.py', 'test_referral_fields.py',
           'test_messaging.py', 'test_replies.py', 'test_scenarios.py', 'test_revision4.py',
           'test_planner.py', 'test_interview.py', 'test_importer.py',
           'test_api_presignoff.py', 'test_manual_workflow_presignoff.py', 'test_independent_repairs_presignoff.py']
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
    out = done.stdout + done.stderr
    # Keep the start of the output (the first traceback, usually the real assertion) and the end (teardown noise).
    shown = out if len(out) <= 6000 else out[:3500] + '\n...[%d characters omitted]...\n' % (len(out) - 5500) + out[-2000:]
    assert done.returncode == 0, shown


def test_script_runner_propagates_a_failure(tmp_path):
    bad = tmp_path / 'bad_script.py'
    bad.write_text('assert 1 == 2, "deliberate"\n')
    done = subprocess.run([sys.executable, '-c', BOOT, str(bad)], cwd=str(HERE), capture_output=True, text=True)
    assert done.returncode != 0 and 'deliberate' in done.stderr
