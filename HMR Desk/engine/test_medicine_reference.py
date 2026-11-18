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

def _synthetic_db(path, rows):
    from medicine_data import catalog
    db = catalog.connect(path)
    with catalog.snapshot(db, 'syn', '20260101', path, 'https://example.invalid/synthetic'):
        for i, d in enumerate(rows):
            catalog.add_medicine(db, 'syn', 'C%d' % i, d, 'generic', d.split()[0], None, 'tablet', [], {})
    db.commit()
    return db


SYN = ['Synthstatin 20 mg tablet', 'Synthstatin 40 mg tablet (Synthbrand)', 'Alphamed + Betamed 5 mg/10 mg tablet',
       'Caf\u00e9medin 100 \u00b5g tablet', 'Percent 5% cream', 'Under_score 1 mg tablet', 'Synthmed MR 665 mg modified release tablet',
       'Synthsolve 1 g/10 mL oral liquid', 'Zetamed 10 mg capsule', 'Synthstatin 10 mg tablet']
SYN_QUERIES = ['syn', 'Synthstatin', 'statin 40', '(synthbrand)', '(', 'alphamed + beta', 'alphamed/beta', 'caf\u00e9', '\u00b5g', '5%', '%', '_', 'under_', 'a%b',
               'MR 665', 'mg tablet', 'mg/10', 'zz', 'ab', 'SYNTHSTATIN 20', '  synth   med ', '\\', 'tablet (', 'oral liquid', '10 mL']


def test_indexed_search_is_identical_to_plain_scan_and_exact_check_is_indexed():
    import sqlite3
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN)
        plain = {q: catalog.search(db, q, 15) for q in SYN_QUERIES}
        assert any(plain.values())
        assert catalog.build_search_index(db) == {'display': True, 'fts': True}
        assert catalog.build_search_index(db) == {'display': True, 'fts': True}  # idempotent
        db.close()
        ro = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        assert catalog._fts_usable(ro)
        for q in SYN_QUERIES:
            assert catalog.search(ro, q, 15) == plain[q], q
        plan = ' '.join(r[3] for r in ro.execute("EXPLAIN QUERY PLAN SELECT * FROM medicine WHERE lower(display)=?", ('x',)))
        assert 'medicine_display_lower' in plan
        ro.close()


def test_stale_or_missing_fts_falls_back_to_the_plain_scan_and_import_drops_it():
    import sqlite3
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN)
        catalog.build_search_index(db)
        db.execute("INSERT INTO medicine VALUES('syn','NEW','Newmed 5 mg tablet','newmed 5 mg tablet','generic',NULL,NULL,NULL,'[]','{}')")
        db.commit(); catalog._FTS_OK.clear()
        assert not catalog._fts_usable(db)
        assert [r['code'] for r in catalog.search(db, 'newmed', 15)] == ['NEW']  # never hidden by a stale index
        db.execute('DROP TABLE medicine_fts'); catalog._FTS_OK.clear()
        assert [r['code'] for r in catalog.search(db, 'synthstatin 20', 15)] == ['C0']
        catalog.build_search_index(db)
        with catalog.snapshot(db, 'syn', '20260102', str(path), 'https://example.invalid/synthetic'):
            catalog.add_medicine(db, 'syn', 'X1', 'Replacement 1 mg tablet', 'generic')
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='medicine_fts'").fetchone()[0] == 0
        assert [r['code'] for r in catalog.search(db, 'replacement', 15)] == ['X1']
        db.close()


def test_failed_index_step_rejects_install_and_keeps_current_reference():
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t); build(target)
        before = target.read_bytes()
        new = candidate(t)
        real = catalog.build_search_index
        def boom(db):
            db.execute("UPDATE medicine SET display=display||'x'")  # an index step that changes rows must be refused
            return {'display': True, 'fts': False}
        catalog.build_search_index = boom
        try:
            try: ref.install(str(new)); assert False
            except ValueError as exc: assert 'changed medicine rows' in str(exc)
        finally:
            catalog.build_search_index = real
        assert target.read_bytes() == before and ref.status()['installed']
        assert not (Path(t) / 'medicine-reference.sqlite.incoming').exists()


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
        # Rows stay identical to the operator's file; only derived indexes are added to the private copy.
        import sqlite3
        a, b = sqlite3.connect(target), sqlite3.connect(new)
        assert ref._content_hash(a) == ref._content_hash(b)
        assert a.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('medicine_display_lower','medicine_fts')").fetchone()[0] == 2
        assert b.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('medicine_display_lower','medicine_fts')").fetchone()[0] == 0
        a.close(); b.close()
        assert result['search_index'] == {'display': True, 'fts': True}
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
