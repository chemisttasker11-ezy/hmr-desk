"""Synthetic checks: a report block that differs from the patient record stays visible until replaced or deliberately kept."""
import json

import pytest

import api
import jobs
import records
import report
from test_report_save_revision import _setup, _saved_report, _patient_row


def _change_record(conn, patient, **fields):
    for column, value in fields.items():
        conn.execute('UPDATE patients SET %s=? WHERE id=?' % column, (value, patient['id']))
    conn.commit()
    return _patient_row(conn, patient['id'])


def _by_key(loaded):
    return {m['key']: m for m in loaded['demographic_mismatches']}


def test_changed_record_shows_as_unacknowledged_mismatch_and_authored_text_is_kept(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        assert loaded['demographic_mismatches'] == []
        edited = dict(loaded, doctor=loaded['doctor'] + '\nPractice manager: Synthetic Person', expected_revision=loaded['revision'])
        report.save(conn, patient, edited)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected')
        current = report.load(conn, patient)
        found = _by_key(current)
        assert 'Practice manager: Synthetic Person' in current['doctor']          # authored text untouched
        assert found['doctor']['acknowledged'] is False and 'Dr Synthetic Corrected' in found['doctor']['record']
        assert 'Practice manager' in found['doctor']['report']
        assert report.unresolved_demographics(conn, patient, current) == ['doctor', 'dear']


def test_response_only_fields_and_a_forged_acknowledgement_in_a_save_do_nothing(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected')
        current = report.load(conn, patient)
        forged = dict(current, expected_revision=current['revision'], demographics_ack={'doctor': 'x'}, demographic_conflicts=[1])
        report.save(conn, patient, forged)
        stored = json.loads(records.get(conn, patient['id'], 'report_spec.json'))
        assert 'demographic_mismatches' not in stored and 'demographic_conflicts' not in stored
        assert 'doctor' in report.unresolved_demographics(conn, patient, report.load(conn, patient))


def test_keep_is_bound_to_the_exact_text_and_the_current_record_value(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected')
        kept = report.resolve_demographics(conn, patient, 'keep', ['doctor', 'dear'])
        assert all(m['acknowledged'] for m in kept['demographic_mismatches'])
        assert report.unresolved_demographics(conn, patient, kept) == []
        # the same text and record survive a reload
        assert report.unresolved_demographics(conn, patient, report.load(conn, patient)) == []
        # the record changes again: the earlier keep no longer applies
        patient2 = _change_record(conn, patient, gp='Dr Synthetic Third')
        assert report.unresolved_demographics(conn, patient2, report.load(conn, patient2)) == ['doctor', 'dear']
        # the report text is edited: the keep no longer applies
        patient3 = _change_record(conn, patient2, gp='Dr Synthetic Corrected')
        assert report.unresolved_demographics(conn, patient3, report.load(conn, patient3)) == []
        current = report.load(conn, patient3)
        report.save(conn, patient3, dict(current, doctor=current['doctor'] + ' edited', expected_revision=current['revision']))
        assert 'doctor' in report.unresolved_demographics(conn, patient3, report.load(conn, patient3))


def test_keep_logs_block_names_only_and_replace_changes_only_the_chosen_block(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected', dob='01-Feb-1950')
        report.resolve_demographics(conn, patient, 'keep', ['patient'])
        event = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_demographics_kept'", (patient['id'],)).fetchone()['detail']
        assert json.loads(event) == {'blocks': ['patient']}
        assert 'Synthetic' not in event and '1950' not in event
        replaced = report.resolve_demographics(conn, patient, 'replace', ['doctor', 'dear'])
        assert 'Dr Synthetic Corrected' in replaced['doctor'] and replaced['dear'] == 'Dear Dr Synthetic Corrected,'
        assert replaced['patient'] == loaded['patient']                     # a different block is untouched
        assert replaced['issues'] == loaded['issues'] and replaced['reason'] == loaded['reason']
        assert [m['key'] for m in replaced['demographic_mismatches']] == ['patient']
        with pytest.raises(ValueError, match='already matches'):
            report.resolve_demographics(conn, patient, 'replace', ['doctor'])
        for bad in (('delete', ['doctor']), ('keep', []), ('keep', ['issues']), ('keep', 'doctor')):
            with pytest.raises(ValueError):
                report.resolve_demographics(conn, patient, *bad)


def test_api_route_resolves_a_block_and_refuses_extra_fields(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected')
        path = '/api/patients/%s/report/demographics' % patient['id']
        status, result = api.handle(conn, 'POST', path, {}, {'action': 'keep', 'keys': ['doctor'], 'extra': 1})
        assert status == 400
        status, result = api.handle(conn, 'POST', path, {}, {'action': 'keep', 'keys': ['issues']})
        assert status == 400
        status, result = api.handle(conn, 'POST', path, {}, {'action': 'keep', 'keys': ['doctor']})
        assert status == 200 and result['demographic_mismatches'][0]['key'] == 'doctor' and result['demographic_mismatches'][0]['acknowledged']


def test_build_evidence_records_block_status_without_text(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.', expected_revision=loaded['revision'])
        report.save(conn, patient, loaded)
        patient = _change_record(conn, patient, gp='Dr Synthetic Corrected')
        report.resolve_demographics(conn, patient, 'keep', ['doctor'])
        conn.commit()
    jobs.report_build(patient['id'])
    with connection() as conn:
        raw = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1", (patient['id'],)).fetchone()['detail']
    detail = json.loads(raw)
    assert detail['demographics'] == {'name': 'matches', 'assess_date': 'matches', 'patient': 'matches', 'doctor': 'kept', 'dear': 'unresolved'}
    assert 'Corrected' not in raw
