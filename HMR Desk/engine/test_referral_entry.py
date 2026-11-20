import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import db
import referral_entry


class ReferralEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        parser_path = self.root / 'scripts' / 'intake' / 'intake.py'
        parser_path.parent.mkdir(parents=True)
        parser_path.write_bytes((Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py').read_bytes())
        self.old_base = db.BASE
        db.BASE = str(self.root)
        self.conn = db.connect(str(self.root / 'test.db'))
        self.pdf = self.root / 'source.pdf'
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 70), ('Referral patient medication details for synthetic test.\n' * 8))
        doc.save(self.pdf)
        doc.close()
        class Parser:
            def classify(self, text): return 'referral', [], []
            def extract_fields(self, text): return {'name': 'Synthetic Person', 'gp': 'Test Doctor'}, []
        self.patcher = patch.object(referral_entry, 'parser', return_value=Parser())
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.conn.close()
        db.BASE = self.old_base
        self.temp.cleanup()

    def test_review_commit_preserves_source_and_deduplicates(self):
        before = self.pdf.read_bytes()
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        self.assertEqual(row['status'], 'review')
        result = referral_entry.commit(self.conn, row['token'], row['fields'])
        self.assertEqual(self.pdf.read_bytes(), before)
        patient = self.conn.execute('SELECT folder FROM patients WHERE id=?', (result['patient_id'],)).fetchone()
        self.assertEqual((self.root / patient['folder'] / 'referral.pdf').read_bytes(), before)
        self.assertEqual(referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]['status'], 'duplicate')

    def test_changed_source_cannot_commit(self):
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        with self.pdf.open('ab') as f: f.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            referral_entry.commit(self.conn, row['token'], row['fields'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM patients').fetchone()[0], 0)

    def test_bad_files_are_reported_individually(self):
        bad = self.root / 'bad.pdf'
        bad.write_text('not a PDF')
        rows = referral_entry.review(self.conn, [str(bad), str(self.pdf)])['rows']
        self.assertEqual([row['status'] for row in rows], ['error', 'review'])

    def test_ocr_forward_slash_source_uses_normalized_lookup(self):
        short = self.root / 'scan.pdf'
        doc = fitz.open(); doc.new_page(); doc.save(short); doc.close()
        before = short.read_bytes()
        class OcrParser:
            def ocr_pdfs(self, paths): return {str(paths[0]): ['Synthetic referral patient medication']}
            def classify(self, text): return 'referral', [], []
            def extract_fields(self, text): return {'name':'Synthetic Person'}, []
        with patch.object(referral_entry, 'parser', return_value=OcrParser()):
            row = referral_entry.review(self.conn, [short.as_posix()])['rows'][0]
        self.assertEqual(row['status'], 'review')
        self.assertEqual(short.read_bytes(), before)
        stored = self.conn.execute('SELECT value FROM meta WHERE key=?', ('referral_review_' + row['token'],)).fetchone()
        self.assertEqual(json.loads(stored['value'])['source'], short.as_posix())

    def test_import_preserves_new_referral_and_booking_interview(self):
        import api, importer, interview, jobs, steps
        plan = self.root / 'Appointment_Plan_1.json'
        plan.write_text(json.dumps({'patients': []}), encoding='utf-8')
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        fields = {'name': 'Synthetic Person', 'gp': 'Test Doctor', 'dob': '01/01/1960',
                  'sex': 'F', 'medicare': '1234567890', 'phone': '0412345678'}
        pid = referral_entry.commit(self.conn, row['token'], fields)['patient_id']
        before = self.pdf.read_bytes()
        sorting = self.root / 'TO SORT'
        (sorting / 'intake_report_1.json').write_text(json.dumps([{'kind':'referral', 'file':'old.pdf', 'fields':{'name':'Synthetic Person', 'phone':'old', 'dob':'old'}}]), encoding='utf-8')
        importer.run(self.conn, self.root)
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        folder = jobs.patient_folder(patient)
        self.assertEqual((folder / 'referral.pdf').read_bytes(), before)
        self.assertEqual((patient['phone'], patient['dob'], patient['state']), ('0412345678', '01/01/1960', 'new'))
        api.action(self.conn, patient, {'action':'book_phone', 'date':'2027-02-01', 'time':'09:00', 'end':'10:00'})
        importer.run(self.conn, self.root)
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        self.assertEqual(patient['state'], 'confirmed')
        self.assertTrue(steps.ready('interview_sheet', self.conn, patient)[0])
        self.assertEqual(jobs.patient_folder(patient), folder)
        self.assertEqual(interview.load(self.conn, patient)['header']['name'], 'Synthetic Person')
        self.assertIn('Referral patient medication', interview.referral_text(folder)[0])
        count = self.conn.execute('SELECT count(*) FROM events').fetchone()[0]
        importer.run(self.conn, self.root)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM events').fetchone()[0], count)
        self.assertEqual((jobs.patient_folder(self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()) / 'referral.pdf').read_bytes(), before)
        legacy = self.root / 'Scheduled' / 'Synthetic Person_ TD'
        legacy.mkdir(parents=True)
        importer.run(self.conn, self.root)
        self.assertEqual(self.conn.execute('SELECT folder FROM patients WHERE id=?', (pid,)).fetchone()['folder'], os.path.relpath(legacy, self.root))

    def test_import_does_not_preserve_untrusted_outside_folder(self):
        import importer
        (self.root / 'Appointment_Plan_1.json').write_text(json.dumps({'patients': []}), encoding='utf-8')
        self.conn.execute('INSERT INTO patients (key,name,folder) VALUES (?,?,?)', ('outside person', 'Outside Person', str(self.root.parent)))
        pid = self.conn.execute('SELECT id FROM patients WHERE key=?', ('outside person',)).fetchone()['id']
        db.log(self.conn, pid, 'referral_received', {'folder': 'TO SORT/Referral-' + 'a'*32, 'sha256': 'b'*64}, 'intake')
        self.conn.commit()
        importer.run(self.conn, self.root)
        self.assertIsNone(self.conn.execute('SELECT folder FROM patients WHERE id=?', (pid,)).fetchone()['folder'])


class RealParserTests(unittest.TestCase):
    def test_actual_parser_duplicates_correction_and_rejection(self):
        original_base = db.BASE
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(Path(__file__).resolve().parents[2] / 'scripts' / 'intake', root / 'scripts' / 'intake')  # the repository's own parser; db.BASE can be left pointing at a temp folder by an earlier test
            db.BASE = tmp
            conn = db.connect(str(root / 'test.db'))
            try:
                def pdf(name, text):
                    target = root / name
                    doc = fitz.open(); page = doc.new_page()
                    page.insert_text((50, 60), text, fontsize=10)
                    doc.save(target); doc.close()
                    return target
                contents = ('Home Medicines Review Referral\nPatient Details\nName: Synthetic Person\n'
                    'DOB: 01/01/1960\nAddress: 1 Test Road\nSuburb: 4000 Testville\nPhone: 0412 345 678\nGeneral Practitioner Details\nName: Dr Test Doctor\n'
                    'Current medications\n' + 'Synthetic medicines listed for review.\n' * 9)
                first = pdf('first.pdf', contents)
                second = pdf('second.pdf', contents + '\nAdditional synthetic referral information.')
                other = pdf('other.pdf', 'Unrelated administrative document.\n' * 12)
                bad = root / 'bad.pdf'; bad.write_bytes(b'not a PDF')
                rows = referral_entry.review(conn, [str(first), str(second), str(other), str(bad)])['rows']
                self.assertEqual([r['status'] for r in rows], ['review', 'duplicate', 'manual', 'error'])  # 'manual' since 4447e17: unrecognised PDFs are review-only; commit refuses without explicit confirmation (test_referral_identity)
                self.assertEqual(rows[1]['duplicate_kind'], 'identity')
                fields = {k: (v or '') for k, v in rows[0]['fields'].items() if k in referral_entry.FIELDS}
                fields['name'] = 'Corrected Person'
                before = first.read_bytes()
                patient = referral_entry.commit(conn, rows[0]['token'], fields)['patient_id']
                self.assertEqual(conn.execute('SELECT name FROM patients WHERE id=?', (patient,)).fetchone()['name'], 'Corrected Person')
                self.assertEqual(first.read_bytes(), before)
                self.assertEqual(referral_entry.review(conn, [str(first)])['rows'][0]['duplicate_kind'], 'content')
                with self.assertRaises(ValueError): referral_entry.commit(conn, rows[0]['token'], fields)
            finally:
                conn.close()
                db.BASE = original_base


if __name__ == '__main__': unittest.main()

class IntakeInterviewPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        parser_path = self.root / 'scripts' / 'intake' / 'intake.py'
        parser_path.parent.mkdir(parents=True)
        parser_path.write_bytes((Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py').read_bytes())
        self.old_base, self.old_data = db.BASE, db.DATA_DIR
        db.BASE = str(self.root)
        db.DATA_DIR = str(self.root / 'userdata')
        (self.root / 'userdata').mkdir()
        self.conn = db.connect(str(self.root / 'userdata' / 'hmr.db'))
        self.pdf = self.root / 'source.pdf'
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 70), 'Medical History\nSynthetic condition\nCurrent Medications\n- Syntheticmed 5 mg MR tablet take one tablet\n')
        doc.save(self.pdf)
        doc.close()
        class Parser:
            def classify(self, text): return 'referral', [], []
            def extract_fields(self, text): return {'name': 'Synthetic Person', 'gp': 'Test Doctor'}, []
        self.patcher = patch.object(referral_entry, 'parser', return_value=Parser())
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.conn.close()
        db.BASE, db.DATA_DIR = self.old_base, self.old_data
        self.temp.cleanup()

    def test_commit_materializes_interview_with_unconfirmed_exact_proposal(self):
        import interview, records
        from medicine_data import catalog
        import medicine_reference as ref
        conn = catalog.connect(ref.reference_path())
        source = self.root / 'synthetic-source.txt'; source.write_text('SYNTHETIC ONLY')
        with catalog.snapshot(conn, 'amt', '20260101', source, 'https://example.invalid/synthetic'):
            catalog.add_medicine(conn, 'amt', '1001', 'Syntheticmed 5 mg MR tablet', 'MPUU', generic='Syntheticmed 5 mg MR tablet', form='tablet')
        conn.close()
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        pid = referral_entry.commit(self.conn, row['token'], row['fields'])['patient_id']
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        data = interview.load(self.conn, patient)
        assert data['revision'] != 'missing'
        proposal = data['details']['meds'][0]['prefill_proposal']
        assert proposal['input_text'] == 'Syntheticmed 5 mg MR tablet'
        assert proposal['candidate']['code'] == '1001' and proposal['candidate']['release'] == '20260101'
        assert 'reference' not in data['details']['meds'][0]
        assert data['details']['meds'][0]['source_evidence']['kind'] == 'referral_text'
        assert self.conn.execute("SELECT 1 FROM events WHERE type='interview_prepared_at_intake' AND patient_id=?", (pid,)).fetchone()
        # Quiet materialization: no pharmacist-save side effects belong to intake.
        assert self.conn.execute("SELECT has_sheet FROM patients WHERE id=?", (pid,)).fetchone()[0] == 0
        assert not self.conn.execute("SELECT 1 FROM events WHERE type='interview_saved' AND patient_id=?", (pid,)).fetchone()
        assert not list((self.root / patient['folder']).glob('PPA Consent - *.pdf'))
        # Referral-derived text only; no clinical confirmation is promoted at intake.
        assert data['conditions'] == 'Synthetic condition'
        assert all('reference' not in m for m in data['details']['meds'])

    def test_commit_without_catalogue_still_materializes_record(self):
        import interview
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        pid = referral_entry.commit(self.conn, row['token'], row['fields'])['patient_id']
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        data = interview.load(self.conn, patient)
        assert data['revision'] != 'missing'
        assert 'prefill_proposal' not in data['details']['meds'][0]
        assert data['details']['meds'][0]['source_evidence']['kind'] == 'referral_text'

    def test_materialization_failure_leaves_intake_fully_intact(self):
        import records as records_mod
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        with patch.object(records_mod, 'put', side_effect=RuntimeError('synthetic disk failure')):
            pid = referral_entry.commit(self.conn, row['token'], row['fields'])['patient_id']
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        assert patient is not None
        assert self.conn.execute("SELECT 1 FROM events WHERE type='referral_received' AND patient_id=?", (pid,)).fetchone()
        assert (self.root / patient['folder'] / 'referral.pdf').is_file()
        assert records_mod.get(self.conn, pid, 'interview.json') is None
        assert not self.conn.execute("SELECT 1 FROM events WHERE type='interview_prepared_at_intake' AND patient_id=?", (pid,)).fetchone()
        # The fallback path still builds the record on first interview open.
        import interview
        data = interview.load(self.conn, patient)
        assert data['details']['meds'][0]['source_evidence']['kind'] == 'referral_text'
        assert all('prefill_proposal' not in m for m in data['details']['meds'])

    def test_rollback_at_event_boundary_removes_inserted_record(self):
        import db as db_mod
        import records as records_mod
        real_log = db_mod.log
        inserted = []
        def failing_log(conn, pid, type_, detail, actor):
            if type_ == 'interview_prepared_at_intake':
                # The record insert is visible inside the transaction right before
                # the failing log write, so a later rollback must remove it.
                inserted.append(records_mod.get(conn, pid, 'interview.json') is not None)
                raise RuntimeError('synthetic log failure')
            return real_log(conn, pid, type_, detail, actor)
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        with patch.object(db_mod, 'log', failing_log):
            pid = referral_entry.commit(self.conn, row['token'], row['fields'])['patient_id']
        assert inserted == [True]
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        assert patient is not None
        assert self.conn.execute("SELECT 1 FROM events WHERE type='referral_received' AND patient_id=?", (pid,)).fetchone()
        assert records_mod.get(self.conn, pid, 'interview.json') is None
        assert not self.conn.execute("SELECT 1 FROM events WHERE type='interview_prepared_at_intake' AND patient_id=?", (pid,)).fetchone()

    def test_confirmed_intake_clinical_review_promotes_into_materialized_record(self):
        # referral_source.json is written once at intake and never mutated after,
        # so promotion at intake materialization matches the pre-change first-open
        # build exactly; early record creation cannot freeze out a later review.
        row = referral_entry.review(self.conn, [str(self.pdf)])['rows'][0]
        clinical = {'confirmed': True, 'allergies_status': 'unknown', 'reviewed_by': 'Synthetic Pharmacist',
                    'conditions': 'Reviewed synthetic condition', 'medicines': '', 'observations': '', 'allergies': '',
                    'source_page': 1}
        pid = referral_entry.commit(self.conn, row['token'], row['fields'], clinical=clinical)['patient_id']
        patient = self.conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        import interview
        data = interview.load(self.conn, patient)
        assert data['revision'] != 'missing'
        assert data['conditions'] == 'Reviewed synthetic condition'
        assert any(s == 'Conditions confirmed: referral.pdf page 1; Synthetic Pharmacist' for s in data['sources'])
