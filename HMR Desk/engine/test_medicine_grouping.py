"""Synthetic PBS-shaped rows only. Grouping must never guess an equivalence."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import db
from medicine_data import catalog
import medicine_reference as ref
import medicine_grouping as mg
import api


def pbs(code, brand='Brandex', generic='Examplestatin', form='20 mg tablet, 30', pack='30', program='GE', **extra):
    d = {'pbs_listed': True, 'schedule_form': form, 'li_form': 'Tablet', 'pack_size': pack,
         'program_code': program, 'pbs_code': code}
    d.update(extra)
    return {'source': 'pbs', 'code': f'{program}:{code}:{code}9', 'display': f'{brand} | {form} | {code}',
            'kind': 'pbs_listing', 'generic_name': generic, 'brand_name': brand, 'dose_form': None,
            'release': '20260101', 'details': d}


def build(path, rows):
    conn = catalog.connect(path)
    src = Path(path).with_name('synthetic.txt'); src.write_text('x')
    with catalog.snapshot(conn, 'pbs', '20260101', src, 'https://example.invalid/synthetic'):
        for r in rows:
            catalog.add_medicine(conn, r['source'], r['code'], r['display'], r['kind'], generic=r['generic_name'],
                                 brand=r['brand_name'], form=r['dose_form'], details=r['details'])
    conn.close()


def test_same_product_different_pbs_codes_share_one_group_and_keep_listings():
    rows = [pbs('1001A'), pbs('1002B'), pbs('1003C', program='S100')]
    groups, more = mg.group_rows(rows, 15)
    assert len(groups) == 1 and not more and groups[0]['grouped']
    assert [l['pbs_code'] for l in groups[0]['listings']] == ['1001A', '1002B', '1003C']
    assert [l['program_code'] for l in groups[0]['listings']] == ['GE', 'GE', 'S100']
    assert groups[0]['label'] == 'Brandex | 20 mg tablet, 30'


def test_strength_form_pack_brand_and_generic_differences_stay_separate():
    rows = [pbs('1'), pbs('2', form='40 mg tablet, 30'), pbs('3', pack='60'), pbs('4', brand='Otherbrand'),
            pbs('5', generic='Examplestatin calcium'), pbs('6', manner_of_administration='ORAL')]
    groups, _ = mg.group_rows(rows, 15)
    assert len(groups) == 6 and not any(g['count'] > 1 for g in mg.finish(groups))


def test_strength_text_is_not_parsed_as_equivalent():
    groups, _ = mg.group_rows([pbs('1', form='20 mg tablet'), pbs('2', form='20mg tablet'), pbs('3', form='0.02 g tablet')], 15)
    assert len(groups) == 3


def test_uncertain_metadata_is_never_grouped():
    blank = lambda code: {**pbs(code), 'details': {'pbs_listed': True, 'pbs_code': code}}
    nobrand = lambda code: {**pbs(code), 'brand_name': None}
    nullform = lambda code: {**pbs(code, form='NULL'), 'details': {**pbs(code, form='NULL')['details'], 'li_form': ''}}
    other = lambda code: {**pbs(code), 'kind': 'TPUU'}
    notlisted = lambda code: {**pbs(code), 'details': {**pbs(code)['details'], 'pbs_listed': False}}
    for make in (blank, nobrand, nullform, other, notlisted):
        groups, _ = mg.group_rows([make('1'), make('2')], 15)
        assert len(groups) == 2, make.__name__


def test_bad_details_json_is_uncertain_not_an_error():
    r = pbs('1'); r['details'] = '{not json'
    assert mg.identity_key(r) is None


def test_non_pbs_sources_are_untouched_even_when_identical():
    a = {**pbs('1'), 'source': 'amt', 'kind': 'TPP'}; b = {**pbs('2'), 'source': 'amt', 'kind': 'TPP'}
    assert len(mg.group_rows([a, b], 15)[0]) == 2


def test_grouping_before_limit_keeps_distinct_matches_visible():
    with tempfile.TemporaryDirectory() as t:
        db.DATA_DIR = t
        rows = [pbs(f'{n:04d}X', brand='Aaa Brand') for n in range(60)]
        rows += [pbs('9001Z', brand='Zzz Brand', generic='Examplestatin')]
        build(ref.reference_path(), rows)
        flat = ref.search('examplestatin')
        assert len(flat['results']) == 15 and not any('9001Z' in r['display'] for r in flat['results'])
        out = ref.search_grouped('examplestatin')
        assert [g['count'] for g in out['groups']] == [60, 1]
        assert out['groups'][1]['listings'][0]['pbs_code'] == '9001Z'
        assert out['more_available'] is False


def test_group_limit_and_more_available():
    rows = [pbs(f'{n}', brand=f'Brand{n:02d}') for n in range(5)]
    groups, more = mg.group_rows(rows, 3)
    assert len(groups) == 3 and more is True


def test_listing_keeps_source_code_release_for_provenance_and_search_route_is_additive():
    with tempfile.TemporaryDirectory() as t:
        db.DATA_DIR = t
        build(ref.reference_path(), [pbs('1001A'), pbs('1002B')])
        out = ref.search_grouped('brandex')
        l = out['groups'][0]['listings'][0]
        assert (l['source'], l['code'], l['release']) == ('pbs', 'GE:1001A:1001A9', '20260101')
        assert ref.pick(l['source'], l['code'])['display'] == l['display']
        plain = ref.search('brandex')
        assert 'groups' not in plain and len(plain['results']) == 2


def test_uninstalled_grouped_search_is_a_normal_state():
    with tempfile.TemporaryDirectory() as t:
        db.DATA_DIR = t
        assert ref.search_grouped('exam') == {'installed': False, 'results': [], 'groups': []}


def test_search_route_grouped_flag_is_opt_in():
    with tempfile.TemporaryDirectory() as t:
        db.DATA_DIR = t
        build(ref.reference_path(), [pbs('1001A'), pbs('1002B')])
        conn = db.connect() if hasattr(db, 'connect') else None
        s, plain = api.handle(conn, 'GET', '/api/medicines/search', {'q': ['brandex']}, None)
        s2, grouped = api.handle(conn, 'GET', '/api/medicines/search', {'q': ['brandex'], 'grouped': ['1']}, None)
        assert s == s2 == 200 and 'groups' not in plain and len(grouped['groups']) == 1 and grouped['groups'][0]['count'] == 2
