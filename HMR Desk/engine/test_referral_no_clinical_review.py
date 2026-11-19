"""A referral added without clinical source review adds demographics only.

Synthetic referral text states allergies, a condition and a medicine. With no pharmacist clinical review at
add time, none of it may become a confirmed clinical fact, and readiness must not report clinical readiness."""
import json
import tempfile
import unittest
from pathlib import Path

import fitz
import db
import interview
import referral_entry
import report_status
import clinical_snapshot

TEXT = ['Synthetic Clinic', 'Date: 01/02/2026', 'Dr Example GP', 'RE: Mrs Alpha Testperson', 'DOB: 03/04/1950',
        'Medicare: 1234567890 1', 'Referral for Home Medicines Review (HMR).', 'Allergies: nil known',
        'Conditions: hypertension', 'Current medications: aspirin 100 mg daily', 'Yours sincerely']


class NoClinicalReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        parser = self.root / 'scripts' / 'intake' / 'intake.py'
        parser.parent.mkdir(parents=True)
        parser.write_bytes((Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py').read_bytes())
        self.old_base = db.BASE
        db.BASE = str(self.root)
        self.conn = db.connect(str(self.root / 'test.db'))
        path = self.root / 'r.pdf'
        doc = fitz.open(); doc.new_page().insert_text((50, 70), '\n'.join(TEXT)); doc.save(path); doc.close()
        row = referral_entry.review(self.conn, [str(path)])['rows'][0]
        fields = {k: v for k, v in row['fields'].items() if isinstance(v, str)}
        pid = referral_entry.commit(self.conn, row['token'], fields)['patient_id']
        self.patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()

    def tearDown(self):
        self.conn.close()
        db.BASE = self.old_base
        self.temp.cleanup()

    def source(self):
        folder = Path(db.BASE) / self.patient['folder']
        return json.loads((folder / 'referral_source.json').read_text(encoding='utf-8'))

    def test_stored_review_is_unconfirmed_with_unknown_allergies(self):
        review = self.source()['clinical_review']
        self.assertIs(review['confirmed'], False)
        self.assertEqual(review['allergies_status'], 'unknown')
        self.assertEqual(review['reviewed_by'], '')

    def test_interview_record_is_not_seeded_with_clinical_facts(self):
        record = interview.load(self.conn, self.patient)
        self.assertEqual(record['conditions'], '')
        self.assertEqual(record['allergies'], '')
        self.assertEqual(record['meds'], [])

    def test_snapshot_keeps_allergies_unknown_and_not_confirmed_negative(self):
        record = interview.load(self.conn, self.patient)
        snapshot = clinical_snapshot.canonical({'name': self.patient['name'], 'dob': self.patient['dob'], 'gp': self.patient['gp'], 'referral_date': self.patient['referral_date']}, record, {}, {}, referral_source=self.source())
        text = json.dumps(snapshot)
        self.assertNotIn('"confirmed_negative": true', text)
        allergies = json.loads(text)
        self.assertEqual(self.find(allergies, 'allergies')['state'], 'unknown')

    @staticmethod
    def find(node, key):
        if isinstance(node, dict):
            if key in node and isinstance(node[key], dict):
                return node[key]
            for value in node.values():
                found = NoClinicalReview.find(value, key)
                if found: return found
        return {}

    def test_readiness_is_not_clinically_ready_and_consent_is_not_met(self):
        result = report_status.readiness(self.conn, self.patient)
        self.assertIsNone(result['clinically_ready'])
        states = {item['key']: item['state'] for item in result['items']}
        self.assertEqual(states['consent_recorded'], 'not_met')
        self.assertNotEqual(states['medicines_reconciled'], 'met')
