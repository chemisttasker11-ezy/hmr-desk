"""Referral text fidelity: form checklists stay out of the report narrative, and directions are never glued to the wrong medicine."""
import referral

FORM = """Domiciliary Medication Management Review
Reason for referral
Issues that may influence medication use
Currently taking 5 or more regular medications
To select any item - click its checkbox
C
D poor vision
D hearing problems
D swallowing difficulties
D dexterity
D language and/or literacy problems
D cognition
D other: please specify. ..
Simulated narrative reason written by the GP.
Current medications
Alphadrug 50mg Capsule
1 Tablet Daily
"""


def test_form_checklist_is_kept_apart_from_the_reason_narrative():
    out = referral.parse(FORM)
    assert out['reason'] == 'Simulated narrative reason written by the GP.'
    kept = ' '.join(out['form_checklist'])
    assert 'poor vision' in kept and 'click its checkbox' in kept          # nothing is silently lost
    assert 'poor vision' not in out['reason'] and 'checkbox' not in out['reason']


def test_a_real_sentence_that_mentions_a_form_word_is_kept_in_the_narrative():
    out = referral.parse(FORM.replace('Simulated narrative reason written by the GP.', 'Patient reports poor vision and dexterity problems when opening packs.'))
    assert out['reason'] == 'Patient reports poor vision and dexterity problems when opening packs.'


def test_directions_following_one_medicine_still_attach_to_it():
    rows, bad = referral.medicines(['Alphadrug 50mg Capsule', '1 Tablet Daily', 'Betadrug 10mg Tablet', '1 Tablet Twice a day'])
    assert rows == [['Alphadrug 50mg Capsule', '1 Tablet Daily'], ['Betadrug 10mg Tablet', '1 Tablet Twice a day']] and not bad


def test_separate_names_then_directions_are_not_glued_to_the_last_medicine():
    lines = ['Alphadrug 50mg Capsule', 'Betadrug 10mg Tablet', 'Tramadol 50mg Capsule', '1 Tablet Daily', '2 Tablets Twice a day', '1 Capsule In the evening']
    unattributed = []
    rows, bad = referral.medicines(lines, unattributed=unattributed)
    assert [r[1] for r in rows] == ['', '', '']          # no guessed pairing
    assert unattributed == ['1 Tablet Daily', '2 Tablets Twice a day', '1 Capsule In the evening'] and bad   # kept and flagged
    assert referral.medicines(lines)[1] is True           # the caller still learns the section needs reading


def test_parse_reports_unattributed_directions_and_flags_the_medicines_section():
    text = 'Domiciliary Medication Management Review\nCurrent medications\nAlphadrug 50mg Capsule\nBetadrug 10mg Tablet\n1 Tablet Daily\n2 Tablets Twice a day\n'
    out = referral.parse(text)
    assert [m[1] for m in out['meds']] == ['', ''] and out['unattributed_directions'] == ['1 Tablet Daily', '2 Tablets Twice a day']
    assert 'meds' in out['unparsed']


# ---- mixed layouts: nothing is falsely assigned and nothing is lost ----
def test_one_empty_row_then_directions_attach_to_the_adjacent_row_only():
    un = []
    rows, bad = referral.medicines(['Alphadrug 50mg Capsule', '1 Tablet Daily', 'Betadrug 10mg Tablet', '2 Tablets Daily'], unattributed=un)
    assert [r[1] for r in rows] == ['1 Tablet Daily', '2 Tablets Daily'] and not un


def test_two_empty_rows_then_directions_are_unattributed_not_guessed():
    un = []
    rows, bad = referral.medicines(['Alphadrug 50mg Capsule', '1 Tablet Daily', 'Betadrug 10mg Tablet', 'Gammadrug 5mg Tablet', '2 Tablets Daily'], unattributed=un)
    assert [r[1] for r in rows] == ['1 Tablet Daily', '', ''] and un == ['2 Tablets Daily'] and bad


def test_single_medicine_with_several_lines_keeps_all_of_them():
    rows, bad = referral.medicines(['Alphadrug 50mg Capsule', '1 Tablet Daily', 'with food'])
    assert len(rows) == 1 and 'with food' in rows[0][1] and rows[0][1].startswith('1 Tablet Daily')


def test_later_direction_continuation_stays_with_its_own_row():
    rows, bad = referral.medicines(['Alphadrug 50mg Capsule', '1 Tablet Daily', 'Betadrug 10mg Tablet', '1 Tablet Twice a day', 'with meals'])
    assert rows[0][1] == '1 Tablet Daily' and rows[1][1].endswith('with meals') and rows[1][1].startswith('1 Tablet Twice a day')


def test_no_direction_line_is_lost_in_any_layout():
    lines = ['Alphadrug 50mg Capsule', 'Betadrug 10mg Tablet', '1 Tablet Daily', '2 Tablets Daily']
    un = []
    rows, bad = referral.medicines(lines, unattributed=un)
    seen = ' '.join(r[1] for r in rows) + ' ' + ' '.join(un)
    assert '1 Tablet Daily' in seen and '2 Tablets Daily' in seen


def test_glyph_variants_of_ticked_and_unticked_boxes_leave_the_narrative():
    for glyph in ('D', 'C', '\u2610', '\u2611', '\u2612', '\uf0a8', '\uf0fc'):
        text = FORM.replace('D poor vision', glyph + ' poor vision').replace('\nC\n', '\n' + glyph + '\n')
        out = referral.parse(text)
        assert out['reason'] == 'Simulated narrative reason written by the GP.', glyph
        assert any('poor vision' in x for x in out['form_checklist'])


def test_narrative_lines_that_look_like_glyphs_or_options_are_not_dropped_when_part_of_a_sentence():
    narrative = 'Patient has poor vision. D is the carer.'
    out = referral.parse(FORM.replace('Simulated narrative reason written by the GP.', narrative))
    assert out['reason'] == narrative


# ---- already stored records: visible warning, nothing rewritten ----
import interview


def test_stored_concatenated_directions_and_form_reason_raise_warnings_without_changing_data():
    data = {'meds': [['Tramadol 50mg Capsule', '1 Tablet Daily. 1 Tablet Daily. 2 TSPNS Daily p.r.n. 1 Dose Daily', '', '', '']],
            'details': {'reason': 'To select any item - click its checkbox\nD poor vision\nreal reason'}}
    before = repr(data)
    warnings = interview.fidelity_warnings(data)
    assert len(warnings) == 2 and repr(data) == before


def test_clean_stored_record_has_no_warning():
    assert interview.fidelity_warnings({'meds': [['A 5mg Tablet', '1 Tablet Daily. Take with food', '', '', '']], 'details': {'reason': 'Review please.'}}) == []



def test_columns_first_unusual_direction_is_unattributed_not_corrected():
    """Text-order-only parsing cannot infer a row pairing or fix a suspicious word."""
    names_first = [
        'Lunovex 5mg Tablet', 'Fictamol 10mg Capsule',
        '1 Taplet Daily', '2 Capsules At night',
    ]
    source_lines, directions = [], []
    rows, uncertain = referral.medicines(names_first, source_rows=source_lines,
                                         unattributed=directions)
    assert rows == [['Lunovex 5mg Tablet', ''], ['Fictamol 10mg Capsule', '']]
    assert directions == ['1 Taplet Daily', '2 Capsules At night']
    assert source_lines == [['Lunovex 5mg Tablet'], ['Fictamol 10mg Capsule']]
    assert uncertain is True
