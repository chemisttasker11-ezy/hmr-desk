import report


def test_request_date_is_shown_day_month_year_and_other_text_is_untouched():
    assert report._dmy('2026-11-18') == '18/11/2026'
    assert report._dmy(' 2026-01-05 ') == '05/01/2026'
    assert report._dmy('18 Nov 2026') == '18 Nov 2026'
    assert report._dmy('') == ''
    assert report._dmy('2026-13-45') == '45/13/2026'  # display only: invalid values are not validated here


def test_untouched_generated_blocks_move_to_day_month_year_on_refresh_and_edited_ones_do_not():
    old = {'name': 'A', 'assess_date': '18/11/2026', 'patient': 'A\nDOB: 1950-01-01', 'doctor': 'Dr\nRequest date: 2026-11-18', 'dear': 'Dear Dr,'}
    new = {**old, 'patient': 'A\nDOB: 01/01/1950', 'doctor': 'Dr\nRequest date: 18/11/2026'}
    data = {**old, 'demographics_generated': dict(old)}
    assert report._merge_demographics(data, new) == []
    assert data['patient'].endswith('DOB: 01/01/1950') and data['doctor'].endswith('Request date: 18/11/2026')
    edited = {**old, 'doctor': 'Dr (edited)\nRequest date: 2026-11-18', 'demographics_generated': dict(old)}
    conflicts = report._merge_demographics(edited, new)
    assert [c['key'] for c in conflicts] == ['doctor'] and edited['doctor'].startswith('Dr (edited)')
