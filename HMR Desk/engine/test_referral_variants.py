"""Synthetic PDF intake regression covering mixed pages, rotation and unsafe inputs."""
import fitz
import pytest

import db
import referral_entry


class SyntheticParser:
    def classify(self, text):
        return ('referral','',[]) if 'Synthetic HMR referral' in text else ('other','',['Manual source review required'])
    def extract_fields(self, text):
        if 'Synthetic HMR referral' in text:
            return ({'name':'Synthetic Example','gp':'Dr Synthetic','dob':'1950-01-01'},[])
        return ({},[])
    def ocr_pdfs(self, paths):
        return {}


def make_pdf(path, page_text, rotations=None):
    doc=fitz.open()
    for i, text in enumerate(page_text):
        page=doc.new_page()
        if text:
            page.insert_text((30,60),text)
        if rotations:
            page.set_rotation(rotations[i])
    doc.save(path)
    doc.close()


@pytest.fixture
def case(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace'
    workspace.mkdir()
    monkeypatch.setattr(db,'BASE',str(workspace))
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'userdata'))
    monkeypatch.setattr(referral_entry,'parser',lambda:SyntheticParser())
    conn=db.connect(str(tmp_path/'userdata'/'hmr.db'))
    yield conn,tmp_path,workspace
    conn.close()


def test_two_page_searchable_referral_preserves_page_source_mapping(case):
    conn,tmp,workspace=case
    pdf=tmp/'two pages.pdf'
    make_pdf(pdf,['Synthetic HMR referral, GP: Dr Synthetic, date: 2026-11-01',
                  'Second page: patient history is unconfirmed'])
    reviewed=referral_entry.review(conn,[str(pdf)])['rows'][0]
    assert reviewed['status']=='review'
    assert len(reviewed['page_previews'])==2
    assert all(p['method']=='text' for p in reviewed['page_previews'])
    accepted=referral_entry.commit(conn,reviewed['token'],reviewed['fields'])
    folder=workspace/'TO SORT'
    original=list(folder.rglob('referral.pdf'))[0]
    assert original.read_bytes()==pdf.read_bytes()


def test_five_page_mixed_rotated_and_blank_pdf_reports_uncertainty(case):
    conn,tmp,workspace=case
    pdf=tmp/'multi-page rotated.pdf'
    texts=['Synthetic HMR referral with mixed pages','','Some readable text on third source page',
           'Fourth page without OCR','']
    make_pdf(pdf,texts,[0,90,180,270,0])
    reviewed=referral_entry.review(conn,[str(pdf)])['rows'][0]
    assert reviewed['status']=='review'
    assert len(reviewed['page_previews'])==5
    assert reviewed['page_previews'][0]['method']=='text'
    assert reviewed['page_previews'][1]['method']=='ocr'
    assert any('OCR unavailable' in flag for flag in reviewed['flags'])
    assert reviewed['page_previews'][4]['text']==''
    assert reviewed['sha256']


def test_damaged_and_unrecognised_pdf_never_invents_referral_fields(case):
    conn,tmp,_=case
    corrupt=tmp/'damaged.pdf'
    corrupt.write_bytes(b'%PDF-corrupt')
    blank=tmp/'blank.pdf'
    make_pdf(blank,[''])
    results=referral_entry.review(conn,[str(corrupt),str(blank)])['rows']
    assert results[0]['status']=='error'
    assert results[1]['status']=='manual'
    assert results[1]['fields']=={}
    assert any('Manual source review' in flag for flag in results[1]['flags'])
    with pytest.raises(ValueError,match='explicit pharmacist confirmation'):
        referral_entry.commit(conn,results[1]['token'],{'name':'Synthetic Example'})


def test_pdf_batch_limit_rejects_more_than_100_sources(case):
    conn,tmp,_=case
    with pytest.raises(ValueError,match='up to 100'):
        referral_entry.review(conn,[str(tmp/'missing.pdf')]*101)



def test_review_preview_keeps_columns_first_pdf_text_and_original_bytes(case):
    """The intake review must not pretend that column-first text is paired."""
    conn, tmp, _ = case
    pdf = tmp / 'synthetic-two-columns.pdf'
    doc = fitz.open(); page = doc.new_page()
    page.insert_text((40, 50), 'Synthetic HMR referral', fontsize=11)
    page.insert_text((40, 75), 'Current Medications', fontsize=11)
    for i, name in enumerate(('Lunovex 5mg Tablet', 'Fictamol 10mg Capsule')):
        page.insert_text((40, 110 + 24 * i), name, fontsize=10)
    for i, directions in enumerate(('1 Taplet Daily', '2 Capsules At night')):
        page.insert_text((300, 110 + 24 * i), directions, fontsize=10)
    page.insert_text((40, 190), 'Allergies', fontsize=11)
    page.insert_text((40, 210), 'Synthetic source page: all details require review.', fontsize=9)
    doc.save(pdf); doc.close()
    original = pdf.read_bytes()
    reviewed = referral_entry.review(conn, [str(pdf)])['rows'][0]
    assert reviewed['status'] == 'review'
    assert reviewed['page_previews'][0]['method'] == 'text'
    preview = reviewed['page_previews'][0]['text']
    assert preview.index('Fictamol 10mg') < preview.index('1 Taplet Daily')
    assert 'Taplet' in preview and pdf.read_bytes() == original
    assert reviewed['sha256']
