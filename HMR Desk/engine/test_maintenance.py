"""Maintenance fault isolation: a failing step never starves the others."""
import datetime as dt
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import db
import service


@pytest.fixture
def conn(tmp_path):
    c = db.connect(os.path.join(str(tmp_path), 'test.db'))
    yield c
    c.close()


def add_patient_event(conn):
    conn.execute("INSERT INTO patients(key,name,state) VALUES ('k1', 'Synthetic Test', 'pooled')")
    pid = conn.execute('SELECT id FROM patients').fetchone()[0]
    conn.execute("INSERT INTO events (ts, patient_id, type, detail, source) VALUES ('2026-11-17T22:14:00', ?, 'test', '{}', 'test')", (pid,))
    conn.commit()
    return pid


def force_backup_due(monkeypatch):
    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 18, 3, 0)
    monkeypatch.setattr(service, 'datetime', type('M', (), {'datetime': FakeDatetime}))


def test_missing_plan_does_not_starve_backup(conn, monkeypatch, caplog):
    add_patient_event(conn)
    force_backup_due(monkeypatch)
    calls = []
    monkeypatch.setattr(db, 'backup', lambda c: calls.append('backup') or 'x.db')
    with caplog.at_level(logging.DEBUG):
        service.maintenance(conn)
    assert calls == ['backup'], 'daily backup ran even with no plan registered'
    assert service.get_meta(conn, 'backup_date') == '2026-11-18'
    assert int(service.get_meta(conn, 'exported_event_id', '0')) == 0, 'no event advancement without a successful export'
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], 'a plan-less workspace is not an error'


def test_export_failure_does_not_block_backup_and_does_not_advance(conn, tmp_path, monkeypatch, caplog):
    add_patient_event(conn)
    service.set_meta(conn, 'plan_meta', '{}')
    plan = tmp_path / 'plan.json'
    plan.write_text('{"patients": []}', encoding='utf-8')
    service.set_meta(conn, 'plan_file', str(plan))
    import export_plan
    def boom(c):
        raise RuntimeError('synthetic export failure')
    monkeypatch.setattr(export_plan, 'export', boom)
    force_backup_due(monkeypatch)
    calls = []
    monkeypatch.setattr(db, 'backup', lambda c: calls.append('backup') or 'x.db')
    with caplog.at_level(logging.DEBUG):
        service.maintenance(conn)
    assert calls == ['backup'], 'backup still executed after export failure'
    assert service.get_meta(conn, 'backup_date') == '2026-11-18'
    assert int(service.get_meta(conn, 'exported_event_id', '0')) == 0, 'failed export must not advance the event marker'
    failures = [r for r in caplog.records if r.levelno >= logging.ERROR and 'Plan export failed' in r.getMessage()]
    assert failures and failures[0].exc_info, 'export failure logged with diagnostic traceback'
    rendered = '\n'.join(r.getMessage() + (r.exc_text or '') for r in failures)
    assert 'synthetic export failure' in rendered
    assert 'key' not in rendered.lower().replace('monkeypatch', ''), 'no key material in diagnostics'


def test_successful_export_advances_event_marker(conn, tmp_path, monkeypatch):
    add_patient_event(conn)
    service.set_meta(conn, 'plan_meta', '{}')
    plan = tmp_path / 'plan.json'
    plan.write_text('{"patients": []}', encoding='utf-8')
    service.set_meta(conn, 'plan_file', str(plan))
    import export_plan
    exported = []
    monkeypatch.setattr(export_plan, 'export', lambda c: exported.append('export'))
    service.maintenance(conn)
    assert exported == ['export']
    highest = conn.execute('SELECT MAX(id) FROM events').fetchone()[0]
    assert int(service.get_meta(conn, 'exported_event_id', '0')) == highest, 'event marker advances only after successful export'
    service.maintenance(conn)
    assert exported == ['export'], 'no re-export once events are reflected'
