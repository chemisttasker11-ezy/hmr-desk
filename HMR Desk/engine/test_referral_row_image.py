"""Row-image source evidence: placement, row association, hash binding, fallbacks, path containment. Synthetic data only."""
import base64, copy, hashlib, io, os, shutil, subprocess
import pytest
fitz = pytest.importorskip('fitz')
import api, db, interview, referral_row_image

ROWS = [('Alphadrug 50mg Tablet', '1 Tablet In the morning.'), ('Betadrug 5mg Tablet', '2 Tablets Daily.'), ('Gammadrug 10mg Capsule', '1 Capsule At night.')]


def make_pdf(path, rows=ROWS):
    doc = fitz.open(); page = doc.new_page(); y = 100
    page.insert_text((50, 70), 'Current Medications', fontsize=11)
    for name, d in rows:
        page.insert_text((50, y), name, fontsize=10); page.insert_text((300, y), d, fontsize=10); y += 40
    page.insert_text((50, 800), 'Page 1', fontsize=9)
    doc.save(str(path)); return path


def evidence_for(folder):
    geo = interview.geometry_table(folder)
    assert geo['ok'] and len(geo['row_boxes']) == 3
    f = {'meds': [tuple(r) for r in geo['rows']], 'unattributed_directions': [], 'unparsed': []}
    interview.apply_geometry(f, geo)
    return f['medicine_locations'], geo


def meta(loc, lines=('x',)):
    return {'source_evidence': {'kind': 'referral_text', 'lines': list(lines), 'page_candidates': [[loc['page']] if loc else [] for _ in lines], 'text_sha256': 'a' * 64, **({'location': loc} if loc else {})}}


def png_of(result): return base64.b64decode(result['png'])
def ink_rows(png):
    pix = fitz.Pixmap(png); return pix.width, pix.height, sum(1 for b in pix.samples if b < 128)


def test_each_row_has_its_own_box_on_the_page_in_order(tmp_path):
    make_pdf(tmp_path / 'referral.pdf'); locs, geo = evidence_for(tmp_path)
    ys = [l['box'][1] for l in locs]
    assert ys == sorted(ys) and len(set(ys)) == 3 and all(l['page'] == 1 and len(l['pdf_sha256']) == 64 for l in locs)
    assert all(l['box'][0] < 60 and l['box'][2] > 300 for l in locs)          # name and directions columns both inside the box


def test_row_crop_is_the_right_row_and_only_its_neighbourhood(tmp_path):
    pdf = make_pdf(tmp_path / 'referral.pdf'); locs, _ = evidence_for(tmp_path)
    for i, loc in enumerate(locs):
        r = referral_row_image.render(tmp_path, meta(loc))
        assert r['kind'] == 'row' and r['page'] == 1 and 'current use' in r['note'] and 'not been checked for correctness' in r['note']
        w, h, ink = ink_rows(png_of(r))
        assert h < 120 and ink > 0                                              # a strip, not a page
        # the crop equals a direct render of that row's own rectangle: association is by position of this row's words
        x0, y0, x1, y1 = loc['box']
        with fitz.open(pdf) as d:
            direct = d[0].get_pixmap(matrix=fitz.Matrix(referral_row_image.ROW_DPI / 72, referral_row_image.ROW_DPI / 72), clip=fitz.Rect(x0 - 4, y0 - 4, x1 + 4, y1 + 4), alpha=False).tobytes('png')
        assert png_of(r) == direct
    assert png_of(referral_row_image.render(tmp_path, meta(locs[0]))) != png_of(referral_row_image.render(tmp_path, meta(locs[1])))


@pytest.mark.skipif(not shutil.which('tesseract'), reason='tesseract not installed')
def test_row_crop_text_is_the_expected_row(tmp_path):
    make_pdf(tmp_path / 'referral.pdf'); locs, _ = evidence_for(tmp_path)
    for loc, (name, _) in zip(locs, ROWS):
        r = referral_row_image.render(tmp_path, meta(loc)); (tmp_path / 'c.png').write_bytes(png_of(r))
        text = subprocess.run(['tesseract', str(tmp_path / 'c.png'), '-', '--psm', '6'], capture_output=True, text=True).stdout
        assert name.split()[0] in text
        assert all(other.split()[0] not in text for other, _ in ROWS if other != name)


def test_changed_pdf_is_never_shown_as_the_source(tmp_path):
    make_pdf(tmp_path / 'referral.pdf'); locs, _ = evidence_for(tmp_path)
    make_pdf(tmp_path / 'referral.pdf', [(n.replace('Alpha', 'Omega'), d) for n, d in ROWS])
    r = referral_row_image.render(tmp_path, meta(locs[0]))
    assert r['kind'] == 'none' and 'png' not in r and 'not the file' in r['note']


def test_oversized_or_offpage_box_falls_back_to_the_whole_page(tmp_path):
    make_pdf(tmp_path / 'referral.pdf'); locs, _ = evidence_for(tmp_path)
    for box in ([0, 0, 600, 800], [1000, 1000, 1100, 1100]):
        r = referral_row_image.render(tmp_path, meta({**locs[0], 'box': box}))
        assert r['kind'] == 'page' and r['page'] == 1 and 'whole of page 1' in r['note'] and 'safe crop' in r['note']


def test_page_candidates_only_and_unknown_page(tmp_path):
    make_pdf(tmp_path / 'referral.pdf')
    r = referral_row_image.render(tmp_path, {'source_evidence': {**meta(None)['source_evidence'], 'page_candidates': [[1]]}})
    assert r['kind'] == 'page' and 'not verified' in r['note']
    for cands in ([[]], [[1, 2]]):
        r = referral_row_image.render(tmp_path, {'source_evidence': {**meta(None)['source_evidence'], 'page_candidates': cands}})
        assert r['kind'] == 'none' and 'png' not in r
    r = referral_row_image.render(tmp_path, meta({'page': 4, 'box': [0, 0, 5, 5], 'pdf_sha256': hashlib.sha256((tmp_path / 'referral.pdf').read_bytes()).hexdigest()}))
    assert r['kind'] == 'none'


def test_rows_not_read_from_the_referral_and_missing_pdf(tmp_path):
    assert referral_row_image.render(tmp_path, {'packed': ''})['kind'] == 'none'
    assert referral_row_image.render(tmp_path, meta({'page': 1, 'box': [1, 1, 50, 20], 'pdf_sha256': 'b' * 64}))['kind'] == 'none'


def test_symlinked_referral_outside_the_folder_is_never_read(tmp_path):
    outside = tmp_path / 'outside'; outside.mkdir(); folder = tmp_path / 'p'; folder.mkdir()
    make_pdf(outside / 'x.pdf'); os.symlink(outside / 'x.pdf', folder / 'referral.pdf')
    assert referral_row_image.render(folder, meta({'page': 1, 'box': [40, 90, 400, 105], 'pdf_sha256': hashlib.sha256((outside / 'x.pdf').read_bytes()).hexdigest()}))['kind'] == 'none'


def test_location_schema_is_validated():
    good = {'page': 1, 'box': [1.0, 2.0, 30.0, 40.0], 'pdf_sha256': 'c' * 64}
    base = meta(good)
    assert interview.valid_use(copy.deepcopy(base), set(), set())
    for bad in ({**good, 'extra': 1}, {**good, 'box': [5, 5, 1, 9]}, {**good, 'box': [1, 2, 3]}, {**good, 'page': 0}, {**good, 'pdf_sha256': 'zz'}, {**good, 'box': [1, 2, 3, float('nan')]}, {**good, 'path': '../x'}):
        assert not interview.valid_use(meta(bad), set(), set())


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 't.db')); monkeypatch.setattr(db, 'BASE', str(tmp_path))
    return db.connect()


def test_route_renders_only_for_valid_row_evidence_and_never_takes_a_path(conn, tmp_path):
    folder = tmp_path / 'Ann_Alpha'; folder.mkdir(); make_pdf(folder / 'referral.pdf'); locs, _ = evidence_for(folder)
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder) VALUES ('ann','Ann Alpha','confirmed',0,?)", (str(folder),)); conn.commit()
    url = '/api/patients/1/interview/medicine-row-image'
    status, out = api.handle(conn, 'POST', url, {}, {'source_evidence': meta(locs[1])['source_evidence']})
    assert status == 200 and out['kind'] == 'row' and out['png']
    assert api.handle(conn, 'POST', '/api/patients/9/interview/medicine-row-image', {}, {'source_evidence': meta(locs[1])['source_evidence']})[0] == 404
    for body in ({}, {'source_evidence': {}}, {'source_evidence': meta(locs[1])['source_evidence'], 'path': '/etc/passwd'}, {'path': 'referral.pdf'}):
        assert api.handle(conn, 'POST', url, {}, body)[0] == 400
    assert api.handle(conn, 'GET', url, {}, None)[0] != 200


def test_a_fresh_interview_attaches_the_location_to_the_row_it_belongs_to(conn, tmp_path):
    folder = tmp_path / 'Ann_Alpha'; folder.mkdir(); make_pdf(folder / 'referral.pdf')
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder) VALUES ('ann','Ann Alpha','confirmed',0,?)", (str(folder),)); conn.commit()
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    record = interview.blank(conn, p)
    assert [m[0] for m in record['meds']] == [n for n, _ in ROWS]
    boxes = [m['source_evidence']['location']['box'][1] for m in record['details']['meds']]
    assert boxes == sorted(boxes) and len(set(boxes)) == 3
    for row, m in zip(record['meds'], record['details']['meds']):
        assert interview.valid_use({'source_evidence': m['source_evidence']}, set(), set())
        shown = referral_row_image.render(folder, m)
        assert shown['kind'] == 'row'
    # the evidence is part of each row's own meta, so it moves with the row
    assert record['details']['meds'][0]['source_evidence']['lines'][0].startswith('Alphadrug')
