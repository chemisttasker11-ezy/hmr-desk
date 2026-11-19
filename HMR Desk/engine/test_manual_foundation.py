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
    assert set(manual_defaults.unresolved({**defaults, "needs_review": ["reason", "intro"]})) == {"reason", "intro", "followup_decision"}
    assert "Synthetic Patient" in defaults["thanks"]
    # No follow-up or 12-month assertion is generated before the pharmacist decides.
    assert defaults["followup_decision"] == "" and "12 months" not in defaults["followup"] and "again" not in defaults["followup"]
    assert "followup_decision" in manual_defaults.unresolved({**defaults, "needs_review": ["followup"]})
    assert manual_defaults.unresolved({"needs_review": ["followup"], "followup": "x"}) == []  # legacy spec without the key


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
    assert "Synthetic Patient" in [c.text for c in doc.tables[1]._cells]
    assert len(doc.tables) == 5  # title, details, medicines, finding block, follow-up block
    try:
        local_report_builder.render(data, target)
        assert False, "must not overwrite report"
    except FileExistsError:
        pass


def test_local_docx_visibly_marks_provisional_layout(tmp_path):
    from docx import Document
    data = dict(name="Synthetic Patient", assess_date="01/11/2026", report_date="02/11/2026",
                patient="Synthetic Patient", doctor="Synthetic GP", dear="Dear Synthetic GP,",
                thanks="", reason="", intro="",
                conditions="", allergies="",
                obs="", meds=[], otc=[], ceased=[], path=[], issues=[{
                    "title": "Verify anticoagulant dose",
                    "rec": "Confirm indication and renal function",
                    "rationale": "Dose requires individual assessment"}],
                followup="")
    target = tmp_path / "report.docx"
    local_report_builder.render(data, target)
    doc = Document(target)
    body = "\n".join(p.text for p in doc.paragraphs)
    header = "\n".join(c.text for t in doc.sections[0].header.tables for c in t._cells)
    # Body and repeating page header both carry the marker so no page reads as the approved layout.
    assert local_report_builder.PROVISIONAL_LABEL in body
    assert local_report_builder.PROVISIONAL_LABEL in header
    # The marker states layout provenance only; it must not comment on clinical content approval.
    label = local_report_builder.PROVISIONAL_LABEL.lower()
    assert "layout" in label and "template" in label
    assert "clinic" not in label and "content" not in label
    assert any(run.bold for p in doc.paragraphs if p.text == local_report_builder.PROVISIONAL_LABEL for run in p.runs)


def test_local_docx_readable_pathology_notes_and_consistent_dates(tmp_path):
    from docx import Document
    from docx.shared import Cm
    data = dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026",
                patient="Synthetic Patient", doctor="Synthetic GP", dear="Dear Synthetic GP,",
                thanks="", reason="", intro="",
                conditions="", allergies="",
                obs="", meds=[], otc=[], ceased=[],
                path=[["Synthetic eGFR", "78", "mL/min/1.73m2", ">=60",
                       "Verified by Test Pharmacist at 2026-11-17T12:33:43+00:00 | Sample: 2026-11-10 | Source: 1-SYNTHETIC referral p.1 | synthetic acceptance entry"]],
                issues=[{
                    "title": "Verify anticoagulant dose",
                    "rec": "Confirm indication and renal function",
                    "rationale": "Dose requires individual assessment"}],
                followup="")
    target = tmp_path / "report.docx"
    local_report_builder.render(data, target)
    doc = Document(target)
    text = "\n".join([p.text for p in doc.paragraphs] + [c.text for c in doc.tables[0]._cells])
    # Both dates display in the same DD/MM/YYYY format; the stored values are not rewritten.
    title = doc.tables[0]
    assert (title.cell(0, 2).text, title.cell(1, 2).text) == ("17/11/2026", "17/11/2026")
    assert "2026-11-17" not in text
    assert local_report_builder._display_date("not a date") == "not a date"
    # Provenance and value columns are wide enough to wrap readably without splitting
    # unit strings like "mL/min/1.73m2" mid-token.
    table = next(t for t in doc.tables if t.rows[0].cells[0].text == "Test")
    widths = [cell.width for cell in table.rows[0].cells]
    assert widths[-1] >= Cm(4.1)
    assert widths[1] >= Cm(3) and widths[2] >= Cm(3)
    assert all(w is not None for w in widths)


def test_required_decision_never_generates_timing():
    base = {**manual_defaults.initial_text("Synthetic Patient", "GP"), "name": "Synthetic Patient"}
    req = manual_defaults.apply_followup_decision({**base, "followup_decision": "required"})
    assert "12 months" not in req["followup"] and "few months" not in req["followup"]
    assert manual_defaults.unresolved(req) == ["followup_plan"]
    entered = {**req, "followup": "Review again after the dose change, timing as entered by the pharmacist."}
    assert manual_defaults.unresolved(entered) == [] and manual_defaults.apply_followup_decision(entered)["followup"] == entered["followup"]
    stock = {**req, "followup": manual_defaults.required_followup("Synthetic Patient")}
    assert manual_defaults.unresolved(stock) == ["followup_plan"]
    assert manual_defaults.apply_followup_decision(stock)["followup"] == manual_defaults.NEUTRAL_FOLLOWUP


def test_not_required_wording_is_proposed_until_reviewed_for_that_exact_text():
    base = {**manual_defaults.initial_text("Synthetic Patient", "GP"), "name": "Synthetic Patient", "followup_decision": "not_required"}
    d = manual_defaults.apply_followup_decision(base)
    assert "No follow-up interview is planned" in d["followup"] and manual_defaults.unresolved(d) == ["followup_review"]
    ok = {**d, "followup_reviewed_sha256": manual_defaults.text_sha(d["followup"], "not_required")}
    assert manual_defaults.unresolved(ok) == []
    assert manual_defaults.unresolved({**ok, "followup": d["followup"] + " Edited."}) == []  # authored edit is no longer generated wording


def test_legacy_stock_flagged_for_any_name_until_reviewed_and_new_specs_cannot_drop_the_key():
    stock = manual_defaults.required_followup("Someone Else")  # name need not match the spec name
    legacy = {"name": "Synthetic Patient", "followup": stock, "needs_review": []}
    assert manual_defaults.unresolved(legacy) == ["followup_review"]
    assert manual_defaults.apply_followup_decision(legacy)["followup"] == stock  # words preserved
    assert manual_defaults.unresolved({**legacy, "followup_reviewed_sha256": manual_defaults.text_sha(stock, "")}) == []
    assert manual_defaults.unresolved({**legacy, "followup": "My own plan."}) == []
    new = manual_defaults.initial_text("Synthetic Patient", "GP"); del new["followup_decision"]
    assert manual_defaults.unresolved(new) == ["followup_decision"]
