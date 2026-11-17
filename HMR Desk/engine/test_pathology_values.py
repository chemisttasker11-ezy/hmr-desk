import datetime as dt
import unittest

import pathology_values as pv
import pathology_records
import suggestion_context as sc
from test_medicine_snapshot import setup


class PathologyValueStructuringTests(unittest.TestCase):
    def test_explicit_values_parse(self):
        assert pv.parse_value('4.1') == ('=', 4.1)
        assert pv.parse_value('44') == ('=', 44.0)
        assert pv.parse_value('<0.5') == ('<', 0.5)
        assert pv.parse_value('>= 60') == ('>=', 60.0)

    def test_free_text_values_never_guessed(self):
        for text in ('positive', 'trace', 'see report', '4.1 (H)', 'approx 4', '', None):
            assert pv.parse_value(text) is None

    def test_intervals_parse_from_lab_text(self):
        assert pv.parse_interval('3.5-5.2') == (3.5, 5.2)
        assert pv.parse_interval('0.0 - 4.0') == (0.0, 4.0)
        assert pv.parse_interval('< 60') == (None, 60.0)
        assert pv.parse_interval('>=90') == (90.0, None)

    def test_intervals_never_guessed(self):
        for text in ('5.2-3.5', 'normal', '3.5 - 5.2 mmol/L', '3.5,5.2', '', None):
            assert pv.parse_interval(text) is None

    def test_position_is_arithmetic_on_lab_interval(self):
        assert pv.position(('=', 3.0), (3.5, 5.2)) == 'below'
        assert pv.position(('=', 4.1), (3.5, 5.2)) == 'within'
        assert pv.position(('=', 6.0), (3.5, 5.2)) == 'above'
        assert pv.position(('=', 3.0), (3.5, None)) == 'below'
        assert pv.position(('=', 6.0), (None, 5.2)) == 'above'
        assert pv.position(('=', 3.0), (None, 60.0)) == 'within'

    def test_position_undetermined_for_inexact_or_missing(self):
        assert pv.position(('<', 0.5), (3.5, 5.2)) == 'undetermined'
        assert pv.position(('=', 4.1), None) == 'undetermined'
        assert pv.position(None, (3.5, 5.2)) == 'undetermined'

    def test_structure_combines_and_labels_basis(self):
        s = pv.structure('6.0', '3.5-5.2')
        assert s['value_number'] == 6.0 and s['range_position'] == 'above'
        assert 'laboratory' in s['basis']
        assert pv.structure('see report', 'normal') is None


if __name__ == '__main__':
    unittest.main()


def _save_pathology(conn, p, **updates):
    row = dict(id='d'*32, test='eGFR', value='41', unit='mL/min/1.73m2',
               reference_interval='60-120', sample_date='2026-11-01',
               source='synthetic-lab.pdf page 2', verified=True, comment='')
    row.update(updates)
    return pathology_records.save(conn, p, {'revision': pathology_records.revision(conn, p),
                                            'records': [row]}, reviewer='Synthetic Reviewer')


def test_context_carries_structured_view_only_when_explicit(setup):
    conn, p, _ = setup
    _save_pathology(conn, p)
    c = sc.build(conn, p, dt.date(2026, 11, 17))
    lab = next(e for e in c['evidence'] if e['id'] == 'pathology:' + 'd'*32)
    assert lab['structured']['value_number'] == 41.0
    assert lab['structured']['interval_low'] == 60.0
    assert lab['structured']['range_position'] == 'below'
    assert 'laboratory' in lab['structured']['basis']


def test_context_leaves_free_text_results_unstructured(setup):
    conn, p, _ = setup
    _save_pathology(conn, p, id='e'*32, value='see report', reference_interval='')
    c = sc.build(conn, p, dt.date(2026, 11, 17))
    lab = next(e for e in c['evidence'] if e['id'] == 'pathology:' + 'e'*32)
    assert lab['structured'] == {}
    # Free text and comment matching behaviour are untouched.
    assert lab['text'] == 'eGFR: see report'


if __name__ == '__main__':
    unittest.main()
