import followup

BASE = dict(date='2026-11-10', method='video', preferred_method='video', choice_offered_on='2026-11-02', spoke_with='', med_changes='',
            recommendations=[], issues='', outcome='', notes='')


def test_video_allowed_and_legacy_record_upgraded():
    followup.validate(BASE)
    legacy = {k: v for k, v in BASE.items() if k not in ('preferred_method', 'choice_offered_on')}
    legacy['method'] = 'phone'
    assert followup.normalize(legacy)['preferred_method'] == ''
    followup.validate(legacy)


def test_invalid_values_rejected():
    for bad in ({'method': 'fax'}, {'preferred_method': 'fax'}, {'choice_offered_on': 'soon'}):
        try: followup.validate({**BASE, **bad}); assert False
        except ValueError: pass


def test_review_issues_only_from_1_nov_2026():
    assert followup.review_issues(BASE) == []
    blank = {**BASE, 'method': '', 'preferred_method': '', 'choice_offered_on': ''}
    assert len(followup.review_issues(blank)) == 3
    assert followup.review_issues({**blank, 'date': '2026-10-31'}) == []
    assert followup.review_issues({**BASE, 'date': '2026-10-31'})  # video before 1 Nov is not covered
    assert any('prefers face-to-face' in i for i in followup.review_issues({**BASE, 'preferred_method': 'in person'}))
    assert any('after the follow-up date' in i for i in followup.review_issues({**BASE, 'choice_offered_on': '2026-11-11'}))
    assert followup.review_issues({**BASE, 'date': ''}) == []
