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
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    patient = {'id': 1}
    initial = pathology_records.load(conn, patient)
    assert initial['revision'] == 'missing'
    example = row()
    result = pathology_records.save(conn, patient, {'revision': 'missing', 'records': [example]}, reviewer='Synthetic Pharmacist')
    assert result['records'][0] == example
    assert result['revision'] != 'missing'
    import records; assert records.exists(conn, 1, 'pathology_records.json') and not (tmp_path / 'pathology_records.json').exists()
    with pytest.raises(ValueError, match='changed'):
        pathology_records.save(conn, patient, {'revision': 'missing', 'records': []})
    assert pathology_records.load(conn, patient)['records'] == [example]


def test_verified_result_amendment_requires_fresh_pharmacist_review(tmp_path, monkeypatch):
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    patient = {'id': 1}
    original = row()
    created = pathology_records.save(conn, patient, {'revision':'missing','records':[original]},
                                     reviewer='Synthetic Pharmacist')
    assert created['version'] == 2
    assert created['verification'][original['id']]['verified_by'] == 'Synthetic Pharmacist'
    with pytest.raises(ValueError, match='marked unverified'):
        pathology_records.save(conn, patient, {'revision':created['revision'],
                                          'records':[row(**{**original,'value':'120'})]},
                                reviewer='Synthetic Pharmacist')
    unsigned = row(**{**original,'value':'120','verified':False})
    changed = pathology_records.save(conn, patient, {'revision':created['revision'],
                                                'records':[unsigned]}, reviewer='Synthetic Pharmacist')
    assert not changed['verification']
    confirmed = row(**{**unsigned,'verified':True})
    with pytest.raises(ValueError, match='pharmacist name'):
        pathology_records.save(conn, patient, {'revision':changed['revision'],'records':[confirmed]})
    reviewed = pathology_records.save(conn, patient, {'revision':changed['revision'],
                                                'records':[confirmed]}, reviewer='Another Pharmacist')
    assert reviewed['verification'][original['id']]['verified_by'] == 'Another Pharmacist'
    assert len(reviewed['history']) == 3
    assert reviewed['history'][1]['before']['value'] == '98'
    assert reviewed['history'][1]['after']['value'] == '120'


def test_legacy_verified_records_retained_without_forged_reviewer(tmp_path, monkeypatch):
    import json
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    legacy = row()
    import records; records.put(conn, 1, 'pathology_records.json', json.dumps({'version':1,'records':[legacy]}).encode()); conn.commit()
    patient={'id':1}
    loaded = pathology_records.load(conn, patient)
    assert loaded['records'] == [legacy]
    assert loaded['verification'] == {}
    assert loaded['version'] == 1
    migrated = pathology_records.save(conn, patient, {'revision':loaded['revision'],'records':[legacy]})
    assert migrated['version'] == 2
    assert migrated['records'] == [legacy]
    assert migrated['verification'] == {}


def test_revision_check_and_write_share_one_write_transaction(tmp_path, monkeypatch):
    """While a save is between its revision check and its write, another connection cannot write."""
    import db
    path = str(tmp_path / 'p.db')
    conn = db.connect(path)
    other = db.connect(path)
    other.execute('PRAGMA busy_timeout=0')
    seen = {}
    real = pathology_records.validate

    def probing_validate(records_):
        if 'locked' in seen:
            return real(records_)  # only the check inside save matters; later calls run after commit
        try:
            other.execute('BEGIN IMMEDIATE')
            other.rollback()
            seen['locked'] = False
        except Exception as exc:
            seen['locked'] = 'locked' in str(exc)
        return real(records_)
    monkeypatch.setattr(pathology_records, 'validate', probing_validate)
    pathology_records.save(conn, {'id': 1}, {'revision': 'missing', 'records': [row()]}, reviewer='Synthetic Pharmacist')
    assert seen['locked'] is True
