"""Which top-level workspace folder a patient is expected to be in, by state."""
import pytest

import db
import lifecycle


@pytest.mark.parametrize('state,folder,expected,ok', [
    ('new', 'TO SORT', 'Scheduled', True),        # a freshly imported referral: no warning
    ('pooled', 'TO SORT', 'Scheduled', True),
    ('offered', 'TO SORT', 'Scheduled', True),
    ('new', 'Scheduled', 'Scheduled', True),      # legacy expectation kept
    ('confirmed', 'Scheduled', 'Scheduled', True),
    ('confirmed', 'TO SORT', 'Scheduled', False),  # booked but still unsorted
    ('hold', 'TO SORT', 'Scheduled', True),        # a hold keeps the folder it had
    ('hold', 'Scheduled', 'Scheduled', True),
    ('visited', 'Visited', 'Visited', True),
    ('visited', 'TO SORT', 'Visited', False),
    ('sent', 'To CLAIM', 'To CLAIM', True),
    ('claimed', 'Completed & Claimed', 'Completed & Claimed', True),
    ('declined', 'Declined-Exp', 'Declined-Exp', True),
])
def test_folder_check(tmp_path, monkeypatch, state, folder, expected, ok):
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    (tmp_path / folder / 'Patient One').mkdir(parents=True)
    result = lifecycle.folder_check({'state': state, 'folder': folder + '/Patient One'})
    assert result == {'actual': folder, 'expected': expected, 'ok': ok}
