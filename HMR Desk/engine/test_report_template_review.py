"""Synthetic checks: a finding added from an imported past-case suggestion template needs a deliberate, server-checked
review for this wording and the current saved sources before the report can be built."""
import copy

import pytest

import jobs
import records
import report
from test_report_save_revision import _setup, _saved_report

H64 = 'a' * 64
SOURCE = {'version': 1, 'context_snapshot_sha256': H64, 'evidence': [{'id': 'obs:0', 'text': 'Synthetic evidence'}]}


def _spec(conn, patient, *issues):
    spec = report.load(conn, patient)
    spec['issues'] = [dict(i) for i in issues]
    spec['followup_decision'] = 'not_required'; spec['followup'] = 'Synthetic pharmacist-authored follow-up wording.'  # keep the earlier build gates out of the way of what is under test
    return report.save(conn, patient, spec)


def _imported(**extra):
    return {'title': 'Template title', 'rec': 'Template recommendation', 'rationale': 'Template rationale',
            'suggestion_source': copy.deepcopy(SOURCE), **extra}


def _tick(conn, patient, tick=True, mutate=None):
    loaded = report.load(conn, patient)
    loaded['issues'][0]['template_reviewed'] = tick
    loaded['issues'][0]['template_review_for'] = loaded['suggestion_context_sha256']
    if mutate: mutate(loaded)
    return report.save(conn, patient, loaded)


def _pending(conn, patient):
    return report.template_reviews_pending(conn, patient, report.load(conn, patient))


def _build_error(patient_id):
    try:
        jobs.report_build(patient_id)
    except Exception as exc:  # the gate under test is the message, later steps are not needed here
        return str(exc)
    return ''


def test_manual_and_unselected_findings_have_no_review_gate(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        assert _pending(conn, patient) == []
        saved = report.load(conn, patient)
        assert 'suggestion_context_sha256' not in saved
        assert 'imported template' not in _build_error(patient['id'])


def test_imported_finding_is_pending_and_build_refuses_until_reviewed(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        _spec(conn, patient, {'title': 'Manual', 'rec': 'Manual rec', 'rationale': 'Manual why'}, _imported())
        assert _pending(conn, patient) == [2]
        conn.commit()
    assert 'Review imported template findings: 2' in _build_error(1)
    with connection() as conn:
        patient = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
        loaded = report.load(conn, patient)
        loaded['issues'] = [loaded['issues'][1], loaded['issues'][0]]
        loaded['issues'][0]['template_reviewed'] = True
        loaded['issues'][0]['template_review_for'] = loaded['suggestion_context_sha256']
        report.save(conn, patient, loaded)  # moved to another position, so the tick is not honoured
        assert _pending(conn, patient) == [1]


def test_deliberate_review_clears_the_gate_and_is_exposed_to_the_editor(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        _spec(conn, patient, _imported())
        assert report.load(conn, patient)['issues'][0]['template_reviewed'] is False
        saved = _tick(conn, patient)
        assert saved['issues'][0]['template_reviewed'] is True
        assert _pending(conn, patient) == []
        stored = records.get_json(conn, patient['id'], 'report_spec.json')
        assert set(stored['issues'][0]['template_review']) == {'sha256', 'context_sha256'}
        assert 'template_reviewed' not in stored['issues'][0] and 'suggestion_context_sha256' not in stored
        conn.commit()
    assert 'imported template' not in _build_error(1)


def test_editing_alone_never_creates_a_review_and_an_edit_after_review_invalidates_it(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        _spec(conn, patient, _imported())
        edited = report.load(conn, patient)
        edited['issues'][0]['rec'] = 'Pharmacist rewrote this'
        report.save(conn, patient, edited)
        assert _pending(conn, patient) == [1]  # edit without a tick is not a review
        _tick(conn, patient)
        assert _pending(conn, patient) == []
        again = report.load(conn, patient)
        again['issues'][0]['rationale'] = 'Changed after review'
        report.save(conn, patient, again)  # the client still reports the old tick state
        assert _pending(conn, patient) == [1]
        # a tick sent in the same save as an edit is also not honoured
        _tick(conn, patient, mutate=lambda d: d['issues'][0].update(rec='Edited and ticked together'))
        assert _pending(conn, patient) == [1]
        _tick(conn, patient)
        assert _pending(conn, patient) == []
        _tick(conn, patient, tick=False)
        assert report.load(conn, patient)['issues'][0]['template_reviewed'] is False
        assert _pending(conn, patient) == [1]


def test_review_lapses_when_the_saved_sources_change(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        _spec(conn, patient, _imported())
        _tick(conn, patient)
        before = report._current_context_sha(conn, patient)
        assert before and _pending(conn, patient) == []
        records.put_json(conn, patient['id'], 'confirmed_meds.json', {'meds': [['Other synthetic medicine', '']], 'allergies': []})
        assert report._current_context_sha(conn, patient) != before
        assert _pending(conn, patient) == [1]
        assert report.load(conn, patient)['issues'][0]['template_reviewed'] is False


def test_tick_needs_the_context_the_pharmacist_saw_and_payload_review_state_is_not_trusted(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        _spec(conn, patient, _imported())
        _tick(conn, patient, mutate=lambda d: d['issues'][0].update(template_review_for='b' * 64))
        assert _pending(conn, patient) == [1]
        forged = report.load(conn, patient)
        forged['issues'][0]['template_review'] = {'sha256': report.template_review_sha(forged['issues'][0], H64), 'context_sha256': H64}
        report.save(conn, patient, forged)
        assert _pending(conn, patient) == [1]
        missing = report.load(conn, patient)
        missing['issues'][0]['template_reviewed'] = True
        report.save(conn, patient, missing)  # no template_review_for at all
        assert _pending(conn, patient) == [1]


def test_legacy_suggestion_finding_without_a_review_record_is_not_silently_certified(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        spec = {k: v for k, v in report.load(conn, patient).items() if k not in ('revision', 'suggestion_context_sha256')}
        spec['issues'] = [_imported()]
        records.put_json(conn, patient['id'], 'report_spec.json', spec)
        assert _pending(conn, patient) == [1]
        _tick(conn, patient)
        assert _pending(conn, patient) == []


def test_review_fields_are_validated_and_manual_findings_cannot_carry_review_state(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        bad = report.load(conn, patient)
        bad['issues'] = [_imported(template_review={'sha256': 'x', 'context_sha256': H64})]
        with pytest.raises(ValueError): report.save(conn, patient, bad)
        bad['issues'] = [_imported(template_reviewed='yes')]
        with pytest.raises(ValueError): report.save(conn, patient, bad)
        manual = report.load(conn, patient)
        manual['issues'] = [{'title': 'Manual', 'rec': 'r', 'rationale': 'w', 'template_reviewed': True, 'template_review': {'sha256': H64, 'context_sha256': H64}}]
        report.save(conn, patient, manual)
        stored = records.get_json(conn, patient['id'], 'report_spec.json')
        assert not {'template_review', 'template_reviewed'} & set(stored['issues'][0])
        assert _pending(conn, patient) == []
