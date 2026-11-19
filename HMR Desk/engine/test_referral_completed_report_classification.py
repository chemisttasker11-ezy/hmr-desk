"""Synthetic: a finished HMR report is not classified as a referral; referrals and GP replies are unchanged."""
import importlib.util
import tempfile
from pathlib import Path

import fitz
import pytest

import db
import referral_entry

INTAKE = Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py'
spec = importlib.util.spec_from_file_location('intake_under_test', INTAKE)
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)

REPORT = """Home Medicines Review Report
Report date: 01/01/2026
Patient details
Patient: Synthetic Patient   DOB: 01/01/1950
Reason for referral
Synthetic reason text
Medications
Synthetic Med 10 mg daily
This assessment has been completed.
Findings
1. Synthetic finding
Recommendations
1. Synthetic recommendation
Plan
Synthetic plan text
"""
REFERRAL = """Domiciliary Medication Management Review
Patient details
Patient: Synthetic Patient   DOB: 01/01/1950
Reason for referral for DMMR
Medical history
Current medications
Synthetic Med 10 mg daily
Assessment
Plan
Referral indications
"""


def test_completed_report_is_not_a_referral_nor_a_gp_reply():
    kind, _, flags = intake.classify(REPORT)
    assert kind == 'other' and kind != 'gp_response'
    assert any('completed HMR report' in f for f in flags)


@pytest.mark.parametrize('variant', [
    REPORT.replace('Findings\n', '1. Findings:\n').replace('Recommendations\n', 'Recommendations:\n'),
    REPORT.replace('Findings\n1. Synthetic finding\nRecommendations', 'Findings and Recommendations'),
    REPORT.replace('Report date:', 'Date of report -'),
])
def test_report_heading_variants_are_still_caught(variant):
    assert intake.classify(variant)[0] == 'other'


def test_genuine_referral_forms_stay_referrals():
    assert intake.classify(REFERRAL)[0] == 'referral'
    # Assessment and Plan headings alone never trigger the report rule.
    assert intake.classify(REFERRAL + 'Findings\nRecommendations\n')[0] == 'referral'
    # A referral that merely mentions a prior review in one sentence.
    assert intake.classify(REFERRAL + 'Patient had a review last year.\n')[0] == 'referral'


def test_report_without_a_report_date_is_not_reclassified():
    # The completed-assessment sentence is an existing GP-reply phrase, so only the date is removed along with it here.
    assert intake.classify(REPORT.replace('Report date: 01/01/2026\n', '').replace('This assessment has been completed.\n', ''))[0] == 'referral'


def test_gp_reply_markers_still_win():
    reply = REPORT + 'GP comments: synthetic\n'
    assert intake.classify(reply)[0] == 'gp_response'
    assert intake.classify('Medication management plan\nGP feedback: ok\nReferral patient medication')[0] == 'gp_response'


def _review_pdf(text):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    target = root / 'scripts' / 'intake' / 'intake.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(INTAKE.read_bytes())
    old = db.BASE
    db.BASE = str(root)
    conn = db.connect(str(root / 'test.db'))
    pdf = root / 'source.pdf'
    doc = fitz.open()
    for chunk in (text, 'Synthetic continuation page ' * 3):
        page = doc.new_page(); page.insert_textbox(fitz.Rect(40, 40, 550, 800), chunk)
    doc.save(pdf); doc.close()
    try:
        row = referral_entry.review(conn, [str(pdf)])['rows'][0]
        patients = conn.execute('SELECT count(*) FROM patients').fetchone()[0]
        return row, patients
    finally:
        conn.close(); db.BASE = old; temp.cleanup()


def test_entry_review_sends_completed_report_to_manual_with_no_extracted_fields():
    row, patients = _review_pdf(REPORT)
    assert row['status'] == 'manual' and row['kind'] == 'other'
    assert row['fields'] == {} and patients == 0
    assert any('completed HMR report' in f for f in row['flags'])


def test_entry_review_keeps_a_genuine_referral_in_review():
    row, _ = _review_pdf(REFERRAL)
    assert row['status'] == 'review' and row['kind'] == 'referral'
