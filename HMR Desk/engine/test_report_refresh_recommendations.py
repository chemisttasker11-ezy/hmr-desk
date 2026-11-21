"""Protect pharmacist-written recommendations during medication report refresh.

Only copy text when the medicine display name, actual use, source notes and
uniqueness match exactly in the old and newly derived medicine tables.
"""
import report
from test_report_save_revision import _setup, _saved_report


def test_exact_unchanged_medicine_preserves_authored_review():
    old = [['Medicine A 5 mg', 'one daily', 'Source: referral', 'Check dose with GP'],
           ['Medicine B 2 mg', 'PRN', 'As reported', '']]
    fresh = [['Medicine A 5 mg', 'one daily', 'Source: referral', ''],
             ['Medicine B 2 mg', 'PRN', 'As reported', '']]
    result, stats = report._carry_forward_unchanged_medicine_recommendations(old, fresh)
    assert result[0][3] == 'Check dose with GP'
    assert stats == {'retained': 1, 'needs_reentry': 0}
    assert fresh[0][3] == ''  # input is not mutated


def test_changed_directions_or_source_notes_never_inherit_stale_review():
    old = [['Medicine A 5 mg', 'one daily', 'Original source note', 'Reduce dose after review']]
    for current in (
        [['Medicine A 5 mg', 'twice daily', 'Original source note', '']],
        [['Medicine A 5 mg', 'one daily', 'New source note', '']],
        [['Medicine A 10 mg', 'one daily', 'Original source note', '']],
    ):
        result, stats = report._carry_forward_unchanged_medicine_recommendations(old, current)
        assert result[0][3] == ''
        assert stats == {'retained': 0, 'needs_reentry': 1}


def test_duplicate_ambiguous_rows_never_guess_where_review_belongs():
    row = ['Medicine A', 'one daily', 'Source note']
    old = [[*row, 'Review renal function'], [*row, 'Other handwritten advice']]
    fresh = [[*row, ''], [*row, '']]
    result, stats = report._carry_forward_unchanged_medicine_recommendations(old, fresh)
    assert [r[3] for r in result] == ['', '']
    assert stats == {'retained': 0, 'needs_reentry': 2}


def test_refresh_preserves_unchanged_review_in_encrypted_report_spec(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, saved = _saved_report(conn)
        assert saved['meds'] and not saved['meds'][0][3]
        updated = dict(saved, meds=[list(row) for row in saved['meds']],
                       expected_revision=saved['revision'])
        updated['meds'][0][3] = 'Synthetic pharmacist recommendation requiring review'
        report.save(conn, patient, updated)
        refreshed = report.refresh(conn, patient)
        assert refreshed['meds'][0][3] == 'Synthetic pharmacist recommendation requiring review'
        assert refreshed['medication_recommendations'] == {'retained': 1, 'needs_reentry': 0}
        assert report.load(conn, patient)['meds'][0][3] == updated['meds'][0][3]
        assert 'medication_recommendations' not in report.load(conn, patient)
