"""Synthetic medicine reference data only. No licensed terminology is used or bundled."""
from contextlib import closing
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


def _ro(path):
    import sqlite3
    c = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)
    return c


def _plain_vs_indexed(path, queries=None):
    """Returns the queries whose indexed result differs from a forced plain scan of the same file."""
    from medicine_data import catalog
    ro = _ro(path); catalog._TRUST.clear()
    bad = []
    for q in queries or SYN_QUERIES + ['newmed', 'qqqq', 'abcnew', 'replaced']:
        got = catalog.search(ro, q, 15)
        orig = catalog._fts_usable
        catalog._fts_usable = lambda db: False
        try: want = catalog.search(ro, q, 15)
        finally: catalog._fts_usable = orig
        if got != want: bad.append(q)
    ro.close()
    return bad


def test_indexed_search_is_identical_to_plain_scan_and_exact_check_is_indexed():
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN)
        plain = {q: catalog.search(db, q, 15) for q in SYN_QUERIES}
        assert any(plain.values())
        made = catalog.build_search_index(db)
        assert made['display'] and made['fts'] and len(made['content_sha256']) == 64
        assert catalog.build_search_index(db)['fts']  # idempotent rebuild
        db.close()
        ro = _ro(path); catalog._TRUST.clear()
        assert catalog._fts_usable(ro)
        for q in SYN_QUERIES:
            assert catalog.search(ro, q, 15) == plain[q], q
        plan = ' '.join(r[3] for r in ro.execute("EXPLAIN QUERY PLAN SELECT * FROM medicine WHERE lower(display)=?", ('x',)))
        assert 'medicine_display_lower' in plan
        ro.close()
        assert _plain_vs_indexed(path) == []


def _mutations():
    """Each way an index can disagree with the rows while the row COUNT stays the same (or the name is reused)."""
    return {
        'same-count update of search_text': "UPDATE medicine SET search_text='newmed 5 mg tablet', display='Newmed 5 mg tablet' WHERE code='C0'",
        'same-count update, same length': "UPDATE medicine SET search_text=replace(search_text,'synth','qqqqq') WHERE code='C0'",
        'delete and insert, same count': "DELETE FROM medicine WHERE code='C1'; INSERT INTO medicine VALUES('syn','Z9','Abcnew 1 mg tablet','abcnew 1 mg tablet','generic',NULL,NULL,NULL,'[]','{}')",
        'rowid reassigned, same count': "UPDATE medicine SET rowid=rowid+1000 WHERE code='C2'",
    }


def test_same_count_content_changes_never_hide_matches_via_a_stale_index():
    from medicine_data import catalog
    for name, sql in _mutations().items():
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'r.sqlite'
            db = _synthetic_db(str(path), SYN); catalog.build_search_index(db)
            count = db.execute('SELECT count(*) FROM medicine').fetchone()[0]
            db.executescript(sql); db.commit()
            assert db.execute('SELECT count(*) FROM medicine').fetchone()[0] == count, name
            db.close()
            ro = _ro(path); catalog._TRUST.clear()
            assert not catalog._fts_usable(ro), name  # the fingerprint no longer matches
            ro.close()
            assert _plain_vs_indexed(path) == [], name
            # and the new/changed rows are actually findable
            ro = _ro(path)
            found = {q: [r['code'] for r in catalog.search(ro, q, 15)] for q in ('newmed', 'abcnew', 'qqqqq')}
            ro.close()
            assert any(found.values()) or name == 'rowid reassigned, same count', (name, found)


def test_existing_incompatible_objects_under_the_same_names_are_replaced_not_trusted():
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN)
        db.execute("CREATE VIRTUAL TABLE medicine_fts USING fts5(display, content='medicine', content_rowid='rowid', tokenize='unicode61')")
        db.execute("INSERT INTO medicine_fts(medicine_fts) VALUES('rebuild')")
        db.execute('CREATE INDEX medicine_display_lower ON medicine(display)')  # wrong definition, same name
        db.commit()
        catalog._TRUST.clear()
        assert not catalog._fts_usable(db)  # no meta, wrong definition: not trusted
        assert [r['code'] for r in catalog.search(db, 'statin 40', 15)] == ['C1']
        made = catalog.build_search_index(db)
        assert made['fts']
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='medicine_fts'").fetchone()[0].lower()
        assert 'trigram' in sql and 'search_text' in sql
        assert 'lower(display)' in db.execute("SELECT sql FROM sqlite_master WHERE name='medicine_display_lower'").fetchone()[0].lower()
        db.close()
        assert _plain_vs_indexed(path) == []
        # a tampered/forged meta row or wrong version is not trusted either
        w = sqlite3_connect(path); w.execute("UPDATE search_index_meta SET value='deadbeef' WHERE key='content_sha256'"); w.commit(); w.close()
        ro = _ro(path); catalog._TRUST.clear(); assert not catalog._fts_usable(ro); ro.close()
        w = sqlite3_connect(path); w.execute("UPDATE search_index_meta SET value='2' WHERE key='version'"); w.commit(); w.close()
        ro = _ro(path); catalog._TRUST.clear(); assert not catalog._fts_usable(ro); ro.close()


def test_index_swapped_for_an_incompatible_one_after_build_is_not_trusted():
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN); catalog.build_search_index(db)
        db.execute('DROP TABLE medicine_fts')  # rows and meta unchanged; only the live index definition differs
        db.execute("CREATE VIRTUAL TABLE medicine_fts USING fts5(search_text, content='medicine', content_rowid='rowid', tokenize='unicode61')")
        db.execute("INSERT INTO medicine_fts(medicine_fts) VALUES('rebuild')"); db.commit(); db.close()
        ro = _ro(path); catalog._TRUST.clear(); assert not catalog._fts_usable(ro); ro.close()
        assert _plain_vs_indexed(path) == []


def sqlite3_connect(path):
    import sqlite3
    return sqlite3.connect(path)


def test_capability_is_proved_by_execution_and_missing_fts_falls_back():
    from medicine_data import catalog
    assert catalog._fts_check_command_works()  # this SQLite supports trigram and detects a stale index
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN)
        real = catalog._fts_check_command_works
        catalog._fts_check_command_works = lambda: False  # simulate an SQLite without trigram / content check
        try:
            made = catalog.build_search_index(db)
        finally:
            catalog._fts_check_command_works = real
        assert made['display'] and not made['fts'] and made['content_sha256'] is None
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('medicine_fts','search_index_meta')").fetchone()[0] == 0
        catalog._TRUST.clear()
        assert [r['code'] for r in catalog.search(db, 'synthstatin 20', 15)] == ['C0']
        db.close()


def test_import_drops_derived_index_and_meta():
    from medicine_data import catalog
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / 'r.sqlite'
        db = _synthetic_db(str(path), SYN); catalog.build_search_index(db)
        with catalog.snapshot(db, 'syn', '20260102', str(path), 'https://example.invalid/synthetic'):
            catalog.add_medicine(db, 'syn', 'X1', 'Replacement 1 mg tablet', 'generic')
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('medicine_fts','search_index_meta')").fetchone()[0] == 0
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
            return {'display': True, 'fts': False, 'content_sha256': None}
        catalog.build_search_index = boom
        try:
            try: ref.install(str(new)); assert False
            except ValueError as exc: assert 'changed medicine rows' in str(exc)
        finally:
            catalog.build_search_index = real
        assert target.read_bytes() == before and ref.status()['installed']
        assert not (Path(t) / 'medicine-reference.sqlite.incoming').exists()
        assert not ref.status()['installing']


def test_provenance_keeps_source_and_installed_hashes_distinct_and_source_authenticity_untouched():
    import hashlib, json, sqlite3
    with tempfile.TemporaryDirectory() as t:
        target = fresh(t)
        new = candidate(t)
        src_hash = hashlib.sha256(new.read_bytes()).hexdigest()
        with closing(sqlite3.connect(new)) as _c:
            before = _c.execute('SELECT source, release, sha256, source_url, row_count FROM source_release ORDER BY source').fetchall()
        result = ref.install(str(new))
        assert result['provenance_recorded']
        record = json.loads((Path(t) / 'medicine-reference.install.json').read_text(encoding='utf-8'))
        assert record['source_sha256'] == src_hash == hashlib.sha256(new.read_bytes()).hexdigest()
        assert record['installed_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest() != record['source_sha256']
        assert record['installed_bytes'] == target.stat().st_size and record['source_bytes'] == new.stat().st_size
        with closing(sqlite3.connect(target)) as _c:
            after = _c.execute('SELECT source, release, sha256, source_url, row_count FROM source_release ORDER BY source').fetchall()
        assert after == before  # the source import authenticity record is exactly as the operator's file had it


def test_second_install_is_refused_while_one_runs_and_scans_are_bounded():
    import threading
    assert ref._INSTALL_LOCK.acquire(blocking=False)
    try:
        ref._installing = True
        assert ref.status()['installing'] is True
        try: ref.install('/nonexistent.sqlite'); assert False
        except ValueError as exc: assert 'already running' in str(exc)
    finally:
        ref._installing = False; ref._INSTALL_LOCK.release()
    assert ref._SCANS.acquire(blocking=False) and ref._SCANS.acquire(blocking=False)
    assert not ref._SCANS.acquire(blocking=False)  # third concurrent scan must wait
    ref._SCANS.release(); ref._SCANS.release()


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
        assert result['search_index']['display'] and result['search_index']['fts']
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
