import socket

import claim_prep

FULL = {'given': 'Amy', 'family': 'Example', 'dob': '1950-01-02', 'medicare': '1234567890', 'interview': '2026-02-01',
        'reportSent': '2026-02-02', 'referral': '2026-01-03', 'gpProvider': '123456A', 'outcomes': ['o'], 'consentHeld': True}


def test_complete_row_is_only_locally_complete_and_never_submitted():
    out = claim_prep.prepare([FULL])
    assert out['connection'] == 'not_connected' and out['submission'] == 'not_available'
    assert out['items'] == [{'name': 'Amy Example', 'missing': [], 'status': 'details_complete_locally'}]
    assert 'ready' not in repr(out).lower() and 'valid' not in repr(out).lower()


def test_missing_fields_and_consent_are_listed_in_plain_words():
    row = dict(FULL, medicare='', outcomes=[], gpProvider='  ', consentHeld=False)
    item, = claim_prep.prepare([row])['items']
    assert item['status'] == 'needs_information'
    assert item['missing'] == ['Medicare number', 'GP provider number', 'outcomes', 'consent evidence']


def test_empty_input_and_no_network_use(monkeypatch):
    def boom(*a, **k): raise AssertionError('network used')
    monkeypatch.setattr(socket, 'socket', boom)
    assert claim_prep.prepare([])['items'] == [] and claim_prep.prepare(None)['items'] == []
    assert claim_prep.prepare([FULL])['items'][0]['status'] == 'details_complete_locally'
