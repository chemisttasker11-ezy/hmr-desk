"""Synthetic check: a Windows delete-pending lock file raises PermissionError, not FileExistsError. A concurrent request
that meets it must carry on instead of failing the whole API request before any reply."""
import os

import db


def _deny_once(monkeypatch, real_open, path_suffix):
    state = {'n': 0}
    def fake(path, flags, *a, **k):
        if str(path).endswith(path_suffix) and state['n'] == 0:
            state['n'] += 1
            raise PermissionError(13, 'Access is denied')
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(db.os, 'open', fake)
    return state


def test_rotation_lock_permission_error_means_not_held(tmp_path, monkeypatch):
    target = str(tmp_path / 'x.db')
    state = _deny_once(monkeypatch, os.open, '.rotating')
    with db._rotation_lock(target, wait=False) as lock:
        assert lock.held is False
    assert state['n'] == 1
    with db._rotation_lock(target, wait=False) as lock:
        assert lock.held is True
    assert not os.path.exists(target + '.rotating')


def test_migration_lock_retries_after_permission_error(tmp_path, monkeypatch):
    target = str(tmp_path / 'y.db')
    monkeypatch.setattr(db.time, 'sleep', lambda s: None)
    state = _deny_once(monkeypatch, os.open, '.migrating')
    with db._migration_lock(target):
        assert os.path.exists(target + '.migrating')
    assert state['n'] == 1
    assert not os.path.exists(target + '.migrating')
