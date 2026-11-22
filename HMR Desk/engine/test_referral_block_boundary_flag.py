"""A DOB or Telephone line that the patient block did not include must be named in a flag, never attributed. Synthetic only."""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py'
spec = importlib.util.spec_from_file_location('intake_under_test', PATH)
intake = importlib.util.module_from_spec(spec); spec.loader.exec_module(intake)


def case01_order(dob_value_at=21):
    """Structural line order of an operator-reported layout (zero-based): Patient 4, Pharmacy 5, name 7, General
    Practitioner 8, clinician 9, Telephone 15/17, DOB 20, History 30. All values are invented."""
    lines = {i: f'filler line {i}' for i in range(40)}
    lines.update({4: 'Patient', 5: 'Pharmacy', 6: 'Example Pharmacy Name', 7: 'Mrs Jane Sample', 8: 'General Practitioner',
                  9: 'Dr Alex Example', 15: 'Telephone', 17: '0400 000 000', 20: 'DOB', dob_value_at: '05/03/1948', 30: 'History'})
    return '\n'.join(lines[i] for i in range(40))


class BlockBoundary(unittest.TestCase):
    def test_values_outside_the_patient_block_stay_blank(self):
        fields, flags = intake.extract_fields(case01_order())
        self.assertIsNone(fields['dob']); self.assertIsNone(fields['phone'])   # not attributed across the GP heading

    def test_flags_name_the_boundary_cause(self):
        _, flags = intake.extract_fields(case01_order())
        self.assertTrue(any('Telephone' in f and 'outside the patient block' in f and 'check by hand' in f for f in flags), flags)
        self.assertTrue(any('DOB' in f and 'outside the patient block' in f and 'check by hand' in f for f in flags), flags)
        self.assertIn('Missing phone', flags); self.assertIn('Missing dob', flags)   # existing flags unchanged

    def test_flags_carry_no_patient_content(self):
        _, flags = intake.extract_fields(case01_order())
        text = ' '.join(flags)
        self.assertNotIn('0400', text); self.assertNotIn('1948', text); self.assertNotIn('Sample', text)

    def test_no_extra_flag_when_the_fields_are_read_normally(self):
        text = 'Patient\nMrs Jane Sample\nDOB: 05/03/1948\nTelephone: 0400 000 000\nGeneral Practitioner\nDr Alex Example\nHistory\n'
        fields, flags = intake.extract_fields(text)
        self.assertEqual(fields['dob'], '05/03/1948' if fields['dob'] and '/' in fields['dob'] else fields['dob'])
        self.assertFalse(any('outside the patient block' in f for f in flags), flags)

    def test_no_flag_when_there_is_no_such_label_anywhere(self):
        text = 'Patient\nMrs Jane Sample\nGeneral Practitioner\nDr Alex Example\nHistory\n'
        _, flags = intake.extract_fields(text)
        self.assertFalse(any('outside the patient block' in f for f in flags), flags)


if __name__ == '__main__':
    unittest.main()
