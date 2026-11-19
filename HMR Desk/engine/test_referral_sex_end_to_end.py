import tempfile
import unittest
from pathlib import Path

import fitz
import db
import referral_entry
import steps

TEXT = ['Synthetic Clinic', 'Date: 01/02/2026', 'Dr Example GP', 'RE: {title} {name}', 'DOB: 03/04/1950',
        'Medicare: 1234567890', 'Referral for Home Medicines Review (HMR).', 'Yours sincerely']


class SexFromTitleEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        parser = self.root / 'scripts' / 'intake' / 'intake.py'
        parser.parent.mkdir(parents=True)
        parser.write_bytes((Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py').read_bytes())
        self.old_base = db.BASE
        db.BASE = str(self.root)
        self.conn = db.connect(str(self.root / 'test.db'))

    def tearDown(self):
        self.conn.close()
        db.BASE = self.old_base
        self.temp.cleanup()

    def pdf(self, title, name):
        path = self.root / (name.replace(' ', '_') + '.pdf')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 70), '\n'.join(TEXT).format(title=title, name=name))
        doc.save(path)
        doc.close()
        return path

    def add(self, title, name, sex=None):
        row = referral_entry.review(self.conn, [str(self.pdf(title, name))])['rows'][0]
        self.assertEqual(row['kind'], 'referral')
        fields = dict(row['fields'])
        if sex is not None:
            fields['sex'] = sex
        fields = {k: v for k, v in fields.items() if isinstance(v, str)}
        pid = referral_entry.commit(self.conn, row['token'], fields)['patient_id']
        # A booked patient, so the only thing left to fail pathology readiness is the data itself.
        self.conn.execute("UPDATE patients SET state='confirmed' WHERE id=?", (pid,))
        self.conn.commit()
        return row, self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()

    def test_title_only_referral_commits_with_blank_sex_and_is_not_ready(self):
        row, patient = self.add('Mrs', 'Alpha Testperson')
        self.assertFalse(row['fields'].get('sex'))
        self.assertFalse(patient['sex'])
        ready, reason = steps.ready('pathology', self.conn, patient)
        self.assertFalse(ready)
        self.assertIn('sex', reason)

    def test_pharmacist_supplied_sex_is_kept_and_satisfies_readiness(self):
        _, patient = self.add('Mrs', 'Beta Testperson', sex='F')
        self.assertEqual(patient['sex'], 'F')
        ready, reason = steps.ready('pathology', self.conn, patient)
        self.assertTrue(ready, reason)

    def test_blank_sex_reaches_clinical_context_as_blank(self):
        import clinical_privacy
        _, patient = self.add('Mr', 'Gamma Testperson')
        self.assertEqual(patient['sex'] or '', '')
        out = clinical_privacy.project({'header': {}}, sex=patient['sex'] or '')
        self.assertEqual(out['demographics']['sex'], '')
