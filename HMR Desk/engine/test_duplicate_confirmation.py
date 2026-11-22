"""Pharmacist-confirmed duplicate entries: structured, explicit, never inferred, never a change of use. Synthetic data only."""
import copy
import pytest
import interview
import interaction_scope as scope
from test_medicine_snapshot import setup  # noqa: F401  (fixture)

A, B, C = 'a' * 32, 'b' * 32, 'c' * 32


def record(setup, rows):
    conn, p, data = setup
    data = copy.deepcopy(data)
    data['meds'] = [[r[0], 'one daily', 'one daily', '', ''] for r in rows]
    data['other_meds'] = []
    data['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': r[1], 'use_reason': '', 'use_details': '', 'item_id': r[2]} for r in rows]
    data['details']['other_meds'] = []
    return data


def link(data, i, target_index, note=''):
    m, t = data['details']['meds'][i], data['details']['meds'][target_index]
    m['duplicate_of'] = {'item_id': t['item_id'], 'own_sig': interview.identity_sig(data['meds'][i], m),
                         'target_sig': interview.identity_sig(data['meds'][target_index], t), 'target_text': data['meds'][target_index][0], 'note': note}


def test_confirmation_validates_saves_and_is_current(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    link(data, 1, 0, 'entered twice')
    interview.validate(data)
    state = interview.duplicate_state(data)
    assert len(state) == 1 and state[0]['current'] and state[0]['target_name'] == 'Synth 10 mg tablet'
    assert data['details']['meds'][1]['use_status'] == 'not_using' and data['details']['meds'][0]['use_status'] == 'taking'  # use untouched
    assert 'Pharmacist confirmed this entry as a duplicate' in interview.medicine_rows(data)[1][4] and 'entered twice' in interview.medicine_rows(data)[1][4]
    assert 'duplicate' not in interview.medicine_rows(data)[0][4].lower()


def test_an_unconfirmed_pair_with_identical_text_is_never_reported_as_a_duplicate(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    assert interview.duplicate_state(data) == [] and 'duplicate' not in interview.medicine_rows(data)[1][4].lower()


def test_ten_and_twenty_mg_stay_distinct_and_a_confirmation_does_not_survive_a_strength_edit(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    link(data, 1, 0)
    data['meds'][0][0] = 'Synth 20 mg tablet'
    interview.validate(data)  # structurally fine, but no longer current
    assert interview.duplicate_state(data)[0]['current'] is False
    assert 'no longer current' in interview.medicine_rows(data)[1][4] and 'Pharmacist confirmed this entry' not in interview.medicine_rows(data)[1][4]


def test_a_lapsed_confirmation_is_not_revived_by_restoring_the_text_and_needs_a_new_tick(setup):
    conn, p, data = setup
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    data['revision'] = 'missing'
    link(data, 1, 0, 'checked against the referral')
    data['meds'][0][0] = 'Synth 20 mg tablet'          # identity changes, then the record is saved
    saved = interview.save(conn, p, data)
    kept = saved['details']['meds'][1]['duplicate_of']
    assert kept['lapsed'] is True and kept['note'] == 'checked against the referral' and kept['target_text'] == 'Synth 10 mg tablet'  # audit retained
    saved['meds'][0][0] = 'Synth 10 mg tablet'          # the text is put back
    again = interview.save(conn, p, saved)
    state = interview.duplicate_state(again)[0]
    assert state['current'] is False and 'needs a new confirmation' in interview.medicine_rows(again)[1][4]
    fresh = copy.deepcopy(again); link(fresh, 1, 0, 'confirmed again')
    assert interview.duplicate_state(fresh)[0]['current'] is True  # an explicit new confirmation is current
    assert 'lapsed' not in fresh['details']['meds'][1]['duplicate_of']


def test_a_lapsed_link_does_not_block_marking_its_target_and_unchanged_saves_do_not_lapse(setup):
    conn, p, data = setup
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'taking', B), ('Synth 10 mg tablet', 'taking', C)])
    data['revision'] = 'missing'
    link(data, 1, 0)
    saved = interview.save(conn, p, data)
    assert 'lapsed' not in saved['details']['meds'][1]['duplicate_of']   # nothing changed: stays current
    saved['meds'][0][0] = 'Synth 20 mg tablet'; saved = interview.save(conn, p, saved)
    assert saved['details']['meds'][1]['duplicate_of']['lapsed'] is True
    saved['meds'][2][0] = 'Synth 20 mg tablet'
    link(saved, 0, 2)  # row 0 may now be marked: the lapsed link pointing at it no longer counts
    interview.validate(saved)


def test_own_edit_or_removal_of_the_target_invalidates_and_does_not_break_the_record(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    link(data, 1, 0)
    own = copy.deepcopy(data); own['meds'][1][0] = 'Synth 10 mg capsule'
    assert interview.duplicate_state(own)[0]['current'] is False
    gone = copy.deepcopy(data); del gone['meds'][0]; del gone['details']['meds'][0]
    interview.validate(gone)
    state = interview.duplicate_state(gone)
    assert state[0]['current'] is False and state[0]['target_name'] == 'Synth 10 mg tablet'


def test_self_links_chains_cycles_and_malformed_links_are_refused(setup):
    data = record(setup, [('X 1 mg', 'taking', A), ('X 1 mg', 'taking', B), ('X 1 mg', 'taking', C)])
    selfie = copy.deepcopy(data); link(selfie, 0, 0)
    with pytest.raises(ValueError, match='itself'): interview.validate(selfie)
    cycle = copy.deepcopy(data); link(cycle, 0, 1); link(cycle, 1, 0)
    with pytest.raises(ValueError, match='itself marked'): interview.validate(cycle)
    chain = copy.deepcopy(data); link(chain, 0, 1); link(chain, 1, 2)
    with pytest.raises(ValueError, match='itself marked'): interview.validate(chain)
    for bad in ({'item_id': 'nope'}, {'item_id': B, 'own_sig': 'x' * 2001, 'target_sig': 'y', 'target_text': '', 'note': ''}, {'item_id': B, 'own_sig': '', 'target_sig': 'y', 'target_text': '', 'note': ''}, 'B', None):
        broken = copy.deepcopy(data); broken['details']['meds'][0]['duplicate_of'] = bad
        with pytest.raises(ValueError): interview.validate(broken)
    two = copy.deepcopy(data); link(two, 1, 0); link(two, 2, 0)
    interview.validate(two)  # several copies may point at one entry


def test_report_footer_and_report_row_carry_the_confirmation_without_deciding_use(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 10 mg tablet', 'not_using', B)])
    link(data, 1, 0, 'same product entered twice')
    state = interview.duplicate_state(data)
    text = ' '.join(scope.lines(scope.compute(['Synth 10 mg tablet'], [{'name': 'Synth 10 mg tablet', 'status': 'taking'}, {'name': 'Synth 10 mg tablet', 'status': 'not_using'}], 'automated_current', None, state)))
    assert 'Pharmacist confirmed a duplicate entry' in text and 'does not record which entry is in use' in text and 'same product entered twice' in text
    assert scope.needs_statement(scope.compute([], [], 'automated_current', None, state))
    state[0]['current'] = False
    assert 'no longer current' in ' '.join(scope.lines(scope.compute([], [], 'automated_current', None, state)))
    assert not scope.needs_statement(scope.compute([], [], 'automated_current', None, []))


def test_legacy_rows_without_the_field_or_item_ids_are_unchanged(setup):
    conn, p, data = setup
    assert interview.duplicate_state(data) == [] and interview.duplicate_notes(data) == {}
    no_id = record(setup, [('Q 1 mg', 'taking', A)]); del no_id['details']['meds'][0]['item_id']
    assert interview.duplicate_state(no_id) == []


def test_confirmation_survives_the_real_save_and_reload_and_reorder(setup):
    conn, p, data = setup
    data = copy.deepcopy(data)
    data['meds'] = [['Synth 10 mg tablet', 'one daily', 'one daily', '', ''], ['Synth 10 mg tablet', 'one daily', 'one daily', '', '']]
    data['other_meds'] = []
    data['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'taking', 'use_reason': '', 'use_details': '', 'item_id': A},
                               {'packed': '', 'as_instructed': False, 'use_status': 'not_using', 'use_reason': 'other', 'use_details': 'entered twice', 'item_id': B}]
    data['details']['other_meds'] = []
    link(data, 1, 0, 'checked against the referral')
    data['revision'] = 'missing'
    interview.save(conn, p, data)
    again = interview.load(conn, p)
    assert again['details']['meds'][1]['duplicate_of']['note'] == 'checked against the referral'
    assert again['details']['meds'][1]['use_status'] == 'not_using' and again['details']['meds'][0]['use_status'] == 'taking'
    assert interview.duplicate_state(again)[0]['current'] is True
    # reorder: the link follows the stable item ids, not positions
    swapped = copy.deepcopy(again)
    for key in ('meds',):
        swapped[key].reverse(); swapped['details'][key].reverse()
    state = interview.duplicate_state(swapped)
    assert len(state) == 1 and state[0]['current'] and state[0]['index'] == 0 and state[0]['target_name'] == 'Synth 10 mg tablet'


R5 = {'source': 'amt', 'code': '5'}
CASES = [  # (text a, ref a, text b, ref b, compatible) -- fail-closed: equal text after case/spacing/plural only; the renderer test uses the same table
    ('Metformin 500 mg tablet', None, 'metformin  500 MG tablet', None, True),
    ('Metformin 500 mg tablet', None, 'Metformin 1000 mg tablet', None, False),
    ('Metformin 500 mg tablet', None, 'Metformin 500 mg capsule', None, False),
    ('Metformin', None, 'Metformin', None, False),
    ('Brand A 500 mg tablet', R5, 'BRAND A 500mg tablets', R5, True),
    ('Brand A 500 mg tablet', R5, 'Generic B 500 mg tablets', R5, False),
    ('Brand A 500 mg tablet', R5, 'Generic B 850 mg tablet', R5, False),
    ('Brand A 500 mg tablet', R5, 'Brand A 500 mg tablet', {'source': 'amt', 'code': '6'}, False),
    ('Brand A 500 mg MR tablet', R5, 'Brand A 500 mg tablet', R5, False),
    ('Brand X 10 mg extended-release tablet', R5, 'Brand X 10 mg immediate-release tablet', R5, False),
    ('Brand X 10 mg/20 mg tablet', R5, 'Brand X 20 mg/10 mg tablet', R5, False),
    ('Brand X 10 mg gel', R5, 'Brand X 10 mg powder', R5, False),
    ('Brand X 10 mg widget', R5, 'Brand X 10 mg gadget', R5, False),
    ('Version 2 notes', R5, 'Version 2 notes', R5, False),
    ('Syrup 5 mg/5 mL', None, 'Syrup 5 mg/5 mL', None, True),
    ('Syrup 5 mg/5 mL', None, 'Syrup 5 mg/10 mL', None, False),
]


@pytest.mark.parametrize('a, ra, b, rb, expected', CASES)
def test_only_entries_that_show_the_same_strength_and_form_can_be_confirmed(a, ra, b, rb, expected):
    meta = lambda r: {'reference': {'source': r['source'], 'code': r['code'], 'display': 'x', 'release': '1'}} if r else {}
    assert interview.duplicate_compatible([a], meta(ra), [b], meta(rb)) is expected


def test_the_engine_refuses_a_current_confirmation_between_entries_with_different_strength(setup):
    data = record(setup, [('Synth 10 mg tablet', 'taking', A), ('Synth 20 mg tablet', 'taking', B)])
    link(data, 1, 0)
    with pytest.raises(ValueError, match='same strength and form'): interview.validate(data)
    ok = record(setup, [('Brand 10 mg tablet', 'taking', A), ('BRAND 10mg tablets', 'taking', B)])
    for m in ok['details']['meds']: m['reference'] = {'source': 'amt', 'code': '7', 'display': 'x', 'release': '1'}
    link(ok, 1, 0)
    interview.validate(ok)  # same entry, only case/spacing/plural differ


ADVERSARIAL = [
    ('Brand X .5 mg tablet', 'Brand X 5 mg tablet'),
    ('Brand X 0.5 mg tablet', 'Brand X .5 mg tablet'),
    ('Brand X 5 mg tablet', 'Brand X 5. mg tablet'),
    ('Brand X 5-10 mg tablet', 'Brand X 5+10 mg tablet'),
    ('Brand X 5-10 mg tablet', 'Brand X 5/10 mg tablet'),
    ('Brand X 5+10 mg tablet', 'Brand X 5/10 mg tablet'),
    ('Brand X 5,10 mg tablet', 'Brand X 5/10 mg tablet'),
    ('Brand X 5 mg/mL solution', 'Brand X 5 mg/5 mL solution'),
    ('Brand X 5 mg per mL solution', 'Brand X 5 mg/mL solution'),
    ('Brand X 5 mg/mL solution', 'Brand X 5 mg:mL solution'),
    ('Brand X 1,000 mg tablet', 'Brand X 1000 mg tablet'),
    ('Brand X 1.000 mg tablet', 'Brand X 1000 mg tablet'),
    ('Brand X 5 mg tablet', 'Brand X 50 mg tablet'),
    ('Brand X 1 0 mg tablet', 'Brand X 10 mg tablet'),
    ('Brand X 5 mg tablet', 'Brand X 5 mg (tablet)'),
    ('Brand X 5 mg tablet', 'Brand X 5 mg tablet x2'),
    ('Brand X 5 mg tablet', 'Brand X 5 mg tablet.'),
    ('Brand X 5 mg EC tablet', 'Brand X 5 mg-EC tablet'),
    ('Brand X 5 mg tablet', 'Brand X 5 mcg tablet'),
    ('Brand X 5 mg tablet', 'Brand X 5 g tablet'),
    ('Brand X 5 mg tablet', 'Brand X 5 % tablet'),
    ('Brand X 5 mg tablet', 'Brand-X 5 mg tablet'),
    ('Brand X µ5 tablet', 'Brand X 5 tablet'),
    ('Brand X 5 mg tablet', 'Brand X ５ mg tablet'),
]


@pytest.mark.parametrize('a, b', ADVERSARIAL)
def test_punctuation_digits_and_units_are_never_normalised_into_the_same_identity(a, b):
    for ref in (None, {'source': 'amt', 'code': '5', 'display': 'x', 'release': '1'}):
        meta = {'reference': ref} if ref else {}
        assert interview.duplicate_compatible([a], meta, [b], meta) is False
        assert interview.duplicate_compatible([b], meta, [a], meta) is False


def test_only_case_whitespace_and_tablet_capsule_plurals_are_ignored_and_a_mutation_scan_finds_no_other_equality():
    base = 'Brand X 5-10 mg/5 mL .5% tablet, 1,000 (EC) + oral'
    meta = {}
    assert interview.duplicate_compatible([base], meta, ['  BRAND x   5-10 MG/5 ML .5%  TABLETS, 1,000 (ec) +  oral'], meta) is True
    # remove or replace each non-space, non-letter character, and each digit: none may stay compatible
    for i, ch in enumerate(base):
        if ch == ' ' or ch.isalpha() and ch.isascii() and not ch.isdigit(): continue
        for repl in ('', 'x' if ch.isdigit() else '', '+', '-', '/', '.', ',', ':', '9'):
            mutated = base[:i] + repl + base[i + 1:]
            if mutated == base: continue
            assert interview.duplicate_compatible([base], meta, [mutated], meta) is False, (i, ch, repl)
