"""Synthetic pathology PDF geometry and unverified-acceptance tests."""
import hashlib

import fitz
import pytest

import db
import jobs
import pathology_import
import pathology_proposals as proposals
import pathology_records


def fixture(path, *, dated=False, missing_date=False, report_date=False):
    with fitz.open() as pdf:
        p = pdf.new_page()
        p.insert_text((44, 35), 'SYNTHETIC - NOT A PATIENT RESULT')
        if not dated and not missing_date:
            p.insert_text((44, 65), 'Collected: 12/11/2026')
        if report_date:
            p.insert_text((350, 65), 'Reported: 14/11/2026')
        if dated:
            columns = [(44, 'Test'), (205, '12/11/2026'), (315, '01/10/2026'),
                       (435, 'Units'), (515, 'Reference')]
            rows = [('Creatinine', '98', '112', 'umol/L', '50-120'),
                    ('eGFR', '>90', '68', 'mL/min/1.73m2', '>=60')]
        else:
            columns = [(44, 'Test'), (220, 'Result'), (365, 'Units'), (485, 'Reference')]
            rows = [('Total calcium', '2.41 H', 'mmol/L', '2.20-2.60'),
                    ('Corrected calcium', '2.36', 'mmol/L', '2.15-2.60')]
        for x, text in columns:
            p.insert_text((x, 100), text)
        for i, cells in enumerate(rows):
            for (x, _), value in zip(columns, cells):
                p.insert_text((x, 130 + 30*i), value, fontsize=9)
        pdf.save(path)


def test_digital_one_column_and_distinct_analytes(tmp_path):
    path = tmp_path / 'one.pdf'
    fixture(path, report_date=True)
    with fitz.open(path) as pdf:
        rows, issues = proposals._page_proposals(pdf[0], 'a'*32, hashlib.sha256(path.read_bytes()).hexdigest())
    assert not issues and len(rows) == 2
    assert [r['fields']['test'] for r in rows] == ['Total calcium', 'Corrected calcium']
    assert [r['fields']['value'] for r in rows] == ['2.41', '2.36']
    assert rows[0]['raw_text']['value'] == '2.41 H'
    assert rows[0]['field_uncertainty']['value']
    assert rows[0]['fields']['sample_date'] == '2026-11-12'
    assert rows[0]['fields']['unit'] == 'mmol/L'
    assert rows[0]['cell_bbox']['value']
    assert rows[0]['id'] != rows[1]['id']


def test_two_dated_columns_preserve_both_results(tmp_path):
    path = tmp_path / 'dates.pdf'
    fixture(path, dated=True)
    with fitz.open(path) as pdf:
        rows, issues = proposals._page_proposals(pdf[0], 'a'*32, hashlib.sha256(path.read_bytes()).hexdigest())
    assert not issues and len(rows) == 4
    creat = [r for r in rows if r['fields']['test'] == 'Creatinine']
    assert [r['fields']['sample_date'] for r in creat] == ['2026-11-12', '2026-10-01']
    assert [r['fields']['value'] for r in creat] == ['98', '112']
    assert creat[0]['source_column_label'] == '12/11/2026'
    assert creat[1]['source_column_label'] == '01/10/2026'
    assert len({r['id'] for r in rows}) == 4


def test_report_date_never_implies_collection_date(tmp_path):
    path = tmp_path / 'report-only.pdf'
    fixture(path, missing_date=True, report_date=True)
    with fitz.open(path) as pdf:
        rows, _ = proposals._page_proposals(pdf[0], 'a'*32, hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(rows) == 2
    assert all(not r['fields']['sample_date'] and 'sample_date' in r['field_uncertainty'] for r in rows)


@pytest.fixture
def case(tmp_path, monkeypatch):
    folder = tmp_path / 'patient'
    folder.mkdir()
    monkeypatch.setattr(jobs, 'patient_folder', lambda p: folder)
    conn = db.connect(str(tmp_path / 'records.db'))
    path = tmp_path / 'source.pdf'
    fixture(path)
    source = pathology_import.import_pdf(conn, {'id': 1}, str(path))
    return conn, folder, source


def test_propose_then_accept_is_unverified_revision_checked_and_idempotent(case):
    conn, folder, source = case
    person = {'id': 1}
    response = proposals.for_source(conn, person, source['id'])
    assert len(response['proposals']) == 2
    assert pathology_records.load(conn, person)['records'] == []
    r = response['proposals'][0]
    request = {'proposal_id': r['id'], 'source_sha256': source['sha256'],
               'revision': response['records_revision'], 'fields': dict(r['fields'])}
    result = proposals.accept(conn, person, source['id'], request)
    assert result['record']['verified'] is False
    assert result['records']['verification'] == {}
    assert 'cell:' + r['id'] in result['record']['source']
    assert len(result['records']['records']) == 1
    with pytest.raises(ValueError, match='changed; reload'):
        proposals.accept(conn, person, source['id'], request)
    modified = folder / 'Pathology' / source['name']
    with modified.open('ab') as output:
        output.write(b'changed')
    with pytest.raises(ValueError, match='bytes changed'):
        proposals.for_source(conn, person, source['id'])
    with pytest.raises(ValueError, match='bytes changed'):
        proposals.accept(conn, person, source['id'], request)


def test_other_patient_source_rejected_and_scan_abstains(tmp_path, monkeypatch):
    folders = {1: tmp_path/'one', 2: tmp_path/'two'}
    for folder in folders.values():
        folder.mkdir()
    monkeypatch.setattr(jobs, 'patient_folder', lambda p: folders[p['id']])
    conn = db.connect(str(tmp_path / 'records.db'))
    path = tmp_path / 'one.pdf'
    fixture(path)
    source = pathology_import.import_pdf(conn, {'id': 1}, str(path))
    with pytest.raises(ValueError, match='not found for this patient'):
        proposals.for_source(conn, {'id': 2}, source['id'])
    blank = tmp_path / 'scan.pdf'
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(blank)
    scanned = pathology_import.import_pdf(conn, {'id': 1}, str(blank))
    response = proposals.for_source(conn, {'id': 1}, scanned['id'])
    assert response['proposals'] == []
    assert response['pages'][0]['status'] == 'unavailable'
