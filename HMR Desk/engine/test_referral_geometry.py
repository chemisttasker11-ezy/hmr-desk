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


def words_of(path, n=0):
    with fitz.open(path) as doc: return [(w[0], w[1], w[2], w[3], w[4]) for w in doc[n].get_text('words')], doc[n].rect.height


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
    page.insert_text((150, 800), 'Footer text that runs across both columns of the page 1234', fontsize=9)
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
    page.insert_text((60, 800), 'Page', fontsize=9); page.insert_text((90, 800), '1', fontsize=9); page.insert_text((320, 800), 'Practice name', fontsize=9)
    doc.save(p)
    r = pair(p)
    assert r['ok'] and len(r['rows']) == 5 and len(r['excluded']) == 1


def table_page(doc, n=8, extra=None, heading=True):
    page = doc.new_page(); y = 100
    if heading: page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for i in range(n):
        page.insert_text((50, y), 'Drug%d 50mg Tablet' % i, fontsize=10); page.insert_text((300, y), '1 Tablet Daily', fontsize=10); y += 14
    return page


def test_clinical_content_in_the_footer_zone_is_never_set_aside(tmp_path):
    p = str(tmp_path / 'h.pdf'); doc = fitz.open(); page = table_page(doc)
    page.insert_text((60, 800), 'Warfarin 5mg Tablet', fontsize=9); page.insert_text((320, 800), '1 Tablet Daily', fontsize=9)
    doc.save(p); words, h = words_of(p)
    r = g.pair_table(words, h)
    assert r['ok'] is False or all('Warfarin' not in e for e in r['excluded'])
    if r['ok']: assert any('Warfarin' in row[0] for row in r['rows'])


def test_trailing_text_mid_page_is_not_treated_as_a_footer_from_distance_alone(tmp_path):
    p = str(tmp_path / 'i.pdf'); doc = fitz.open(); page = table_page(doc)
    page.insert_text((60, 400), 'Please note the patient also takes something not listed here', fontsize=9)
    doc.save(p); words, h = words_of(p)
    r = g.pair_table(words, h)
    assert not r['ok'] and r['rows'] == []


def test_whole_table_fails_closed_when_the_next_page_may_continue_it(tmp_path):
    p = str(tmp_path / 'j.pdf'); doc = fitz.open(); table_page(doc)
    nxt = doc.new_page(); nxt.insert_text((50, 100), 'Drug99 50mg Tablet', fontsize=10); nxt.insert_text((300, 100), '2 Tablets Daily', fontsize=10)
    doc.save(p)
    pages = [words_of(p, 0), words_of(p, 1)]
    r = g.pair_document(pages)
    assert not r['ok'] and 'may continue' in r['reason'] and r['rows'] == []


def test_table_is_accepted_when_the_next_page_starts_with_another_section(tmp_path):
    p = str(tmp_path / 'k.pdf'); doc = fitz.open(); table_page(doc)
    nxt = doc.new_page(); nxt.insert_text((50, 100), 'Allergies', fontsize=11); nxt.insert_text((50, 120), 'None known', fontsize=10)
    doc.save(p)
    r = g.pair_document([words_of(p, 0), words_of(p, 1)])
    assert r['ok'] and len(r['rows']) == 8 and r['page'] == 1


def test_a_repeated_medicines_heading_on_the_next_page_fails_closed(tmp_path):
    p = str(tmp_path / 'l.pdf'); doc = fitz.open(); table_page(doc); table_page(doc)
    doc.save(p)
    r = g.pair_document([words_of(p, 0), words_of(p, 1)])
    assert not r['ok']


def test_every_word_is_accounted_for(tmp_path):
    p = str(tmp_path / 'm.pdf'); doc = fitz.open(); page = table_page(doc, 12)
    page.insert_text((60, 800), 'Page 1', fontsize=9)
    doc.save(p); words, h = words_of(p)
    r = g.pair_table(words, h)
    assert r['ok'] and r['excluded'] == ['Page 1']
    got = sorted(' '.join(' '.join(x) for x in r['rows']).split() + ['Page', '1'])
    region = sorted(w[4] for w in g.medicine_region(words))
    assert got == region



def test_pdf_text_layer_columns_first_still_yields_distinct_verbatim_rows(tmp_path):
    """The PDF may write all names before any direction even when the page is two-column."""
    target = tmp_path / 'synthetic-columns-first.pdf'
    names = ['Lunovex 5mg Tablet', 'Fictamol 10mg Capsule', 'Nuvrala 20mg Tablet']
    directions = ['1 Taplet Daily', '2 Capsules At night', '1 Tablet With meals']
    doc = fitz.open(); page = doc.new_page()
    page.insert_text((50, 70), 'Current Medications')
    for i, name in enumerate(names):
        page.insert_text((50, 100 + 24 * i), name)
    for i, direction in enumerate(directions):
        page.insert_text((310, 100 + 24 * i), direction)
    page.insert_text((50, 240), 'Allergies')
    doc.save(target); doc.close()
    with fitz.open(target) as source:
        text = source[0].get_text()
        assert text.index(names[-1]) < text.index(directions[0]), 'fixture must encode column-first order'
    paired = pair(str(target))
    assert paired['ok'], paired
    assert paired['rows'] == [[name, direction] for name, direction in zip(names, directions)]
    assert 'Taplet' in g.unusual_direction_words(paired['rows'][0][1])
    assert paired['rows'][0][0] == names[0] and paired['rows'][1][0] == names[1]
