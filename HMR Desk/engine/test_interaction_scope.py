"""Interaction-check scope statements: what was and was not covered. Synthetic names only."""
import pytest

import interaction_scope as scope


def rows(*items):
    return [dict(name=n, status=s, source='meds', has_text=t) for n, s, t in items]


def txt(result): return ' '.join(scope.lines(result))


def test_explicit_unknown_off_the_confirmed_list_is_not_on_the_list_and_not_claimed_unchecked_by_matching():
    ing = lambda n: {'alpha': ['alpha'], 'hp7': ['hp7ing']}.get(n.lower(), [])
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Hp7', 'unknown', True)), 'automated_current', ing)
    assert result['off_list'] == ['Hp7']
    assert 'Not on the confirmed medicine list: Hp7' in txt(result)
    assert 'reconciliation is incomplete' in txt(result) and 'limited to the confirmed medicine list' in txt(result)
    assert 'checked list' not in txt(result)
    assert scope.row_tag(result, 'Hp7').startswith('Interaction check: Not on the confirmed list')
    assert scope.row_tag(result, 'Alpha') == ''


def test_unavailable_matching_is_unmatched_never_an_exclusion_claim():
    result = scope.compute(['Alpha'], rows(('Hp7', 'unknown', True)), 'automated_current', None)
    assert result['unmatched'] == ['Hp7'] and not result['off_list']
    assert 'Could not be matched to the confirmed medicine list' in txt(result)
    def boom(name): raise RuntimeError('no data')
    assert scope.compute(['Alpha'], rows(('Hp7', 'unknown', True)), 'automated_current', boom)['unmatched'] == ['Hp7']
    # a confirmed entry with no ingredient data also blocks an off-list claim
    ing = lambda n: {'hp7': ['x']}.get(n.lower(), [])
    assert scope.compute(['Alpha'], rows(('Hp7', 'unknown', True)), 'automated_current', ing)['unmatched'] == ['Hp7']


def test_exact_name_on_confirmed_list_is_membership_not_verified_coverage():
    result = scope.compute(['Alpha', 'Hp7'], rows(('Hp7', 'unknown', True)), 'manual_note')
    assert result['on_list'] == ['Hp7']
    text = txt(result)
    assert 'On the confirmed medicine list although use is not confirmed: Hp7' in text
    assert 'not proof that an interaction check covered it' in text and 'no current result verifies coverage' in text
    assert 'included' not in text.lower() and 'were checked' not in text
    assert 'is not verified' in scope.row_tag(result, 'Hp7')


def test_ambiguous_brand_ingredient_overlap_is_not_coverage():
    ing = lambda n: {'brand x 10mg': ['genx'], 'generic x 50mg': ['genx'], 'generic x 50mg + y': ['genx', 'y']}.get(n.lower(), [])
    result = scope.compute(['Generic X 50mg'], rows(('Brand X 10mg', 'unknown', True)), 'automated_current', ing)
    assert result['ingredient_only'] == ['Brand X 10mg'] and not result['on_list']
    assert 'not established as the same product, strength or combination' in txt(result)
    assert 'Coverage is not established' in txt(result)
    assert 'Coverage not established' in scope.row_tag(result, 'Brand X 10mg')
    combo = scope.compute(['Generic X 50mg'], rows(('Generic X 50mg + Y', 'unknown', True)), 'automated_current', ing)
    assert combo['ingredient_only'] == ['Generic X 50mg + Y']


def test_blank_status_with_actual_use_text_is_unconfirmed_and_blank_without_text_is_ignored():
    result = scope.compute(['Beta'], rows(('Beta', '', True), ('Gamma', '', True), ('Delta', '', False)), 'automated_current')
    assert result['on_list'] == ['Beta']
    assert result['unmatched'] == ['Gamma']
    assert 'Delta' not in txt(result)


def test_ceased_medicines_are_listed_as_not_part_of_the_check_not_as_unconfirmed():
    result = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Old', 'not_using', False)), 'automated_current')
    assert result['not_using'] == ['Old'] and not scope.has_unconfirmed(result)
    assert 'Recorded as not using, not part of the check: Old.' in scope.lines(result)
    assert 'reconciliation is incomplete' not in txt(result)


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
    text = txt(result)
    assert phrase in text
    assert 'result for the current confirmed medicine list is on file' not in text


def test_apply_tags_rows_and_adds_note_without_changing_original(monkeypatch):
    ing = lambda n: {'alpha': ['a'], 'hp7': ['h']}.get(n.lower(), [])
    fixed = scope.compute(['Alpha'], rows(('Alpha', 'taking', True), ('Hp7', 'unknown', True)), 'stale', ing)
    monkeypatch.setattr(scope, 'for_patient', lambda conn, p: fixed)
    data = {'meds': [['Alpha', 'daily', 'note', ''], ['Hp7', '?', '', '']], 'otc': [['Hp7', '?', '']]}
    out, _ = scope.apply_to_report(None, {'id': 1}, data)
    assert data['meds'][1][2] == ''
    assert out['meds'][0][2] == 'note'
    assert out['meds'][1][2].startswith('Interaction check: Not on the confirmed list')
    assert out['otc'][0][2].startswith('Interaction check: Not on the confirmed list')
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


def _template_data():
    return dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026", patient="P", doctor="D", dear="Dear Dr,",
                thanks="", reason="", intro="Intro text", conditions="C", allergies="A", obs="O", meds=[["a", "b", "c", "d"]], otc=[], ceased=[],
                path=[], issues=[{"title": "F", "rec": "R", "rationale": "Y"}], followup="Follow up", path_date="")


def test_approved_template_without_a_marker_carries_the_warning_in_the_intro_and_keeps_layout(tmp_path):
    from docx import Document
    import template_report_builder as renderer
    from test_template_report_builder import make_template
    template = tmp_path / 't.docx'; make_template(template)
    out = tmp_path / 'r.docx'
    renderer.render(dict(_template_data(), interaction_scope_note='Interaction check: no interaction result is on file.'), out, template)
    body = [p.text for p in Document(out).paragraphs]
    assert any('Intro text' in t and 'Interaction check: no interaction result is on file.' in t for t in body)
    assert not any('{{HMR_' in t for t in body)
    plain = tmp_path / 'p.docx'
    renderer.render(dict(_template_data(), interaction_scope_note=''), plain, template)
    assert not any('Interaction check' in p.text for p in Document(plain).paragraphs)
    assert len(Document(out).paragraphs) == len(Document(plain).paragraphs)


def test_approved_template_with_the_optional_marker_places_the_warning_there_and_intro_is_unchanged(tmp_path):
    from docx import Document
    import template_report_builder as renderer
    from test_template_report_builder import make_template
    template = tmp_path / 't.docx'; make_template(template)
    doc = Document(template); doc.add_paragraph('{{HMR_INTERACTION_SCOPE}}'); doc.save(template)
    out = tmp_path / 'r.docx'
    renderer.render(dict(_template_data(), interaction_scope_note='Interaction check: no interaction result is on file.'), out, template)
    body = [p.text for p in Document(out).paragraphs]
    assert 'Interaction check: no interaction result is on file.' in body
    assert 'Intro text' in body
    assert renderer.validate_layout(template) is True
