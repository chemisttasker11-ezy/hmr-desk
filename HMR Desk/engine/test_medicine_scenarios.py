"""Ten-plus synthetic medicine reconciliation cases; no prescribing assertions."""
import copy

import pytest

import reconciliation


def scenario(prescribed, actual, status='taking', extras=None, others=None):
    meta = {'use_status':status, 'as_instructed':False, 'packed':'', 'use_reason':'',
            'use_details':'', 'prn_use':''}
    meta.update(extras or {})
    return {
        'meds': [['Synthetic medicine A', prescribed, actual, '', '']],
        'other_meds': others or [],
        'details': {'meds':[meta], 'other_meds':[]},
    }


@pytest.mark.parametrize('label,record,expected', [
    ('different dose', scenario('one tablet daily','two tablets daily'), 'directions_differ'),
    ('frequency', scenario('one daily','one twice daily'), 'directions_differ'),
    ('unknown actual', scenario('one daily','',status='unknown'), 'use_unconfirmed'),
    ('unconfirmed blank', scenario('once daily','',status=''), 'use_unconfirmed'),
    ('ceased without reason', scenario('once daily','',status='not_using'), 'cessation_reason_missing'),
    ('taking but actual blank', scenario('once daily','',status='taking'), 'actual_directions_missing'),
    ('ceased documented', scenario('once daily','',status='not_using',
                                   extras={'use_reason':'pharmacist to confirm'}), None),
    ('PRN documented', scenario('as needed','as needed',status='taking',
                                 extras={'prn_use':'used on 3 days'}), None),
    ('DAA packed', scenario('once daily','once daily',status='taking',
                              extras={'packed':'dose administration aid'}), None),
    ('exact same directions', scenario('once daily','once daily'), None),
])
def test_ten_synthetic_actual_use_scenarios(label,record,expected):
    audit = reconciliation.audit(record)
    codes = {flag['code'] for flag in audit['flags']}
    if expected is None:
        assert not codes, label
    else:
        assert expected in codes, label
        assert audit['flags'][0]['medicine_id'] == 'meds:0'
    # Deterministic clinical data checks never alter patient actual-use data.
    frozen = copy.deepcopy(record)
    assert reconciliation.audit(record) == audit
    assert record == frozen


def test_ontheday_otc_herbal_and_combination_products_are_not_assumed_equivalent():
    data = scenario('once daily','once daily')
    data['other_meds'] = [
        ['Synthetic herbal product', 'as needed', 'Patient', ''],
        ['Synthetic combination A+B', 'once daily', '', ''],
        ['Synthetic medicine A forte', 'once daily', '', ''],
    ]
    data['details']['other_meds'] = [
        {'use_status':'taking'}, {'use_status':'taking'}, {'use_status':'taking'},
    ]
    result = reconciliation.audit(data)
    assert len(result['medicines']) == 4
    assert not any(f['code'] == 'possible_duplicate' for f in result['flags'])


def test_duplicate_medicine_names_are_reviewed_but_different_strengths_never_auto_merged():
    data = scenario('A 5 mg daily','A 10 mg daily')
    data['meds'].append(['Synthetic medicine A','A 10 mg daily','A 10 mg daily','',''])
    data['details']['meds'].append({'use_status':'taking','as_instructed':True})
    result = reconciliation.audit(data)
    duplicates = [f for f in result['flags'] if f['code'] == 'possible_duplicate']
    assert len(duplicates) == 2
    assert {f['medicine_id'] for f in duplicates} == {'meds:0','meds:1'}


def test_pharmacist_acknowledgement_stales_after_prn_medication_edit():
    data = scenario('as needed','as needed',extras={'prn_use':'twice weekly'})
    source_hash = reconciliation.digest(data)
    approved = reconciliation.acknowledge(data,source_hash,'Synthetic Pharmacist')
    assert reconciliation.review_status(data,approved)['reviewed']
    data['details']['meds'][0]['prn_use'] = 'daily'
    stale = reconciliation.review_status(data,approved)
    assert stale['stale'] and not stale['reviewed']
