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

def test_chosen_reference_is_validated_and_carried_into_report_rows():
    import interview
    ref = {'source': 'amt', 'code': '1001', 'display': 'Examplestatin 20 mg tablet', 'release': '20260101'}
    ok = {'packed': '', 'as_instructed': False, 'checked': False, 'priority': 0, 'reference': ref}
    assert interview.valid_use(ok, {'packed', 'as_instructed', 'checked', 'priority'}, {'prn_use'})
    assert interview.valid_use({'checked': False, 'priority': 0, 'reference': ref}, {'checked', 'priority'}, {'kind'})
    for bad in ({**ref, 'extra': 'x'}, {**ref, 'code': ''}, {**ref, 'code': 5}, 'amt 1001', {k: v for k, v in ref.items() if k != 'release'}):
        assert not interview.valid_use({**ok, 'reference': bad}, {'packed', 'as_instructed', 'checked', 'priority'}, {'prn_use'})
    rows = interview.medicine_rows({'meds': [['Examplestatin', '1 daily', '', '', '']], 'details': {'meds': [ok]}})
    assert 'Reference: Examplestatin 20 mg tablet (AMT 1001, release 20260101)' in rows[0][4]
    plain = interview.medicine_rows({'meds': [['Free text', '', '', '', '']], 'details': {'meds': [{'packed': '', 'as_instructed': False}]}})
    assert 'Reference' not in plain[0][4]

def test_reconciliation_flags_same_concept_under_different_names():
    import reconciliation
    ref = {'source': 'amt', 'code': '1001', 'display': 'Examplestatin 20 mg tablet', 'release': '20260101'}
    meta = lambda r=None: {'packed': '', 'as_instructed': False, 'checked': False, 'priority': 0, **({'reference': r} if r else {})}
    record = {'meds': [['Examplestatin', '', '', '', ''], ['Brandex', '', '', '', '']], 'other_meds': [],
              'details': {'meds': [meta(ref), meta(ref)], 'other_meds': []}}
    codes = [(f['code'], f['medicine_id']) for f in reconciliation.audit(record)['flags']]
    assert ('possible_duplicate_concept', 'meds:0') in codes and ('possible_duplicate_concept', 'meds:1') in codes
    record['details']['meds'][1] = meta()
    assert not [f for f in reconciliation.audit(record)['flags'] if f['code'] == 'possible_duplicate_concept']
    # linking or unlinking changes the reviewed digest, so a prior acknowledgement goes stale
    linked = {**record, 'details': {'meds': [meta(ref), meta(ref)], 'other_meds': []}}
    assert reconciliation.digest(record) != reconciliation.digest(linked)

if __name__ == '__main__':
    for n, f in list(globals().items()):
        if n.startswith('test_'): f()
    print('ok')

def candidate(tmp_dir, name='candidate.sqlite', release='20260201', code='2001'):
    path = Path(tmp_dir) / name
    build(path)
    return path

def test_install_validates_and_replaces_atomically():
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t)
        build(target)
        assert ref.status()['sources'][0]['release'] == '20260101'
        new = candidate(t)
        result = ref.install(str(new))
        assert result['installed'] and result['sources'][0]['source'] == 'amt'
        assert ref.status()['installed']
        assert target.read_bytes() == new.read_bytes()
        previous = Path(t) / 'medicine-reference.previous.sqlite'
        assert previous.is_file() and previous.stat().st_size > 0
        assert ref.search('examplestatin')['results']

def test_rejected_candidate_preserves_working_reference():
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t)
        build(target)
        before = target.read_bytes()
        bad = Path(t) / 'empty.sqlite'
        conn = sqlite3.connect(bad); conn.execute('CREATE TABLE x(y)'); conn.close()
        for source in (str(bad), str(Path(t) / 'missing.sqlite'), str(Path(t) / 'not-a-db.sqlite')):
            if source.endswith('not-a-db.sqlite'):
                Path(source).write_bytes(b'junk' * 1000)
            try:
                ref.install(source)
                assert False, source
            except ValueError:
                pass
        assert target.read_bytes() == before
        assert ref.status()['installed']
        assert not (Path(t) / 'medicine-reference.sqlite.incoming').exists()

def test_install_rejects_wrong_shape_and_missing_content():
    with tempfile.TemporaryDirectory() as t:
        fresh(t)
        wrong_ext = Path(t) / 'reference.db'; build(wrong_ext)
        try:
            ref.install(str(wrong_ext)); assert False
        except ValueError: pass
        no_medicines = Path(t) / 'no-medicines.sqlite'
        conn = sqlite3.connect(no_medicines); conn.executescript(catalog.SCHEMA); conn.close()
        try:
            ref.install(str(no_medicines)); assert False
        except ValueError as e:
            assert 'sources' in str(e) or 'records' in str(e)
        assert ref.status()['installed'] is False

def test_install_refuses_target_as_source(tmp_path=None):
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t)
        build(target)
        try:
            ref.install(str(target)); assert False
        except ValueError as e:
            assert 'already the installed reference' in str(e)


def test_install_first_time_reports_no_previous_retained():
    with tempfile.TemporaryDirectory() as t:
        fresh(t)
        new = candidate(t)
        result = ref.install(str(new))
        assert result['previous_retained'] is False
        assert not (Path(t) / 'medicine-reference.previous.sqlite').exists()


def test_install_replace_reports_previous_retained():
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t)
        build(target)
        new = candidate(t)
        result = ref.install(str(new))
        assert result['previous_retained'] is True
        assert (Path(t) / 'medicine-reference.previous.sqlite').exists()
