import datetime as dt

import candidate_checks as cc
import pathology_records
import records
import suggestion_context as sc
from test_medicine_snapshot import setup

TODAY = dt.date(2026, 11, 17)


def _save(conn, p, rid, **updates):
    row = dict(id=rid, test='eGFR', value='41', unit='mL/min/1.73m2',
               reference_interval='60-120', sample_date='2026-11-01',
               source='synthetic-lab.pdf page 2', verified=True, comment='')
    row.update(updates)
    return pathology_records.save(conn, p, {'revision': pathology_records.revision(conn, p),
                                            'records': [row]}, reviewer='Synthetic Reviewer')


def _obs(result, eid):
    return next(o for o in result['observations'] if o['evidence_id'] == 'pathology:' + eid)


def test_below_interval_is_neutral_observation_with_full_operands(setup):
    conn, p, _ = setup
    _save(conn, p, 'f' * 32)
    result = cc.for_patient(conn, p)
    o = _obs(result, 'f' * 32)
    assert o['status'] == 'below_stated_interval'
    assert o['kind'] == 'arithmetic_observation'
    assert o['applicability'] == 'unestablished' and 'not independently confirmed' in o['applicability_note']
    assert o['value_exact'] == '41' and o['interval_low_exact'] == '60' and o['interval_high_exact'] == '120'
    assert o['interval_low_inclusive'] is True and o['interval_high_inclusive'] is True
    assert o['raw_value'] == '41' and o['raw_interval'] == '60-120' and o['unit'] == 'mL/min/1.73m2'
    assert o['verified_by'] == 'Synthetic Reviewer' and o['date'] == '2026-11-01'
    assert any('sample date 2026-11-01' in c for c in o['cautions'])
    assert any('synthetic-lab.pdf' in c for c in o['cautions'])
    assert result['review_status'] == 'pharmacist_review_required'
    assert 'not a clinical finding' in ' '.join(result['limitations'])


def test_date_flags_are_carried_into_observation(setup):
    conn, p, _ = setup
    _save(conn, p, '8' * 32, sample_date='2027-01-01')  # future: evidence flag
    result = cc.for_patient(conn, p)
    o = _obs(result, '8' * 32)
    assert 'Future date: check original' in o['flags']
    assert any('sample date 2027-01-01' in c for c in o['cautions'])


def test_missing_unit_cannot_assess_with_reason():
    e = {'id': 'pathology:synthetic', 'kind': 'pathology', 'test': 'eGFR',
         'verification': 'named pharmacist verified', 'verified_by': 'R', 'verified_at': 't',
         'source': 'synthetic', 'date': '2026-11-01', 'flags': [],
         'structured': {'range_position': 'below', 'raw_value': '41', 'raw_interval': '60-120',
                        'unit': '', 'unit_assumption': '', 'undetermined_reason': 'unit not recorded',
                        'basis': 'laboratory range position only'}}
    o = cc.check_lab_range_position(e)
    # Fail closed on missing unit regardless of the supplied position.
    assert o['status'] == 'cannot_assess'
    assert any('unit not recorded' in r for r in o['reasons'])
    e2 = dict(e, structured={**e['structured'], 'unit': 'mmol/L',
                             'undetermined_reason': 'reference interval not an explicit numeric range'})
    o2 = cc.check_lab_range_position(e2)
    assert o2['status'] == 'cannot_assess'
    assert any('reference interval' in r for r in o2['reasons'])


def test_free_text_result_cannot_assess(setup):
    conn, p, _ = setup
    _save(conn, p, '2' * 32, value='see report', reference_interval='')
    result = cc.for_patient(conn, p)
    o = _obs(result, '2' * 32)
    assert o['status'] == 'cannot_assess' and o['reasons']


def test_comparator_result_cannot_assess(setup):
    conn, p, _ = setup
    _save(conn, p, '3' * 32, value='>90', reference_interval='60-120')
    result = cc.for_patient(conn, p)
    o = _obs(result, '3' * 32)
    assert o['status'] == 'cannot_assess'
    assert any('comparator' in r for r in o['reasons'])


def test_unknown_position_fails_closed(setup):
    e = {'id': 'pathology:synthetic', 'kind': 'pathology', 'test': 'eGFR',
         'verification': 'named pharmacist verified', 'verified_by': 'R', 'verified_at': 't',
         'source': 'synthetic', 'date': '2026-11-01', 'flags': [],
         'structured': {'range_position': 'borderline', 'raw_value': '41', 'raw_interval': '60-120',
                        'unit': 'mmol/L', 'basis': 'laboratory range position only'}}
    o = cc.check_lab_range_position(e)
    assert o['status'] == 'cannot_assess'
    assert any('unrecognised' in r for r in o['reasons'])


def test_within_interval_is_neutral_observation_not_reassurance(setup):
    conn, p, _ = setup
    _save(conn, p, '4' * 32, value='90')
    result = cc.for_patient(conn, p)
    o = _obs(result, '4' * 32)
    assert o['status'] == 'within_stated_interval'
    assert 'no_concern' not in o['status'] and 'concern' not in o['status']


def test_unverified_pathology_is_never_assessed(setup):
    conn, p, _ = setup
    row = dict(id='5' * 32, test='K', value='7.1', unit='mmol/L',
               reference_interval='3.5-5.2', sample_date='2026-11-01',
               source='synthetic-lab.pdf', verified=False, comment='')
    pathology_records.save(conn, p, {'revision': pathology_records.revision(conn, p),
                                     'records': [row]}, reviewer='')
    result = cc.for_patient(conn, p)
    assert all(o['evidence_id'] != 'pathology:' + '5' * 32 for o in result['observations'])
    assert 'pathology:' + '5' * 32 in result['unassessed_pathology_ids']


def test_fingerprint_mismatch_refused(setup):
    conn, p, _ = setup
    _save(conn, p, '9' * 32)
    context = sc.build(conn, p, TODAY)
    context['evidence'].append({'id': 'pathology:injected', 'kind': 'pathology',
                                'verification': 'named pharmacist verified',
                                'verified_by': 'X', 'verified_at': 'Y', 'text': 'x'})
    try:
        cc.run(context)
        assert False, 'fingerprint mismatch must refuse'
    except ValueError as exc:
        assert 'fingerprint' in str(exc)


def test_concurrent_evidence_change_refused(setup):
    import interview
    conn, p, _ = setup
    _save(conn, p, 'a' * 32)
    original = sc.build
    calls = []
    def build_then_change(conn_, patient, today=None):
        context = original(conn_, patient, today)
        calls.append(1)
        if len(calls) == 1:
            data = interview.load(conn_, patient)
            data['revision'] = records.revision(conn_, patient['id'], 'interview.json')
            data['notes'] = data.get('notes', '') + ' changed during checks'
            interview.save(conn_, patient, data)
        return context
    sc.build = build_then_change
    try:
        try:
            cc.for_patient(conn, p)
            assert False, 'concurrent change must refuse'
        except ValueError as exc:
            assert 'changed during checks' in str(exc)
    finally:
        sc.build = original


def test_api_route_serves_observations_and_404(setup):
    import api
    conn, p, _ = setup
    _save(conn, p, '7' * 32)
    status, payload = api.handle(conn, 'GET', '/api/patients/%s/candidate-checks' % p['id'], {}, None)
    assert status == 200
    o = _obs(payload, '7' * 32)
    assert o['status'] == 'below_stated_interval'
    status, payload = api.handle(conn, 'GET', '/api/patients/99999/candidate-checks', {}, None)
    assert status == 404


def test_api_route_returns_409_when_evidence_changes_during_checks(setup, monkeypatch):
    import api, interview
    conn, p, _ = setup
    _save(conn, p, 'b' * 32)
    original = sc.build
    calls = []
    def build_then_change(conn_, patient, today=None):
        context = original(conn_, patient, today)
        calls.append(1)
        if len(calls) == 1:
            data = interview.load(conn_, patient)
            data['revision'] = records.revision(conn_, patient['id'], 'interview.json')
            data['notes'] = data.get('notes', '') + ' changed during request'
            interview.save(conn_, patient, data)
        return context
    monkeypatch.setattr(sc, 'build', build_then_change)
    status, payload = api.handle(conn, 'GET', '/api/patients/%s/candidate-checks' % p['id'], {}, None)
    assert status == 409
    assert payload['observations'] == [] and payload['review_status'] == 'checks_unavailable'
    assert 'changed during checks' in payload['error']


def test_output_json_safe(setup):
    import json
    conn, p, _ = setup
    _save(conn, p, '6' * 32)
    json.dumps(cc.for_patient(conn, p), allow_nan=False)
