"""Synthetic check: a nil allergy line never hides a real allergy line."""
import referral

HEAD = 'DOMICILIARY MEDICATION MANAGEMENT\nCURRENT MEDICATION:\nSynthetic Medicine A 10mg tablet take daily\nAllergies:\n'


def allergies(*lines):
    return referral.parse(HEAD + '\n'.join(lines) + '\n')


def test_nil_beside_real_allergy_keeps_the_allergy_and_flags_it():
    result = allergies('Nil known.', 'Penicillin - rash')
    assert result['allergies'] == ['Penicillin - rash']
    assert 'allergies' in result['unparsed']
    assert result['unparsed'].count('allergies') == 1


def test_real_allergy_then_nil_keeps_the_allergy():
    assert allergies('Penicillin - rash', 'NKDA')['allergies'] == ['Penicillin - rash']


def test_only_nil_is_nil_known():
    assert allergies('NKDA')['allergies'] == ['nil known']
    assert allergies('Nil known.')['allergies'] == ['nil known']


def test_real_allergies_are_all_kept():
    result = allergies('Penicillin - rash', 'Codeine - nausea')
    assert result['allergies'] == ['Penicillin - rash', 'Codeine - nausea']
    assert 'allergies' not in result['unparsed']
