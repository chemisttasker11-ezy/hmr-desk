"""Unticking 'I have reviewed this follow-up wording' must persist (found on a Windows retention check)."""
import manual_defaults
import report


def reviewed_record():
    text = manual_defaults.not_required_followup('A B')
    return {'followup_decision': 'not_required', 'followup': text,
            'followup_reviewed_sha256': manual_defaults.text_sha(text, 'not_required')}


def test_explicit_untick_with_unchanged_text_clears_the_stored_review():
    old = reviewed_record()
    saved = report._bind_followup_review({**old, 'followup_text_reviewed': False}, old)
    assert saved['followup_reviewed_sha256'] == '' and 'followup_text_reviewed' not in saved
    assert manual_defaults.review_valid(saved) is False


def test_save_without_the_flag_keeps_an_existing_review():
    old = reviewed_record()
    other = {k: v for k, v in old.items() if k != 'followup_reviewed_sha256'}
    saved = report._bind_followup_review(dict(other), old)
    assert saved['followup_reviewed_sha256'] == old['followup_reviewed_sha256']


def test_tick_after_untick_round_trips():
    old = reviewed_record()
    cleared = report._bind_followup_review({**old, 'followup_text_reviewed': False}, old)
    again = report._bind_followup_review({**cleared, 'followup_text_reviewed': True}, cleared)
    assert again['followup_reviewed_sha256'] == old['followup_reviewed_sha256']
