"""Intake warns when the PDF layout is not one the interview can read clinical sections from (synthetic PDFs)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import db
import referral_entry


def make_pdf(path, lines):
    doc = fitz.open(); page = doc.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line); y += 16
    doc.save(path); doc.close()


SUMMARY = ['Example Medical Centre', 'Patient Details:', 'Name: Mrs Jane Syntheticexample', 'Date of birth: 01/02/1950',
           'Medical History', 'Fictional high cholesterol', 'Current Medications', 'examplestatin 20 mg tablet',
           'take one tablet daily', 'Allergies', 'Nil known']
OTHER = ['Example Medical Centre', 'Patient Details:', 'Name: Mrs Jane Syntheticexample', 'Date of birth: 01/02/1950',
         'Current medications: examplestatin 20 mg tablet, one daily', 'Allergies: nil known']


class Layout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        parser_path = self.root / 'scripts' / 'intake' / 'intake.py'; parser_path.parent.mkdir(parents=True)
        parser_path.write_bytes((Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py').read_bytes())
        self.old_base = db.BASE; db.BASE = str(self.root)
        self.conn = db.connect(str(self.root / 'test.db'))
        class Parser:
            def classify(self, text): return 'referral', [], []
            def extract_fields(self, text): return {'name': 'Synthetic Person'}, []
        self.patcher = patch.object(referral_entry, 'parser', return_value=Parser()); self.patcher.start()

    def tearDown(self):
        self.patcher.stop(); self.conn.close(); db.BASE = self.old_base; self.temp.cleanup()

    def row(self, lines, name):
        pdf = self.root / name; make_pdf(pdf, lines)
        return referral_entry.review(self.conn, [str(pdf)])['rows'][0]

    def test_unrecognised_layout_is_flagged_and_nothing_is_filled(self):
        row = self.row(OTHER, 'other.pdf')
        self.assertIn(referral_entry.UNRECOGNISED_LAYOUT_FLAG, row['flags'])
        self.assertEqual(row['status'], 'review')  # still reviewable; the flag changes no status or fields
        self.assertNotIn('medicines', row['fields'])

    def test_recognised_layout_has_no_such_flag(self):
        row = self.row(SUMMARY, 'summary.pdf')
        self.assertNotIn(referral_entry.UNRECOGNISED_LAYOUT_FLAG, row['flags'])

    def test_flag_wording_does_not_claim_intake_fills_clinical_fields(self):
        text = referral_entry.UNRECOGNISED_LAYOUT_FLAG
        self.assertIn('interview', text)
        self.assertNotIn('auto', text.lower())
