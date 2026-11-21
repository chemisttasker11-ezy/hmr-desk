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
