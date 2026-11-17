import datetime as dt
import json
import unittest
from decimal import Decimal

import pathology_values as pv
import pathology_records
import suggestion_context as sc
from test_medicine_snapshot import setup


class PathologyValueParsingTests(unittest.TestCase):
    def test_explicit_values_parse(self):
        assert pv.parse_value('4.1') == ('=', Decimal('4.1'))
        assert pv.parse_value('44') == ('=', Decimal('44'))
        assert pv.parse_value('<0.5') == ('<', Decimal('0.5'))
        assert pv.parse_value('>= 60') == ('>=', Decimal('60'))

    def test_free_text_values_never_guessed(self):
        for text in ('positive', 'trace', 'see report', '4.1 (H)', 'approx 4', '', None,
                     '4,1', '1,024', '4.1.2'):
            assert pv.parse_value(text) is None

    def test_nonfinite_and_oversized_numbers_never_parse(self):
        assert pv.parse_value('9' * 400) is None
        assert pv.parse_value('1' * 21) is None
        assert pv.parse_value('nan') is None
        assert pv.parse_value('inf') is None
        assert pv.parse_value('-5') is None  # sign form not modelled; stays free text
        assert pv.parse_value('1e5') is None  # scientific notation not modelled

    def test_intervals_parse_with_inclusivity(self):
        assert pv.parse_interval('3.5-5.2') == ((Decimal('3.5'), True), (Decimal('5.2'), True))
        assert pv.parse_interval('< 60') == (None, (Decimal('60'), False))
        assert pv.parse_interval('<=60') == (None, (Decimal('60'), True))
        assert pv.parse_interval('>90') == ((Decimal('90'), False), None)
        assert pv.parse_interval('>= 90') == ((Decimal('90'), True), None)

    def test_intervals_never_guessed(self):
        for text in ('5.2-3.5', 'normal', '3.5 - 5.2 mmol/L', '3.5,5.2', '', None,
                     'M: 4-6 F: 3-5', '60-120 (age adjusted)', '< 60 mL/min'):
            assert pv.parse_interval(text) is None

    def test_interval_digit_overflow_never_parses(self):
        assert pv.parse_interval('%s-5.2' % ('9' * 400)) is None
        assert pv.parse_interval('< %s' % ('9' * 400)) is None


class PathologyPositionTests(unittest.TestCase):
    def test_between_bounds_are_inclusive(self):
        iv = pv.parse_interval('3.5-5.2')
        assert pv.position(('=', Decimal('3.5')), iv) == 'within'
        assert pv.position(('=', Decimal('5.2')), iv) == 'within'
        assert pv.position(('=', Decimal('3.4')), iv) == 'below'
        assert pv.position(('=', Decimal('5.3')), iv) == 'above'

    def test_exact_endpoints_for_all_four_comparators(self):
        assert pv.position(('=', Decimal('60.0')), pv.parse_interval('< 60')) == 'above'
        assert pv.position(('=', Decimal('60.0')), pv.parse_interval('<= 60')) == 'within'
        assert pv.position(('=', Decimal('60.0')), pv.parse_interval('> 60')) == 'below'
        assert pv.position(('=', Decimal('60.0')), pv.parse_interval('>= 60')) == 'within'
        assert pv.position(('=', Decimal('59.9')), pv.parse_interval('< 60')) == 'within'
        assert pv.position(('=', Decimal('60.1')), pv.parse_interval('> 60')) == 'within'

    def test_position_undetermined_for_inexact_or_missing(self):
        assert pv.position(('<', Decimal('0.5')), pv.parse_interval('3.5-5.2')) == 'undetermined'
        assert pv.position(('=', Decimal('4.1')), None) == 'undetermined'
        assert pv.position(None, pv.parse_interval('3.5-5.2')) == 'undetermined'


class PathologyStructureTests(unittest.TestCase):
    def test_structure_combines_and_labels_basis(self):
        s = pv.structure('6.0', '3.5-5.2', 'mmol/L')
        assert s['value_number'] == 6.0 and s['range_position'] == 'above'
        assert s['raw_value'] == '6.0' and s['raw_interval'] == '3.5-5.2' and s['unit'] == 'mmol/L'
        assert s['value_exact'] == '6.0' and s['interval_low_exact'] == '3.5' and s['interval_high_exact'] == '5.2'
        json.dumps(s, allow_nan=False)
        assert s['undetermined_reason'] == ''
        assert 'laboratory range position only' in s['basis']
        assert 'not a renal dosing' in s['basis']

    def test_missing_unit_is_undetermined_even_with_clean_numbers(self):
        s = pv.structure('6.0', '3.5-5.2', '')
        assert s['range_position'] == 'undetermined'
        assert 'unit not recorded' in s['undetermined_reason']

    def test_reasons_preserve_why_undetermined(self):
        s = pv.structure('<0.5', 'see report', '')
        assert s['range_position'] == 'undetermined'
        assert 'comparator result cannot be positioned exactly' in s['undetermined_reason']
        assert 'reference interval not an explicit numeric range' in s['undetermined_reason']
        assert 'unit not recorded' in s['undetermined_reason']

    def test_structure_none_when_nothing_explicit(self):
        assert pv.structure('see report', 'normal', 'mmol/L') is None

    def test_json_never_carries_nan_or_infinity(self):
        for value, interval in (('9' * 400, '<60'), ('4.1', '9' * 400 + '-5'), ('<0.5', '3.5-5.2'),
                                ('60', '<60'), ('4.1', '')):
            s = pv.structure(value, interval, 'mmol/L')
            if s is not None:
                json.dumps(s, allow_nan=False)  # raises on NaN/Infinity

    def test_precision_safe_arithmetic(self):
        # 0.3-0.7 style decimals: float representation must not shift endpoints.
        iv = pv.parse_interval('0.1-0.3')
        assert pv.position(('=', Decimal('0.3')), iv) == 'within'
        assert pv.position(('=', Decimal('0.3000000001')), pv.parse_interval('0.1-0.3')) == 'above'
        # Beyond float64 resolution: exact decimals keep the distinction.
        assert pv.position(('=', Decimal('0.30000000000000000001')), pv.parse_interval('0.1-0.3')) == 'above'


def _save_pathology(conn, p, **updates):
    row = dict(id='d' * 32, test='eGFR', value='41', unit='mL/min/1.73m2',
               reference_interval='60-120', sample_date='2026-11-01',
               source='synthetic-lab.pdf page 2', verified=True, comment='')
    row.update(updates)
    return pathology_records.save(conn, p, {'revision': pathology_records.revision(conn, p),
                                            'records': [row]}, reviewer='Synthetic Reviewer')


def test_context_carries_structured_view_only_when_explicit(setup):
    conn, p, _ = setup
    _save_pathology(conn, p)
    c = sc.build(conn, p, dt.date(2026, 11, 17))
    lab = next(e for e in c['evidence'] if e['id'] == 'pathology:' + 'd' * 32)
    assert lab['structured']['value_number'] == 41.0
    assert lab['structured']['interval_low'] == 60.0
    assert lab['structured']['range_position'] == 'below'
    assert lab['structured']['unit'] == 'mL/min/1.73m2'
    assert 'laboratory range position only' in lab['structured']['basis']


def test_context_leaves_free_text_results_unstructured(setup):
    conn, p, _ = setup
    _save_pathology(conn, p, id='e' * 32, value='see report', reference_interval='')
    c = sc.build(conn, p, dt.date(2026, 11, 17))
    lab = next(e for e in c['evidence'] if e['id'] == 'pathology:' + 'e' * 32)
    assert lab['structured'] == {}
    assert lab['text'] == 'eGFR: see report'


if __name__ == '__main__':
    unittest.main()
