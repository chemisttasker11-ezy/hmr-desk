"""Pins the stopped-overlap contract in the manual medicine-name mode (synthetic names only).
In this mode an 'ingredient' is the whole name normalised for case and spacing, so an overlap exists only when a medicine in the
confirmed list has the same normalised name as a medicine marked not using. The alternative rule requires the chosen taking medicine
to have the row's name and a name different from every stopped one, so no alternative can resolve a manual-mode overlap."""
import api


def usage(name, status):
    return {'name': name, 'status': status, 'detail': '', 'source': 'Referral medicine', 'directions': ['', '']}


STOPPED = usage('Synthmed A 10 mg tablet', 'not_using')


def check(meds, items, pick):
    relevant = api.relevant_usage(items, meds)
    choice = None if pick is None else next(x for x in relevant if x['status'] == 'taking')
    return api.valid_alternatives(meds, relevant, [choice])


def test_ingredient_in_manual_mode_is_the_whole_normalised_name():
    assert api.mims.ingredients('Synthmed  A 10 MG tablet') == ['synthmed a 10 mg tablet']
    assert api.mims.ingredients('Synthmed A 20 mg tablet') == ['synthmed a 20 mg tablet']


def test_different_strength_is_not_an_overlap_and_needs_no_alternative():
    assert check([['Synthmed A 20 mg tablet', '']], [STOPPED, usage('Synthmed A 20 mg tablet', 'taking')], None) is True


def test_same_normalised_name_is_an_overlap_and_no_selection_resolves_it():
    items = [STOPPED, usage('synthmed  a 10 mg   TABLET', 'taking')]
    meds = [['synthmed  a 10 mg   TABLET', '']]
    assert check(meds, items, None) is False
    assert check(meds, items, 'taking') is False
    items = [STOPPED, usage('Synthmed A 10 mg tablet', 'taking')]
    assert check([['Synthmed A 10 mg tablet', '']], items, 'taking') is False


def test_a_stopped_medicine_not_in_the_confirmed_list_causes_no_overlap():
    assert check([['Synthmed B 5 mg tablet', '']], [STOPPED, usage('Synthmed B 5 mg tablet', 'taking')], None) is True
