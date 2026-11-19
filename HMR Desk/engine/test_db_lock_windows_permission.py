"""Synthetic checks for the lock files db.connect() takes on every API request.

Windows reports a brief PermissionError (delete pending) instead of FileExistsError while another request releases the
lock file. That race must be retried a bounded number of times. A lasting denial must still be raised, a held lock must
never be taken over, and concurrent requests must never hold one lock together. Linux simulation only: real Windows
behaviour is a hypothesis until the host retest."""
import os
import threading

import pytest

import db


def _deny(monkeypatch, suffix, times):
    real = os.open
    state = {'denied': 0, 'calls': 0}
    def fake(path, flags, *a, **k):
        if str(path).endswith(suffix):
            state['calls'] += 1
            if times is None or state['denied'] < times:
                state['denied'] += 1
                raise PermissionError(13, 'Access is denied')
        return real(path, flags, *a, **k)
    monkeypatch.setattr(db.os, 'open', fake)
    monkeypatch.setattr(db.time, 'sleep', lambda s: None)
    return state


def test_transient_denial_is_retried_and_lock_acquired(tmp_path, monkeypatch):
    target = str(tmp_path / 'x.db')
    state = _deny(monkeypatch, '.rotating', 3)
    with db._rotation_lock(target, wait=False) as lock:
        assert lock.held is True and os.path.exists(target + '.rotating')
    assert state['denied'] == 3
    assert not os.path.exists(target + '.rotating')


def test_transient_denial_on_migration_lock(tmp_path, monkeypatch):
    target = str(tmp_path / 'y.db')
    state = _deny(monkeypatch, '.migrating', 2)
    with db._migration_lock(target):
        assert os.path.exists(target + '.migrating')
    assert state['denied'] == 2 and not os.path.exists(target + '.migrating')


def test_lasting_denial_is_raised_after_bounded_tries_and_never_counts_as_held(tmp_path, monkeypatch):
    target = str(tmp_path / 'z.db')
    for cls, suffix, kwargs in ((db._rotation_lock, '.rotating', {'wait': False}), (db._migration_lock, '.migrating', {})):
        state = _deny(monkeypatch, suffix, None)
        with pytest.raises(PermissionError):
            with cls(target, **kwargs):
                raise AssertionError('lock must not be acquired')
        assert state['calls'] == db._LOCK_DENIED_TRIES
        assert not os.path.exists(target + suffix)


def test_held_lock_is_not_taken_over(tmp_path):
    target = str(tmp_path / 'h.db')
    open(target + '.rotating', 'w').close()
    with db._rotation_lock(target, wait=False) as lock:
        assert lock.held is False
    assert os.path.exists(target + '.rotating')   # the other holder's file is left in place


def test_concurrent_requests_never_hold_the_lock_together(tmp_path):
    target = str(tmp_path / 'c.db')
    inside, overlaps, acquired = [0], [0], [0]
    guard = threading.Lock()
    def worker():
        for _ in range(40):
            with db._rotation_lock(target, wait=False) as lock:
                if lock.held:
                    with guard:
                        inside[0] += 1; acquired[0] += 1
                        if inside[0] > 1: overlaps[0] += 1
                    with guard:
                        inside[0] -= 1
    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert overlaps[0] == 0 and acquired[0] > 0
    assert not os.path.exists(target + '.rotating')
