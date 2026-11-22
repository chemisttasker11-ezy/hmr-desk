"""Mixed digital-text/scanned-table regression using an entirely fictional PDF.

Proves the real production referral_entry.review path does not silently treat a
native cover heading as evidence that a rasterised clinical table was read.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz

import db
import referral_entry
import referral_page_audit


def test_mixed_image_clinical_table_warns_in_real_referral_review():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / 'fictional-referral.pdf'
        scanned = fitz.open()
        scanpage = scanned.new_page(width=400, height=300)
        scanpage.insert_text((20, 30), 'Current Medications', fontsize=16)
        scanpage.insert_text((20, 80), 'Fictamed 5 mg tablet  1 tablet daily', fontsize=11)
        pixels = scanpage.get_pixmap()
        scanned.close()
        document = fitz.open()
        page = document.new_page()
        page.insert_text((20, 30), 'HMR Referral: synthetic cover text is digitally readable', fontsize=11)
        page.insert_image(fitz.Rect(30, 100, 570, 650), pixmap=pixels)
        inspected = referral_page_audit.inspect_page(page)
        assert inspected['native_present']
        assert inspected['needs_image_review']
        document.save(source)
        document.close()

        class FictionalParser:
            @staticmethod
            def classify(text):
                return 'referral', [], []

            @staticmethod
            def extract_fields(text):
                return {'name': 'Fictional Person'}, []

        original_base = db.BASE
        try:
            db.BASE = str(root)
            conn = db.connect(str(root / 'test.db'))
            try:
                with patch.object(referral_entry, 'parser', return_value=FictionalParser()):
                    row = referral_entry.review(conn, [str(source)])['rows'][0]
                assert row['status'] == 'review'
                assert any('image content' in flag.lower() for flag in row['flags'])
                assert row['page_previews'][0]['method'] == 'text+unread_image'
                assert 'Fictamed' not in row['page_previews'][0]['text']
            finally:
                conn.close()
        finally:
            db.BASE = original_base

