"""Actual-use cell wording: confirmation of use vs confirmation of directions stay distinct."""
import report


def test_taking_with_recorded_directions_prints_them():
    assert report.actual(['metformin 1 g', '1 mane', '1 g twice daily', '', ''], {'use_status': 'taking'}) == '1 g twice daily'


def test_taking_without_directions_states_use_confirmed_and_directions_missing():
    assert report.actual(['metformin 1 g', '', '', '', ''], {'use_status': 'taking'}) == 'Taking confirmed - actual directions not recorded'


def test_taking_without_directions_quotes_referral_directions_as_referral():
    assert report.actual(['metformin 1 g', '1 mane', '', '', ''], {'use_status': 'taking'}) == 'Taking confirmed - actual directions not recorded; referral directions: 1 mane'


def test_unknown_keeps_explicit_unconfirmed_with_recorded_directions():
    assert report.actual(['metformin 1 g', '', '1 g bd', '', ''], {'use_status': 'unknown'}) == 'Not yet confirmed; previously recorded directions: 1 g bd'


def test_unexamined_stays_not_yet_confirmed():
    assert report.actual(['metformin 1 g', '', '', '', ''], {'use_status': ''}) == 'Not yet confirmed'


def test_prn_suffix_preserved_on_confirmed_use_without_directions():
    assert report.actual(['metformin 1 g', '', '', '', ''], {'use_status': 'taking', 'prn_use': 'weekly'}) == 'Taking confirmed - actual directions not recorded; used weekly'


def test_no_directions_are_invented_from_status():
    out = report.actual(['Metformin (APX) 1 g tablet, 100, blister pack', '', '', '', ''], {'use_status': 'taking'})
    assert out == 'Taking confirmed - actual directions not recorded'
    assert 'tablet' not in out and 'blister' not in out


def test_other_taking_without_directions():
    assert report.other_actual(['vitamin d', ''], {'use_status': 'taking'}) == 'Taking confirmed - actual directions not recorded'


def test_other_unknown_unchanged():
    assert report.other_actual(['vitamin d', 'daily'], {'use_status': 'unknown'}) == 'Not yet confirmed; previously recorded directions: daily'


def test_other_unexamined_unchanged():
    assert report.other_actual(['vitamin d', ''], {'use_status': ''}) == 'Not yet confirmed'


def test_checked_without_use_status_does_not_confirm_use():
    assert report.actual(['Synthetic medicine 1 g tablet', '', '', '', ''], {'checked': True}) == 'Not yet confirmed'


def test_checked_with_default_empty_status_does_not_confirm_use():
    meta = {'checked': True, 'use_status': '', 'use_reason': '', 'use_details': ''}
    assert report.actual(['Synthetic medicine 1 g tablet', '', '', '', ''], meta) == 'Not yet confirmed'
    assert report.other_actual(['Synthetic supplement 1 g', ''], meta) == 'Not yet confirmed'


def test_checked_unknown_status_does_not_confirm_use():
    meta = {'checked': True, 'use_status': 'unknown'}
    assert report.actual(['Synthetic medicine', 'once daily', '', '', ''], meta) == 'Not yet confirmed; referral: once daily'
    assert report.other_actual(['Synthetic supplement', ''], meta) == 'Not yet confirmed'


def test_legacy_actual_text_is_preserved_without_claiming_confirmation():
    assert report.actual(['Synthetic medicine', '', 'Source-entered directions', '', ''], {'use_status': ''}) == 'Source-entered directions'
    assert report.other_actual(['Synthetic supplement', 'Source-entered directions'], {}) == 'Source-entered directions'
