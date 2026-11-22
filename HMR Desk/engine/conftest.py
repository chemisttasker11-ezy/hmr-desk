"""Keep the script-style legacy files out of in-process collection only.

They assert and change global state at import, which corrupted unrelated tests when pytest imported them in the same
process (plain `pytest` gave 2 failures and 5 collection errors). Every one of them still runs, to its end, in its own
interpreter through test_legacy_scripts.py, so none is excluded from validation.
"""
import test_legacy_scripts

collect_ignore = list(test_legacy_scripts.SCRIPTS)


import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_legacy_signoff_overrides():
    """Restore legacy test overrides only if a test actually loaded the helper.

    Importing it from teardown itself needlessly loads the legacy inbox/SMS stack,
    including Windows-only msvcrt, on Linux privacy runners. A loaded helper is
    still restored after every test, so process-wide overrides cannot leak.
    """
    yield
    helper = sys.modules.get('legacy_signoff_support')
    if helper is not None:
        helper.restore()
