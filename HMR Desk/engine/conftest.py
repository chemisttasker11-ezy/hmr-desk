"""Keep the script-style legacy files out of in-process collection only.

They assert and change global state at import, which corrupted unrelated tests when pytest imported them in the same
process (plain `pytest` gave 2 failures and 5 collection errors). Every one of them still runs, to its end, in its own
interpreter through test_legacy_scripts.py, so none is excluded from validation.
"""
import test_legacy_scripts

collect_ignore = list(test_legacy_scripts.SCRIPTS)


import pytest


@pytest.fixture(autouse=True)
def _restore_legacy_signoff_overrides():
    """legacy_signoff_support.approve() swaps jobs.APP_ASSETS and the approved-template root for the whole process.
    Undo that after every test so it cannot leak into later modules (e.g. the original-builder routing tests)."""
    yield
    import legacy_signoff_support
    legacy_signoff_support.restore()
