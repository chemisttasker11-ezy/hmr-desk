"""Portable regressions for the global legacy sign-off teardown boundary.

Fictional test-only overrides; no patient records or external integrations.
"""
import builtins
import sys
from types import SimpleNamespace

import pytest

import conftest


def _run_cleanup():
    # Exercise the real autouse fixture body without invoking a pytest fixture
    # manually (the fixture wrapper deliberately forbids direct invocation).
    teardown = conftest._restore_legacy_signoff_overrides.__wrapped__()
    next(teardown)
    with pytest.raises(StopIteration):
        next(teardown)


def test_unused_legacy_helper_is_not_imported_at_teardown(monkeypatch):
    monkeypatch.delitem(sys.modules, 'legacy_signoff_support', raising=False)
    original_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == 'legacy_signoff_support':
            raise AssertionError('teardown imported the Windows-only legacy helper')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guard_import)
    _run_cleanup()
    assert 'legacy_signoff_support' not in sys.modules


def test_loaded_helper_cleanup_is_not_skipped(monkeypatch):
    calls = []
    fake = SimpleNamespace(restore=lambda: calls.append('restored'))
    monkeypatch.setitem(sys.modules, 'legacy_signoff_support', fake)
    _run_cleanup()
    assert calls == ['restored']


@pytest.mark.skipif(sys.platform != 'win32', reason='real legacy helper uses Windows-only SMS code')
def test_real_legacy_asset_and_template_overrides_are_restored_on_windows():
    import jobs
    import legacy_signoff_support
    import template_report_builder

    original_assets = jobs.APP_ASSETS
    original_root = template_report_builder.active_template_root
    try:
        legacy_signoff_support._templates()
        assert jobs.APP_ASSETS != original_assets
        assert template_report_builder.active_template_root is not original_root
        _run_cleanup()
        assert jobs.APP_ASSETS == original_assets
        assert template_report_builder.active_template_root is original_root
    finally:
        legacy_signoff_support.restore()
