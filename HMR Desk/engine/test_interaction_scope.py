"""Interaction-check scope statements: what was and was not covered. Synthetic names only."""
import pytest

import interaction_scope as scope


def rows(*items):
    return [dict(name=n, status=s, source='meds', has_text=t) for n, s, t in items]


def test_explicit_unknown_excluded_from_list_is_reported_as_not_checked():
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Hp7', 'unknown', True)), 'automated_current')
    assert result['excluded_unconfirmed'] == ['Hp7'] and result['included_unconfirmed'] == []
    text = ' '.join(scope.lines(result))
    assert 'Hp7' in text and 'were not checked' in text and 'reconciliation is incomplete' in text
    assert 'only to the checked list' in text
    assert scope.row_tag(result, 'Hp7').startswith('Interaction check: NOT included')
    assert scope.row_tag(result, 'Alpha') == ''


def test_unknown_that_was_put_on_the_confirmed_list_is_reported_as_included():
    result = scope.compute(['Alpha', 'Hp7'], rows(('Alpha', 'taking', True), ('Hp7', 'unknown', True)), 'automated_current')
    assert result['included_unconfirmed'] == ['Hp7'] and result['excluded_unconfirmed'] == []
    assert 'Included in the checked list although use is not confirmed: Hp7' in ' '.join(scope.lines(result))
    assert 'included although use is not confirmed' in scope.row_tag(result, 'Hp7')
    assert 'not confirmed' in ' '.join(scope.lines(result))


def test_blank_status_with_actual_use_text_is_unconfirmed_and_blank_without_text_is_ignored():
    result = scope.compute(['Beta'], rows(('Beta', '', True), ('Gamma', '', True), ('Delta', '', False)), 'automated_current')
    assert result['included_unconfirmed'] == ['Beta']
    assert result['excluded_unconfirmed'] == ['Gamma']
    assert 'Delta' not in ' '.join(scope.lines(result))


def test_ceased_medicines_are_listed_as_not_part_of_the_check_not_as_unconfirmed():
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Old', 'not_using', False)), 'automated_current')
    assert result['not_using'] == ['Old'] and not result['excluded_unconfirmed']
    assert 'Recorded as not using, not part of the check: Old.' in scope.lines(result)
    assert 'reconciliation is incomplete' not in ' '.join(scope.lines(result))


def test_clean_case_with_a_current_automated_result_needs_no_statement():
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True)), 'automated_current')
    assert not scope.needs_statement(result)


@pytest.mark.parametrize('evidence,phrase', [
    ('manual_note', 'only a manually saved interaction note'),
    ('stale', 'does not match the current confirmed medicine list'),
    ('none', 'no interaction result is on file'),
    ('no_current_confirmation', 'has not been confirmed'),
])
def test_missing_stale_or_manual_evidence_never_reads_as_a_check(evidence, phrase):
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True)), evidence)
    assert scope.needs_statement(result)
    text = ' '.join(scope.lines(result))
    assert phrase in text
    assert 'result matching the confirmed medicine list is on file' not in text


def test_ingredient_match_counts_a_brand_row_as_on_the_list():
    ing = lambda n: {'brandx': ['genericx'], 'genericx': ['genericx']}.get(n.lower().replace(' ', ''), [])
    result = scope.compute(['Generic X'], rows(('Brand X', 'unknown', True)), 'automated_current', ing)
    assert result['included_unconfirmed'] == ['Brand X']
    result = scope.compute(['Generic X'], rows(('Other', 'unknown', True)), 'automated_current', ing)
    assert result['excluded_unconfirmed'] == ['Other']


def test_apply_tags_rows_and_adds_note_without_changing_original(monkeypatch):
    fixed = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Hp7', 'unknown', True)), 'stale')
    monkeypatch.setattr(scope, 'for_patient', lambda conn, p: fixed)
    data = {'meds': [['Alpha', 'daily', 'note', ''], ['Hp7', '?', '', '']], 'otc': [['Hp7', '?', '']]}
    out, _ = scope.apply_to_report(None, {'id': 1}, data)
    assert data['meds'][1][2] == ''
    assert out['meds'][0][2] == 'note'
    assert out['meds'][1][2].startswith('Interaction check: NOT included')
    assert out['otc'][0][2].startswith('Interaction check: NOT included')
    assert 'does not match the current confirmed' in out['interaction_scope_note']


def _fake(monkeypatch, confirmed_current, files, stamps, generated_current):
    import records, steps, medicine_review
    monkeypatch.setattr(records, 'get', lambda conn, pid, name: b'{}' if confirmed_current is not None else None)
    monkeypatch.setattr(medicine_review, 'confirmed_medicines_current', lambda conn, p: bool(confirmed_current))
    monkeypatch.setattr(records, 'stamp', lambda conn, pid, name: stamps.get(name, '2026-01-01'))
    monkeypatch.setattr(records, 'names_like', lambda conn, pid, prefix: files)
    monkeypatch.setattr(steps, 'interactions_result_current', lambda conn, p, name: generated_current)


GEN = 'MIMS interactions generated ' + 'a' * 64 + ' ' + 'b' * 64 + '.txt'


def test_evidence_state_from_records(monkeypatch):
    p = {'id': 1}
    _fake(monkeypatch, None, [], {}, False); assert scope.evidence_state(None, p) == 'no_current_confirmation'
    _fake(monkeypatch, False, [GEN], {}, True); assert scope.evidence_state(None, p) == 'no_current_confirmation'
    _fake(monkeypatch, True, [], {}, False); assert scope.evidence_state(None, p) == 'none'
    _fake(monkeypatch, True, [GEN], {}, True); assert scope.evidence_state(None, p) == 'automated_current'
    _fake(monkeypatch, True, [GEN], {}, False); assert scope.evidence_state(None, p) == 'stale'
    _fake(monkeypatch, True, ['MIMS interactions note.txt'], {'MIMS interactions note.txt': '2026-02-01'}, False)
    assert scope.evidence_state(None, p) == 'manual_note'
    _fake(monkeypatch, True, ['MIMS interactions note.txt'], {'MIMS interactions note.txt': '2025-12-01'}, False)
    assert scope.evidence_state(None, p) == 'stale'


def test_provisional_report_prints_the_scope_note_before_findings_and_omits_it_when_empty(tmp_path):
    from docx import Document
    import local_report_builder as builder
    base = dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026", patient="P", doctor="D", dear="Dear Dr,",
                thanks="", reason="", intro="", conditions="C", allergies="A", obs="O", meds=[["a", "b", "c", "d"]], otc=[], ceased=[],
                path=[], issues=[{"title": "F", "rec": "R", "rationale": "Y"}], followup="Follow up", path_date="")
    with_note = tmp_path / 'a.docx'; builder.render(dict(base, interaction_scope_note='Interaction check: no interaction result is on file.'), with_note)
    texts = [p.text for p in Document(with_note).paragraphs]
    assert 'Interaction check: no interaction result is on file.' in texts
    assert texts.index('Interaction check: no interaction result is on file.') < texts.index('Review Findings')
    without = tmp_path / 'b.docx'; builder.render(dict(base, interaction_scope_note=''), without)
    assert not any(t.startswith('Interaction check') for t in (p.text for p in Document(without).paragraphs))
