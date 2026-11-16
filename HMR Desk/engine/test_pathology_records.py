"""Synthetic pathology provenance and optimistic-concurrency tests."""
import uuid
import pytest
import pathlib
import pathology_records


def row(**updates):
    source = dict(id=uuid.uuid4().hex, test='Serum creatinine', value='98',
                  unit='umol/L', reference_interval='60-110', sample_date='2026-11-12',
                  source='synthetic.pdf page 2', verified=True, comment='')
    source.update(updates)
    return source


def test_pathology_requires_actual_unit_source_and_date():
    assert pathology_records.validate([row()])
    for bad in ({'unit': ''}, {'source': ''}, {'sample_date': ''}, {'test': ''},
                {'value': ''}):
        with pytest.raises(ValueError, match='Verification requires'):
            pathology_records.validate([row(**bad)])
    assert pathology_records.validate([row(unit='', verified=False)])
    with pytest.raises(ValueError, match='sample date'):
        pathology_records.validate([row(sample_date='12/11/2026')])
    one = row()
    with pytest.raises(ValueError, match='duplicate'):
        pathology_records.validate([one, one])


def test_pathology_file_roundtrip_conflict_and_original_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(pathology_records.jobs, 'patient_folder', lambda _: tmp_path)
    patient = {'id': 1}
    initial = pathology_records.load(patient)
    assert initial['revision'] == 'missing'
    example = row()
    result = pathology_records.save(patient, {'revision': 'missing', 'records': [example]}, reviewer='Synthetic Pharmacist')
    assert result['records'][0] == example
    assert result['revision'] != 'missing'
    assert pathlib.Path(tmp_path / 'pathology_records.json').exists()
    with pytest.raises(ValueError, match='changed'):
        pathology_records.save(patient, {'revision': 'missing', 'records': []})
    assert pathology_records.load(patient)['records'] == [example]


def test_verified_result_amendment_requires_fresh_pharmacist_review(tmp_path, monkeypatch):
    monkeypatch.setattr(pathology_records.jobs, 'patient_folder', lambda _: tmp_path)
    patient = {'id': 1}
    original = row()
    created = pathology_records.save(patient, {'revision':'missing','records':[original]},
                                     reviewer='Synthetic Pharmacist')
    assert created['version'] == 2
    assert created['verification'][original['id']]['verified_by'] == 'Synthetic Pharmacist'
    with pytest.raises(ValueError, match='marked unverified'):
        pathology_records.save(patient, {'revision':created['revision'],
                                          'records':[row(**{**original,'value':'120'})]},
                                reviewer='Synthetic Pharmacist')
    unsigned = row(**{**original,'value':'120','verified':False})
    changed = pathology_records.save(patient, {'revision':created['revision'],
                                                'records':[unsigned]}, reviewer='Synthetic Pharmacist')
    assert not changed['verification']
    confirmed = row(**{**unsigned,'verified':True})
    with pytest.raises(ValueError, match='pharmacist name'):
        pathology_records.save(patient, {'revision':changed['revision'],'records':[confirmed]})
    reviewed = pathology_records.save(patient, {'revision':changed['revision'],
                                                'records':[confirmed]}, reviewer='Another Pharmacist')
    assert reviewed['verification'][original['id']]['verified_by'] == 'Another Pharmacist'
    assert len(reviewed['history']) == 3
    assert reviewed['history'][1]['before']['value'] == '98'
    assert reviewed['history'][1]['after']['value'] == '120'


def test_legacy_verified_records_retained_without_forged_reviewer(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(pathology_records.jobs, 'patient_folder', lambda _: tmp_path)
    legacy = row()
    (tmp_path / 'pathology_records.json').write_text(json.dumps({'version':1,'records':[legacy]}))
    patient={'id':1}
    loaded = pathology_records.load(patient)
    assert loaded['records'] == [legacy]
    assert loaded['verification'] == {}
    assert loaded['version'] == 1
    migrated = pathology_records.save(patient, {'revision':loaded['revision'],'records':[legacy]})
    assert migrated['version'] == 2
    assert migrated['records'] == [legacy]
    assert migrated['verification'] == {}
