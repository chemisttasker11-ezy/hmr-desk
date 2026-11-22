"""The standalone intake CLI must retain GP-added FreeText and issue a warning.

Uses a fictional PDF generated at test runtime. No real records or filenames.
"""
import importlib.util
import json
import sys

import fitz


def test_intake_cli_freetext_retained_and_warning(tmp_path, monkeypatch):
    source = tmp_path / 'fictional-referral.pdf'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((35, 65), 'Home Medicines Review Referral')
    page.insert_text((35, 95), 'Patient Details')
    page.insert_text((35, 125), 'Name: Ms Fictional Example')
    page.insert_text((35, 155), 'Date of Birth: 01/01/1960')
    page.insert_text((35, 185), 'Current Medications')
    annotation = page.add_freetext_annot(
        fitz.Rect(35, 210, 450, 300),
        'GP additional medication: Fictamed 20 mg daily',
        text_color=(0, 0, 1))
    annotation.update()
    doc.save(source)
    doc.close()
    before = source.read_bytes()
    import pathlib
    script = pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py'
    spec = importlib.util.spec_from_file_location('standalone_referral_intake', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, 'argv', ['intake.py', str(tmp_path), '--out', str(tmp_path)])
    module.main()
    results = sorted(tmp_path.glob('intake_report_*.json'))
    assert len(results) == 1
    rows = json.loads(results[0].read_text(encoding='utf-8'))
    assert len(rows) == 1
    assert any('FreeText annotations' in flag and 'preserved' in flag for flag in rows[0]['flags'])
    assert source.read_bytes() == before
