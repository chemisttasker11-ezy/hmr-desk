import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py'
spec = importlib.util.spec_from_file_location('intake_sex_blank', PATH)
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)

LETTER = 'Date: 01/02/2026\nRE: {title} Synthetic Person\nDOB: 03/04/1950\nMedicare: 1234567890\n'


def test_a_title_never_fills_sex():
    for title in ('Mr', 'Mrs', 'Ms', 'Miss', 'Master', 'Dr'):
        fields, flags = intake.extract_fields(LETTER.format(title=title))
        if title in ('Mr', 'Mrs', 'Ms', 'Miss'):
            assert fields['name'] == 'Synthetic Person'
        assert not fields['sex']
        assert 'Missing sex' in flags
