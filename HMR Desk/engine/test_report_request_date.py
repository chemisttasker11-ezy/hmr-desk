import report


def test_request_date_is_shown_day_month_year_and_other_text_is_untouched():
    assert report._dmy('2026-11-18') == '18/11/2026'
    assert report._dmy(' 2026-01-05 ') == '05/01/2026'
    assert report._dmy('18 Nov 2026') == '18 Nov 2026'
    assert report._dmy('') == ''
    assert report._dmy('2026-13-45') == '45/13/2026'  # display only: invalid values are not validated here
