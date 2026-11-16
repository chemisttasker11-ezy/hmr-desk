"""Synthetic tests for the fully local, non-AI report foundation."""
import json
from pathlib import Path

import manual_defaults
import reconciliation
import local_report_builder


def sample():
    return {
        "meds": [
            ["apixaban", "5 mg twice daily", "2.5 mg twice daily", "", ""],
            ["apixaban", "5 mg twice daily", "", "", ""],
            ["atorvastatin", "40 mg nightly", "40 mg nightly", "", ""],
        ],
        "other_meds": [["paracetamol", "500 mg as needed", "", ""]],
        "details": {"meds": [
            {"use_status": "taking", "packed": "", "as_instructed": False},
            {"use_status": "unknown", "packed": "", "as_instructed": False},
            {"use_status": "not_using", "packed": "", "as_instructed": False},
        ], "other_meds": [{"use_status": "taking"}]},
    }


def test_manual_reconciliation_flags_without_changing_record():
    source = sample()
    original = json.dumps(source, sort_keys=True)
    result = reconciliation.audit(source)
    assert json.dumps(source, sort_keys=True) == original
    codes = {f["code"] for f in result["flags"]}
    assert {"directions_differ", "use_unconfirmed", "possible_duplicate",
            "cessation_reason_missing"} <= codes
    assert result == reconciliation.audit(source)
    assert reconciliation.digest(source) == reconciliation.digest(source)


def test_manual_defaults_do_not_fabricate_clinical_text():
    defaults = manual_defaults.initial_text("Synthetic Patient", "Synthetic GP")
    assert defaults["reason"] == defaults["intro"] == ""
    assert set(manual_defaults.unresolved({**defaults, "needs_review": ["reason", "intro"]})) == {"reason", "intro"}
    assert "Synthetic Patient" in defaults["followup"] and "Synthetic Patient" in defaults["thanks"]
    assert "Synthetic Patient" not in manual_defaults.initial_text("", "Synthetic GP")["followup"]


def test_local_docx_build(tmp_path):
    from docx import Document
    data = dict(name="Synthetic Patient", assess_date="01/11/2026", report_date="02/11/2026",
                patient="Synthetic Patient", doctor="Synthetic GP", dear="Dear Synthetic GP,",
                thanks="Thank you", reason="Review of medicine use", intro="Interview completed",
                conditions="Atrial fibrillation", allergies="Penicillin",
                obs="BP 120/70", meds=[["apixaban", "5 mg twice daily", "", ""]],
                otc=[], ceased=[], path=[], issues=[{
                    "title": "Verify anticoagulant dose",
                    "rec": "Confirm indication and renal function",
                    "rationale": "Dose requires individual assessment"}],
                followup="Discuss with the referring GP")
    target = tmp_path / "report.docx"
    local_report_builder.render(data, target)
    doc = Document(target)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Verify anticoagulant dose" in text
    assert "Synthetic Patient" in text
    assert len(doc.tables) == 1
    try:
        local_report_builder.render(data, target)
        assert False, "must not overwrite report"
    except FileExistsError:
        pass
