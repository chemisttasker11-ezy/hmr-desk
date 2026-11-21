"""A medicine-row Action that refresh cannot safely carry forward is held, recoverable and visible. Synthetic data only."""
import records
import report
from test_report_save_revision import _setup, _saved_report


def test_held_entries_follow_the_exact_match_rule():
    row = ['Medicine A', 'one daily', 'Source note']
    old = [[*row, 'Dup one'], [*row, 'Dup two'], ['Medicine B', 'bd', 'n', 'Changed text'], ['Medicine C', 'od', 'n', 'Kept text'], ['Medicine D', 'od', 'n', '']]
    new = [[*row, ''], [*row, ''], ['Medicine B', 'tds', 'n', ''], ['Medicine C', 'od', 'n', ''], ['Medicine D', 'od', 'n', '']]
    held = {h['action']: h['reason'] for h in report._held_entries(old, new)}
    assert held == {'Dup one': 'duplicate', 'Dup two': 'duplicate', 'Changed text': 'changed_or_removed'}
    # a row that disappeared entirely is held too
    assert [h['action'] for h in report._held_entries([['Gone', 'x', 'y', 'Removed text']], [])] == ['Removed text']


def test_refresh_holds_dropped_action_through_later_saves_and_refreshes(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, saved = _saved_report(conn)
        edited = dict(saved, meds=[list(r) for r in saved['meds']], expected_revision=saved['revision'])
        edited['meds'][0][1] = edited['meds'][0][1] + ' (hand edited)'
        edited['meds'][0][3] = 'Synthetic review text that must not be lost'
        report.save(conn, patient, edited)
        refreshed = report.refresh(conn, patient)
        assert refreshed['meds'][0][3] == ''
        assert refreshed['medication_recommendations']['needs_reentry'] == 1
        held = report.load(conn, patient)['held_medicine_actions']
        assert [h['action'] for h in held] == ['Synthetic review text that must not be lost']
        assert held[0]['reason'] == 'changed_or_removed' and held[0]['name'] == saved['meds'][0][0]
        # autosave of the refreshed report (which holds no Action) and a second refresh cannot erase it
        again = report.load(conn, patient)
        report.save(conn, patient, dict(again, expected_revision=again['revision']))
        report.refresh(conn, patient)
        loaded = report.load(conn, patient)
        assert [h['action'] for h in loaded['held_medicine_actions']] == ['Synthetic review text that must not be lost']
        assert 'held_medicine_actions' not in records.get_json(conn, patient['id'], 'report_spec.json')
        # saving the loaded report back (the UI does this) must not put the held list into the spec
        report.save(conn, patient, dict(loaded, expected_revision=loaded['revision']))
        assert 'held_medicine_actions' not in records.get_json(conn, patient['id'], 'report_spec.json')


def test_unchanged_row_is_not_held_and_resolving_hides_but_keeps_text(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, saved = _saved_report(conn)
        edited = dict(saved, meds=[list(r) for r in saved['meds']], expected_revision=saved['revision'])
        edited['meds'][0][3] = 'Synthetic unchanged review'
        report.save(conn, patient, edited)
        report.refresh(conn, patient)
        assert report.load(conn, patient)['held_medicine_actions'] == []
        edited = report.load(conn, patient)
        edited['meds'][0][2] = edited['meds'][0][2] + ' changed'
        report.save(conn, patient, dict(edited, expected_revision=edited['revision']))
        report.refresh(conn, patient)
        held = report.load(conn, patient)['held_medicine_actions']
        assert len(held) == 1
        try:
            report.resolve_held_action(conn, patient, 'nope'); assert False
        except ValueError:
            pass
        assert report.resolve_held_action(conn, patient, held[0]['id'])['held_medicine_actions'] == []
        stored = records.get_json(conn, patient['id'], report.HELD_RECORD)['entries']
        assert stored[0]['action'] == 'Synthetic unchanged review' and stored[0]['resolved'] is True
        try:
            report.resolve_held_action(conn, patient, held[0]['id']); assert False
        except ValueError:
            pass


def _hold_one(conn):
    patient, saved = _saved_report(conn)
    edited = dict(saved, meds=[list(r) for r in saved['meds']], expected_revision=saved['revision'])
    edited['meds'][0][1] += ' (hand edited)'
    edited['meds'][0][3] = 'Synthetic held text'
    report.save(conn, patient, edited)
    report.refresh(conn, patient)
    return patient


def test_build_is_refused_until_held_recommendations_are_handled(tmp_path, monkeypatch):
    import jobs
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient = _hold_one(conn)
        conn.commit()
    def error():
        try: jobs.report_build(patient['id'])
        except Exception as exc: return str(exc)
        return ''
    assert 'Handle held medicine recommendations before building: 1' in error()
    with connection() as conn:
        report.resolve_held_action(conn, patient, report.held_actions(conn, patient)[0]['id'])
    assert 'held medicine' not in error()


def test_signoff_check_runs_and_refuses_with_unhandled_held_text(tmp_path, monkeypatch):
    import pytest, report_auth, report_status
    from test_report_auth import case
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert report_auth.check_approval(conn, patient, body)  # the unmodified fixture signs off
    states = lambda: {'held_medicine_actions': report_status.report_status(conn, patient)['held_medicine_actions']}
    assert states()['held_medicine_actions'] == 0
    report._hold_actions(conn, patient, [dict(name='Synthetic A', directions='od', comment='', action='Synthetic text', reason='duplicate')]); conn.commit()
    assert states()['held_medicine_actions'] == 1
    with pytest.raises(ValueError, match='Held medicine recommendations'):
        report_auth.check_approval(conn, patient, body)
    monkeypatch.setattr(report, 'load', lambda c, p: {})  # the fixture spec is demographics-only, so load() would not validate
    report.resolve_held_action(conn, patient, report.held_actions(conn, patient)[0]['id'])
    assert states()['held_medicine_actions'] == 0
    assert report_auth.check_approval(conn, patient, body)
    conn.close()


def test_held_text_survives_reopen_and_is_in_the_record_list_and_patient_isolated(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient = _hold_one(conn)
        conn.commit()
    with connection() as conn:  # a fresh connection, as after a restart
        assert report.HELD_RECORD in records.names(conn, patient['id'])
        held = report.held_actions(conn, patient)
        assert [h['action'] for h in held] == ['Synthetic held text']
        other = dict(patient, id=patient['id'] + 1000)
        assert report.held_actions(conn, other) == []
        try:
            report.resolve_held_action(conn, other, held[0]['id']); assert False
        except ValueError:
            pass
        assert len(report.held_actions(conn, patient)) == 1


def test_failed_refresh_save_rolls_back_the_held_write(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, saved = _saved_report(conn)
        edited = dict(saved, meds=[list(r) for r in saved['meds']], expected_revision=saved['revision'])
        edited['meds'][0][1] += ' (hand edited)'; edited['meds'][0][3] = 'Synthetic held text'
        report.save(conn, patient, edited)
        real_save = report.save
        def boom(*a, **k): raise ValueError('boom')
        monkeypatch.setattr(report, 'save', boom)
        try:
            report.refresh(conn, patient); assert False
        except ValueError:
            conn.rollback()
        monkeypatch.setattr(report, 'save', real_save)
        assert report.held_actions(conn, patient) == []
        assert report.load(conn, patient)['meds'][0][3] == 'Synthetic held text'  # the typed text is still in the report


def test_unreadable_or_malformed_held_record_fails_closed_never_zero(tmp_path, monkeypatch):
    import pytest, report_status
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient = _hold_one(conn)
        for bad in (b'not json', b'{"version":1,"entries":"x"}', b'{"version":2,"entries":[]}', b'[]',
                    b'{"version":1,"entries":[{"id":"a"}]}'):
            records.put(conn, patient['id'], report.HELD_RECORD, bad); conn.commit()
            with pytest.raises(Exception):
                report.held_actions(conn, patient)
            with pytest.raises(Exception):
                report.load(conn, patient)
            assert report_status.report_status(conn, patient)['held_medicine_actions'] is None
        records.delete(conn, patient['id'], report.HELD_RECORD); conn.commit()
        assert report.held_actions(conn, patient) == []  # absent is the only empty case


def test_build_and_signoff_refuse_when_held_record_is_unreadable(tmp_path, monkeypatch):
    import jobs, pytest, report_auth
    from test_report_auth import case
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient = _hold_one(conn)
        records.put(conn, patient['id'], report.HELD_RECORD, b'garbage'); conn.commit()
    with pytest.raises(ValueError, match='could not be read'):
        jobs.report_build(patient['id'])
    conn, patient, folder, body = case(tmp_path / 'signoff', monkeypatch)
    records.put(conn, patient['id'], report.HELD_RECORD, b'garbage'); conn.commit()
    with pytest.raises(ValueError, match='could not be read'):
        report_auth.check_approval(conn, patient, body)
    conn.close()


def _entry(**over):
    e = dict(name='Synthetic A', directions='od', comment='', action='Synthetic text', reason='duplicate', resolved=False)
    e.update(over); e['id'] = over.get('id', report._held_id(e)); return e


def test_strict_held_contract_rejects_every_malformed_shape(tmp_path, monkeypatch):
    import json, pytest
    connection = _setup(tmp_path, monkeypatch)
    good = _entry()
    cases = {
        'bool version': {'version': True, 'entries': [good]},
        'float version': {'version': 1.0, 'entries': [good]},
        'extra top key': {'version': 1, 'entries': [good], 'x': 1},
        'duplicate ids': {'version': 1, 'entries': [good, dict(good)]},
        'blank action': {'version': 1, 'entries': [_entry(action='   ')]},
        'id not the content hash': {'version': 1, 'entries': [dict(good, id='0' * 16)]},
        'unknown reason': {'version': 1, 'entries': [_entry(reason='other')]},
        'resolved as int': {'version': 1, 'entries': [dict(good, resolved=1)]},
        'extra entry key': {'version': 1, 'entries': [dict(good, note='x')]},
        'too many': {'version': 1, 'entries': [_entry(action='t%d' % i) for i in range(report.HELD_MAX_ENTRIES + 1)]},
    }
    with connection() as conn:
        patient, _ = _saved_report(conn)
        records.put_json(conn, patient['id'], report.HELD_RECORD, {'version': 1, 'entries': [good]}); conn.commit()
        assert [h['action'] for h in report.held_actions(conn, patient)] == ['Synthetic text']  # the shape used below is itself valid
        for label, store in cases.items():
            records.put(conn, patient['id'], report.HELD_RECORD, json.dumps(store).encode()); conn.commit()
            with pytest.raises(ValueError, match='could not be read'):
                report.held_actions(conn, patient)
            with pytest.raises(ValueError, match='could not be read'):
                report.refresh(conn, patient)  # a refresh must not run on top of a record it cannot read
            conn.rollback()


def test_route_resolve_validates_body_and_patient(tmp_path, monkeypatch):
    import routes_report
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient = _hold_one(conn); conn.commit()
        eid = report.held_actions(conn, patient)[0]['id']
        path = '/api/patients/%d/report/held-actions' % patient['id']
        for bad in ({}, {'id': eid}, {'id': eid, 'action': 'delete'}, {'id': 5, 'action': 'resolve'}, {'id': eid, 'action': 'resolve', 'x': 1}, None, []):
            assert routes_report.handle(conn, 'POST', path, {}, bad)[0] == 400
        assert routes_report.handle(conn, 'POST', '/api/patients/9999/report/held-actions', {}, {'id': eid, 'action': 'resolve'})[0] == 404
        assert routes_report.handle(conn, 'GET', path, {}, {}) is None  # only POST is routed
        assert len(report.held_actions(conn, patient)) == 1  # nothing above changed it
        assert routes_report.handle(conn, 'POST', path, {}, {'id': 'wrong', 'action': 'resolve'})[0] == 400
        status, body = routes_report.handle(conn, 'POST', path, {}, {'id': eid, 'action': 'resolve'})
        assert status == 200 and body['held_medicine_actions'] == []
        assert routes_report.handle(conn, 'POST', path, {}, {'id': eid, 'action': 'resolve'})[0] == 400
