"""Safety regression: FreeText may be authored by a referring GP.

The original PDF must not be edited or stripped. Keep all native page text,
including blue FreeText, and mark the annotation separately for manual review.
No source author or clinical attribution is inferred. Fixtures are fictional.
"""
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz
import db
import referral_entry
import referral_source_text


def _document(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), 'Home Medicines Review Referral\nPatient Details\nName: Ms Fictional Original\nCurrent Medications')
    annot = page.add_freetext_annot(
        fitz.Rect(40, 110, 440, 180),
        'GP added: Fictamed 20 mg one tablet daily',
        fontsize=13, text_color=(0, 0, 1))
    annot.update()
    doc.save(path)
    doc.close()


def test_freetext_is_retained_and_original_pdf_unchanged(tmp_path):
    source = tmp_path / 'referral.pdf'
    _document(source)
    original = source.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    with fitz.open(source) as doc:
        pages, evidence = referral_source_text.extract_original_pages(doc)
        assert 'Fictional Original' in pages[0]
        assert 'Fictamed 20 mg one tablet daily' in pages[0]
        assert evidence[0]['count'] == 1
        assert evidence[0]['details'][0]['type'] == 'FreeText'
        assert 'Fictamed 20 mg' in evidence[0]['details'][0]['text_unverified']
        assert len(list(doc[0].annots() or [])) == 1
    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_actual_referral_review_preserves_gp_added_text_with_review_warning():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / 'fictional.pdf'
        _document(source)

        class Parser:
            @staticmethod
            def classify(text):
                assert 'Fictamed 20 mg' in text
                return 'referral', [], []

            @staticmethod
            def extract_fields(text):
                assert 'Fictamed 20 mg' in text
                return {'name': 'Fictional Original'}, []

        saved_base = db.BASE
        try:
            db.BASE = str(root)
            conn = db.connect(str(root / 'test.db'))
            try:
                with patch.object(referral_entry, 'parser', return_value=Parser()):
                    row = referral_entry.review(conn, [str(source)])['rows'][0]
                assert row['status'] == 'review'
                assert 'Fictamed 20 mg' in row['page_previews'][0]['text']
                assert row['annotation_evidence'][0]['count'] == 1
                assert any('FreeText annotations' in x and 'retained' in x for x in row['flags'])
            finally:
                conn.close()
        finally:
            db.BASE = saved_base
