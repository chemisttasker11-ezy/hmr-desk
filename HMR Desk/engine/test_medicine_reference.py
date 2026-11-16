"""Synthetic medicine reference data only. No licensed terminology is used or bundled."""
import os, sys, tempfile, sqlite3
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import db
from medicine_data import catalog
import medicine_reference as ref

def fresh(tmp):
    db.DATA_DIR = str(tmp)
    return ref.reference_path()

def build(path):
    conn = catalog.connect(path)
    src = Path(path).with_name('synthetic.txt'); src.write_text('x')
    with catalog.snapshot(conn, 'amt', '20260101', src, 'https://example.invalid/synthetic'):
        catalog.add_medicine(conn, 'amt', '1001', 'Examplestatin 20 mg tablet', 'MPUU', generic='Examplestatin 20 mg tablet', form='Tablet')
        catalog.add_medicine(conn, 'amt', '1002', 'Samplecor (Brandex) 5 mg tablet', 'TPUU', brand='Brandex', aliases=['sampleprilol'])
    conn.close()

def test_missing_reference_is_a_normal_state():
    with tempfile.TemporaryDirectory() as t:
        fresh(t)
        assert ref.status()['installed'] is False
        assert ref.search('exam') == {'installed': False, 'results': []}
        assert ref.pick('amt', '1001') is None

def test_search_status_and_pick():
    with tempfile.TemporaryDirectory() as t:
        build(fresh(t))
        s = ref.status()
        assert s['installed'] and s['sources'][0]['release'] == '20260101' and s['sources'][0]['row_count'] == 2
        found = ref.search('EXAMPLESTATIN')['results']
        assert [r['code'] for r in found] == ['1001'] and found[0]['release'] == '20260101'
        assert [r['code'] for r in ref.search('brandex')['results']] == ['1002']
        assert [r['code'] for r in ref.search('sampleprilol')['results']] == ['1002']
        assert ref.search('x')['results'] == []
        assert ref.pick('amt', '1002')['display'].startswith('Samplecor')
        assert ref.pick('amt', '9999') is None

def test_wildcards_are_literal_and_file_is_read_only():
    with tempfile.TemporaryDirectory() as t:
        path = fresh(t); build(path)
        assert ref.search('%%')['results'] == [] and ref.search('__')['results'] == []
        before = path.stat().st_mtime_ns
        ref.search('exam'); ref.status()
        assert path.stat().st_mtime_ns == before

def test_unreadable_reference_degrades():
    with tempfile.TemporaryDirectory() as t:
        path = fresh(t); path.write_bytes(b'not a database at all' * 50)
        assert ref.status()['installed'] is False
        assert ref.search('exam')['installed'] is False

if __name__ == '__main__':
    for n, f in list(globals().items()):
        if n.startswith('test_'): f()
    print('ok')
