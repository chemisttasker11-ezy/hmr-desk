"""Synthetic check: free-text directions cannot carry a person's name or an Australian date."""
import pytest
import clinical_privacy as cp


@pytest.mark.parametrize('text', [
    'John Smith born 12/03/1950', 'Jane Citizen', 'take daily 5/6/50', 'on 12-Mar-1950', 'D.O.B 1/2/45',
    'per 03.04.1950', 'born in spring',
])
def test_names_and_dates_in_directions_are_blocked(text):
    with pytest.raises(cp.PrivacyBlocked):
        cp.clean(text)


@pytest.mark.parametrize('text', [
    '1 tablet twice daily', '2 puffs PRN', 'Take with food', 'Take Twice Daily', 'half tablet at night', '1/2 tablet daily',
    '5-10 mg as needed', '1-2 tablets every 4-6 hours',
])
def test_ordinary_directions_still_pass(text):
    assert cp.clean(text) == text


def test_medicine_labels_are_not_subject_to_the_name_check():
    assert cp.clean('Metformin Hydrochloride', label=True) == 'Metformin Hydrochloride'
