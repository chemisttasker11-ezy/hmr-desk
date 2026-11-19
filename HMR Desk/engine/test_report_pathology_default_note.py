"""Synthetic checks: the placeholder note on a source-linked pathology row does not print once the row is verified, a
pharmacist-authored note always prints, and an empty GP gives a neutral salutation instead of 'Dear ,'."""
import uuid

import pathology_records
import report
from test_report_save_revision import _setup, _saved_report

DEFAULT = 'UNVERIFIED \u2014 compare source PDF before confirming'


def _row(test, comment, verified):
    return {'id': uuid.uuid4().hex, 'test': test, 'value': '5.0', 'unit': 'mmol/L', 'reference_interval': '3.0 - 6.0',
            'sample_date': '2026-11-10', 'source': 'synthetic.pdf page 1 sha256:00', 'verified': verified,
            'comment': comment}


def _table(conn, patient, rows, reviewer='Synthetic Reviewer'):
    current = pathology_records.load(conn, patient)
    pathology_records.save(conn, patient, {'revision': current['revision'], 'records': rows}, reviewer)
    derived = report._derived(conn, patient)[1]
    return {r[0]: r[4] for r in derived['path']}


def test_default_note_hidden_for_verified_row_only(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        out = _table(conn, patient, [_row('A verified default', DEFAULT, True), _row('B unverified default', DEFAULT, False)])
        assert 'Verified by Synthetic Reviewer' in out['A verified default']
        assert 'compare source PDF' not in out['A verified default']
        assert 'UNVERIFIED \u2014 check original source' in out['B unverified default']
        assert 'compare source PDF' in out['B unverified default']


def test_authored_note_on_verified_row_is_kept(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        out = _table(conn, patient, [_row('C verified authored', 'Synthetic pharmacist note', True),
                                     _row('D verified edited default', DEFAULT + ' (still checking)', True)])
        assert 'Synthetic pharmacist note' in out['C verified authored']
        assert DEFAULT in out['D verified edited default']


def test_blank_gp_salutation_is_neutral(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, _ = _saved_report(conn)
        record = report.interview.load(conn, patient)
        record['header']['gp'] = ''
        blank = dict(patient, gp='')
        assert report._demographics(conn, blank, record)['dear'] == 'Dear Doctor,'
        named = dict(patient, gp='Dr Synthetic Example')
        assert report._demographics(conn, named, record)['dear'] == 'Dear Dr Synthetic Example,'
