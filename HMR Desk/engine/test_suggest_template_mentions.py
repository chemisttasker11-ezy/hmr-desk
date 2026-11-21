"""Synthetic: past-case wording that names things this patient's record lacks is flagged, never silently reused.
Lexical comparison with the existing extractor only. No clinical rule, no dose or lab cutoff."""
import suggest


def _case(i, rationale):
    return {'id': 'c%d' % i, 'age': 80, 'sex': 'Mrs', 'Current Conditions': 'Insomnia',
            'meds': [{'row': ['Temazepam 10 mg', 'nocte', '', '', ''], 'kind': 'regular'}],
            'findings': [{'title': 'Temazepam use with regular alcohol intake', 'rec': 'Review temazepam and alcohol use',
                          'rationale': rationale}]}


def _index():
    cases = [_case(i, 'Sedation and falls risk. Renal impairment raises exposure.') for i in range(6)]
    return suggest.make_index(cases, '', '', tuning=2)


def _context(meds, notes=''):
    return {'age': 82, 'sex': 'female', 'meds': meds, 'obs': notes, 'conditions': '', 'labs': [], 'interactions': ''}


def test_template_mentions_missing_from_the_record_are_listed():
    out = suggest.suggest(_context(['Temazepam 10 mg nocte']), index=_index())
    item = next(x for x in out if 'Temazepam' in x['title'])
    absent = item['template_mentions_not_in_record']
    assert 'topic:renal' in absent
    assert any('Template wording mentions' in m and 'renal' in m for m in item['missing'])
    assert not any(k.endswith('temazepam') for k in absent)  # what the patient takes is not flagged


def test_a_mention_present_in_the_patients_record_is_not_flagged():
    out = suggest.suggest(_context(['Temazepam 10 mg nocte'], notes='Renal function discussed at interview.'), index=_index())
    item = next(x for x in out if 'Temazepam' in x['title'])
    assert 'topic:renal' not in item['template_mentions_not_in_record']


def test_nothing_is_asserted_or_removed_by_the_flag():
    out = suggest.suggest(_context(['Temazepam 10 mg nocte']), index=_index())
    item = next(x for x in out if 'Temazepam' in x['title'])
    assert item['title'] == 'Temazepam use with regular alcohol intake'  # wording untouched; only a visible prompt added
    assert item['source'] == 'past cases'


def test_negated_or_stopped_mentions_do_not_count_as_present():
    for note in ('Denies renal impairment.', 'No history of renal disease', 'Renal function: nil known', 'Renal impairment resolved'):
        out = suggest.suggest(_context(['Temazepam 10 mg nocte'], notes=note), index=_index())
        item = next(x for x in out if 'Temazepam' in x['title'])
        assert 'topic:renal' in item['template_mentions_not_in_record'], note


def test_med_text_marked_ceased_is_not_present_support():
    idx = suggest.make_index([_case(i, 'Warfarin bleeding risk with aspirin.') for i in range(6)], '', '', tuning=2)
    for meds, flagged in ((['Temazepam 10 mg nocte', 'Warfarin 5 mg'], False), (['Temazepam 10 mg nocte', 'Warfarin 5 mg - ceased'], True)):
        item = next(x for x in suggest.suggest(_context(meds), index=idx) if 'Temazepam' in x['title'])
        assert ('med:warfarin' in item['template_mentions_not_in_record']) is flagged, meds
