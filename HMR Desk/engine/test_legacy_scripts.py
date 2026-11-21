"""Run the older script-style engine tests under pytest.

These files assert at import time and define no test functions, so `pytest file.py` collected
nothing ("no tests ran") and CI never executed them. Running each as a script makes an assertion
failure fail a real test. Each script creates its own temporary data directory.
These scripts are the complete older test files. Each runs in its own interpreter through the test below, so a
failure in any of them fails pytest. They also run to their end, including the later sign-off checks: where the
sign-off gate needs evidence, `legacy_signoff_support.approve()` builds real hash-bound Word and PDF evidence and the
gate runs unchanged. The licensed MIMS list helper and the PPA claim helper are not in the repository, so the scripts
use the wiring doubles `legacy_mims_double` and `legacy_ppa_double`; they prove engine wiring only, NOT the real
helpers' parsing.
Known remaining limits:
- test_api: the tail after the retired BUILD_SCRIPT report job is stale against the standalone renderer and is not run
  (set HMR_RUN_STALE_API_TAIL=1 to run it while repairing it). The standalone renderer has its own tests.
- test_referral_entry (pytest): 1 case needs a scripts/intake folder in the default data directory.
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
           'test_api.py', 'test_actions.py', 'test_manual_workflow.py', 'test_independent_repairs.py']
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
