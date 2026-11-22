"""Only original GP PDF content is eligible at this stage.

All fixtures are invented. The file on disk remains unchanged; a FreeText
interview overlay must not enter any referral identity or medicine proposal.
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
    annot = page.add_freetext_annot(fitz.Rect(40, 110, 330, 180),
                                    'Name: Ms Fictional Overlay', fontsize=13,
                                    text_color=(0, 0, 1))
    annot.update()
    doc.save(path)
    doc.close()


def test_typed_pdf_freetext_is_removed_only_in_memory(tmp_path):
    source = tmp_path / 'referral.pdf'
    _document(source)
    original = source.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    with fitz.open(source) as doc:
        assert 'Fictional Overlay' in doc[0].get_text()
        pages, count = referral_source_text.extract_original_pages(doc)
        assert count == [1]
        assert 'Fictional Original' in pages[0]
        assert 'Fictional Overlay' not in pages[0]
    assert source.read_bytes() == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with fitz.open(source) as doc:
        assert 'Fictional Overlay' in doc[0].get_text()


def test_actual_referral_review_ignores_typed_overlay():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / 'fictional.pdf'
        _document(source)
        class Parser:
            @staticmethod
            def classify(text):
                return 'referral', [], []
            @staticmethod
            def extract_fields(text):
                assert 'Fictional Overlay' not in text
                return {'name': 'Fictional Original'}, []
        saved_base = db.BASE
        try:
            db.BASE = str(root)
            conn = db.connect(str(root / 'test.db'))
            try:
                with patch.object(referral_entry, 'parser', return_value=Parser()):
                    rows = referral_entry.review(conn, [str(source)])['rows']
                assert rows[0]['status'] == 'review'
                assert 'Fictional Overlay' not in rows[0]['page_previews'][0]['text']
                assert any('typed PDF interview overlays excluded' in x for x in rows[0]['flags'])
            finally:
                conn.close()
        finally:
            db.BASE = saved_base
