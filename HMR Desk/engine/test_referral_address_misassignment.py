"""A date, phone number or field label must never become the address. Synthetic only."""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py'
spec = importlib.util.spec_from_file_location('intake_under_test', PATH)
intake = importlib.util.module_from_spec(spec); spec.loader.exec_module(intake)
GP = 'General Practitioner\nDr Alex Example\nHistory\n'


def fields(text):
    return intake.extract_fields(text)


class AddressMisassignment(unittest.TestCase):
    def test_label_column_then_value_column_does_not_use_the_dob_as_address(self):
        f, flags = fields('Patient\nPharmacy\nGeneral Practitioner\nName:\nDOB:\nAddress:\nTelephone:\nMrs Jane Sample\n05/03/1948\n1 Test St\n0400 000 000\nHistory\n')
        self.assertNotEqual(f['address'], '05/03/1948')
        self.assertIsNone(f['address']); self.assertIn('Missing address', flags)

    def test_date_directly_after_the_name_is_not_an_address(self):
        f, flags = fields('Patient\nMrs Jane Sample\n05/03/1948\n' + GP)
        self.assertIsNone(f['address']); self.assertIn('Missing address', flags)

    def test_phone_directly_after_the_name_is_not_an_address(self):
        f, _ = fields('Patient\nMrs Jane Sample\n0400 000 000\n' + GP)
        self.assertIsNone(f['address'])

    def test_bare_address_label_followed_by_another_label_takes_no_value(self):
        f, flags = fields('Patient\nMrs Jane Sample\nAddress\nDOB\n05/03/1948\n' + GP)
        self.assertIsNone(f['address']); self.assertIn('Missing address', flags)

    def test_legitimate_addresses_are_kept(self):
        for text in ('Patient\nMrs Jane Sample\nDOB: 05/03/1948\nAddress: 1 Test St\nSampletown QLD 4000\n' + GP,
                     'Patient\nMrs Jane Sample\nDOB\n05/03/1948\nAddress\n1 Test St\nSampletown QLD 4000\n' + GP,
                     'Patient\nMrs Jane Sample\n12 Example Road\nSampletown QLD 4000\n' + GP,
                     'Patient\nMrs Jane Sample\nUnit 3 Example Court\nSampletown QLD 4000\n' + GP,
                     'Patient\nMrs Jane Sample\nLot 7 Example Lane\nSampletown QLD 4000\n' + GP):
            f, flags = fields(text)
            self.assertIsNotNone(f['address'], text); self.assertNotIn('Missing address', flags)
            self.assertNotRegex(f['address'], r'\d{2}/\d{2}/\d{4}')

    def test_dob_still_read_from_a_bare_label_and_value(self):
        f, _ = fields('Patient\nMrs Jane Sample\nDOB\n05/03/1948\n' + GP)
        self.assertEqual(f['dob'], '05/03/1948')


if __name__ == '__main__':
    unittest.main()
