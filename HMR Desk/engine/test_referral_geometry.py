"""Table-aware pairing, on synthetic PDFs built here (no patient material)."""
import pytest
fitz = pytest.importorskip('fitz')
import referral_geometry as g

ROWS = [('Alphadrug 50mg Tablet', '1 Tablet Daily'), ('Betadrug 10mg Capsule', None), ('Gammadrug 200/25 Powder for', '2 Puffs Twice a day'),
        ('Deltadrug 5mg Tablet', '1 Tablet In the evening')]


def make(path, rows=ROWS, wrap=True, columns_first=False):
    doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for name, d in rows:
        page.insert_text((50, y), name.split(' Powder for')[0] + (' Powder for' if 'Powder for' in name else ''), fontsize=10)
        if 'Powder for' in name and wrap: page.insert_text((50, y + 12), 'inhalation', fontsize=10)
        if d: page.insert_text((320, y), d, fontsize=10)
        y += 36 if 'Powder for' in name and wrap else 24
    page.insert_text((50, y + 20), 'Allergies', fontsize=11)
    doc.save(path); doc.close()


def pair(path):
    [(n, result, words)] = g.analyse_pdf(path)
    return result


def test_directions_pair_by_row_and_wrapped_names_join(tmp_path):
    rows = [r for r in ROWS if r[1]]
    p = str(tmp_path / 'a.pdf'); make(p, rows)
    r = pair(p)
    assert r['ok'], r
    assert r['rows'] == [['Alphadrug 50mg Tablet', '1 Tablet Daily'], ['Gammadrug 200/25 Powder for inhalation', '2 Puffs Twice a day'],
                         ['Deltadrug 5mg Tablet', '1 Tablet In the evening']]


def test_a_medicine_with_no_direction_beside_it_fails_closed_not_guessed(tmp_path):
    p = str(tmp_path / 'a2.pdf'); make(p)          # Betadrug has a blank direction cell: could equally be a wrapped name
    r = pair(p)
    assert not r['ok'] and 'no direction beside it' in r['reason'] and r['rows'] == []


def test_footer_line_across_both_columns_is_set_aside_visibly_and_direction_not_matching_regex_still_pairs(tmp_path):
    p = str(tmp_path / 'f.pdf'); doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for i in range(12):
        page.insert_text((50, y), 'Drug%d 50mg Tablet' % i, fontsize=10); page.insert_text((300, y), 'SCI 6 MONTHLY.' if i == 5 else '1 Tablet Daily', fontsize=10); y += 14
    page.insert_text((150, y + 80), 'Footer text that runs across both columns of the page 1234', fontsize=9)
    doc.save(p)
    r = pair(p)
    assert r['ok'], r
    assert len(r['rows']) == 12 and r['rows'][5] == ['Drug5 50mg Tablet', 'SCI 6 MONTHLY.'] and len(r['excluded']) == 1


def test_one_column_layout_is_not_ok_so_the_text_path_stays(tmp_path):
    p = str(tmp_path / 'b.pdf'); doc = fitz.open(); page = doc.new_page()
    page.insert_text((50, 70), 'Current Medications'); page.insert_text((50, 100), 'Alphadrug 50mg Tablet'); page.insert_text((50, 112), '1 Tablet Daily')
    doc.save(p)
    assert not pair(p)['ok']


def test_a_direction_with_no_row_to_sit_beside_fails_closed(tmp_path):
    p = str(tmp_path / 'c.pdf'); doc = fitz.open(); page = doc.new_page()
    page.insert_text((50, 70), 'Current Medications'); page.insert_text((50, 100), 'Alphadrug 50mg Tablet'); page.insert_text((320, 100), '1 Tablet Daily')
    page.insert_text((320, 160), '2 Tablets Daily'); page.insert_text((50, 190), 'Betadrug 5mg Tablet'); page.insert_text((320, 190), '1 Tablet Daily')
    doc.save(p)
    r = pair(p)
    assert not r['ok'] and 'far from any row' in r['reason']


def test_shape_hides_letters_and_digits():
    assert g.shape('Alpha 50mg.') == 'Aaaaa 99aa.'


def test_long_names_close_to_the_direction_column_still_split(tmp_path):
    p = str(tmp_path / 'd.pdf'); doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for name, d in [('Breo Ellipta 200/25 200mcg/25mcg Powder for', '1 Puff Daily'), ('Alphadrug 50mg Tablet', '1 Tablet Daily'), ('Betadrug 5mg Tablet', '2 Tablets Daily')]:
        page.insert_text((50, y), name, fontsize=10); page.insert_text((300, y), d, fontsize=10); y += 24
    doc.save(p)
    r = pair(p)
    assert r['ok'] and [x[1] for x in r['rows']] == ['1 Puff Daily', '1 Tablet Daily', '2 Tablets Daily']


def test_trailing_footer_that_does_not_cross_the_gap_is_excluded_and_reported(tmp_path):
    p = str(tmp_path / 'g.pdf'); doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for i in range(5):
        page.insert_text((50, y), 'Drug%d 50mg Tablet' % i, fontsize=10); page.insert_text((300, y), '1 Tablet Daily', fontsize=10); y += 14
    page.insert_text((60, y + 90), 'Page', fontsize=9); page.insert_text((90, y + 90), '1', fontsize=9); page.insert_text((320, y + 90), 'Practice name', fontsize=9)
    doc.save(p)
    r = pair(p)
    assert r['ok'] and len(r['rows']) == 5 and len(r['excluded']) == 1
