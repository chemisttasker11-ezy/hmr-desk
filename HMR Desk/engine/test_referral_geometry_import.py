"""Importer use of the position-based medicines table. Synthetic data only."""
import pytest
fitz = pytest.importorskip('fitz')
import interview
import referral


def geo(**kw):
    base = {'ok': True, 'reason': '', 'rows': [['Alphadrug 50mg Tablet', '1 Taplet In the morning.'], ['Betadrug 5mg Tablet', '2 Tablets Daily.']],
            'source_lines': [['Alphadrug 50mg Tablet', '1 Taplet In the morning.'], ['Betadrug 5mg Tablet', '2 Tablets Daily.']],
            'excluded': [], 'flags': [], 'scanned_pages': []}
    base.update(kw); return base


def found():
    return {'meds': [('Alphadrug 50mg Tablet', ''), ('Betadrug 5mg Tablet', '2 Tablets Daily.')], 'unattributed_directions': ['1 Taplet In the morning.'],
            'unparsed': ['meds'], 'medicine_source_lines': []}


def test_clean_geometry_replaces_the_text_order_read_and_keeps_the_old_read_visible():
    f = found(); interview.apply_geometry(f, geo())
    assert f['meds'][0] == ('Alphadrug 50mg Tablet', '1 Taplet In the morning.')      # verbatim: no correction of "Taplet"
    assert f['unattributed_directions'] == [] and 'meds' not in f['unparsed']
    notes = ' '.join(f['geometry_notes'])
    assert 'replaced the text-order read' in notes and 'Text-order read was' in notes
    assert 'unusual word' in notes and 'Taplet' in notes                                  # flagged, not fixed


def test_scanned_pages_always_produce_a_check_every_row_note():
    f = found(); interview.apply_geometry(f, geo(scanned_pages=[1, 2]))
    assert any('images with a text layer' in n and '1, 2' in n for n in f['geometry_notes'])


def test_failed_geometry_keeps_the_text_path_and_says_why():
    f = found(); interview.apply_geometry(f, geo(ok=False, reason='page 2 does not start with a different section heading, so the table may continue there', rows=[]))
    assert f['unattributed_directions'] == ['1 Taplet In the morning.'] and 'meds' in f['unparsed']
    assert any('not read by page position' in n and 'may continue' in n for n in f['geometry_notes'])


def test_geometry_with_flags_is_not_used():
    f = found(); interview.apply_geometry(f, geo(flags=['row 1 name has no recognisable strength']))
    assert f['meds'][0] == ('Alphadrug 50mg Tablet', '') and any('was not used' in n for n in f['geometry_notes'])


def test_excluded_lines_are_listed_for_review():
    f = found(); interview.apply_geometry(f, geo(excluded=['Template footer line']))
    assert any('Template footer line' in n and 'page furniture' in n for n in f['geometry_notes'])


def test_no_geometry_changes_nothing():
    f = found(); before = repr(f); interview.apply_geometry(f, None)
    assert f['meds'] == found()['meds'] and f['unattributed_directions']


def test_geometry_table_end_to_end_on_a_synthetic_referral(tmp_path):
    doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for name, d in [('Alphadrug 50mg Tablet', '1 Taplet In the morning.'), ('Betadrug 5mg Tablet', '2 Tablets Daily.')]:
        page.insert_text((50, y), name, fontsize=10); page.insert_text((300, y), d, fontsize=10); y += 14
    page.insert_text((50, 800), 'Page 1', fontsize=9)
    doc.save(str(tmp_path / 'referral.pdf'))
    result = interview.geometry_table(tmp_path)
    assert result and result['ok'] and result['rows'][0] == ['Alphadrug 50mg Tablet', '1 Taplet In the morning.'] and result['scanned_pages'] == []
