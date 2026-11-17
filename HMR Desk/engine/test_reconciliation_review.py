"""Synthetic acknowledgement must be bound to the exact source medicine snapshot."""
import pytest
import reconciliation


def case():
    return {'meds': [['Synthetic Medicine', 'once daily', 'twice daily', '', '']],
            'other_meds': [],
            'details': {'meds': [{'use_status': 'taking', 'as_instructed': False}],
                        'other_meds': []}}


def test_review_does_not_modify_medicines_or_automatically_clear_flags():
    record = case()
    current = reconciliation.digest(record)
    review = reconciliation.acknowledge(record, current, 'Synthetic Pharmacist')
    assert reconciliation.review_status(record, review)['reviewed']
    assert reconciliation.audit(record)['flag_count'] > 0
    record['meds'][0][2] = 'once daily'
    assert reconciliation.review_status(record, review)['stale']
    assert not reconciliation.review_status(record, review)['reviewed']
    with pytest.raises(ValueError, match='changed'):
        reconciliation.acknowledge(record, current, 'Synthetic Pharmacist')
    with pytest.raises(ValueError, match='identity'):
        reconciliation.acknowledge(record, reconciliation.digest(record), '')
