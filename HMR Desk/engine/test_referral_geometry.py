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


def test_directions_pair_by_row_not_by_text_order(tmp_path):
    p = str(tmp_path / 'a.pdf'); make(p)
    r = pair(p)
    assert r['ok'], r
    assert r['rows'] == [['Alphadrug 50mg Tablet', '1 Tablet Daily'], ['Betadrug 10mg Capsule', ''],
                         ['Gammadrug 200/25 Powder for inhalation', '2 Puffs Twice a day'], ['Deltadrug 5mg Tablet', '1 Tablet In the evening']]


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
    assert not r['ok'] and 'no medicine on its row' in r['reason']


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
