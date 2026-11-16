"""Local deterministic DOCX renderer for pharmacist-reviewed HMR reports."""
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt


def render(data, target):
    """Build from validated report spec. Does not invent findings or overwrite files."""
    target = Path(target)
    if target.exists():
        raise FileExistsError("Report output already exists")
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2)
    sec.bottom_margin = Cm(2)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10)
    doc.add_heading("Home Medicines Review", 0)
    doc.add_paragraph("Assessment: " + data["assess_date"] + "    Report: " + data["report_date"])
    doc.add_heading("Patient details", level=2)
    doc.add_paragraph(data["patient"])
    doc.add_heading("Referring doctor", level=2)
    doc.add_paragraph(data["doctor"])
    doc.add_paragraph(data["dear"])
    for field in ("thanks", "reason", "intro"):
        if data[field].strip():
            doc.add_paragraph(data[field])
    for heading, key in (("Medical conditions", "conditions"),
                         ("Allergies and adverse reactions", "allergies"),
                         ("Observations", "obs")):
        if data[key].strip():
            doc.add_heading(heading, level=2)
            doc.add_paragraph(data[key])
    for heading, key, labels in (
        ("Current medicines", "meds", ("Medicine", "Actual use", "Notes", "Review")),
        ("Non-prescription medicines", "otc", ("Medicine", "Use", "Notes")),
        ("Ceased medicines", "ceased", ("Medicine", "Referral directions", "Notes")),
        ("Pathology", "path", ("Test", "Result", "Unit", "Reference range", "Source / notes")),
    ):
        if not data[key]:
            continue
        doc.add_heading(heading, level=2)
        table = doc.add_table(rows=1, cols=len(labels))
        table.style = "Table Grid"
        for cell, label in zip(table.rows[0].cells, labels):
            cell.text = label
        for values in data[key]:
            for cell, value in zip(table.add_row().cells, values):
                cell.text = value
    doc.add_heading("Medication-related findings and recommendations", level=2)
    for index, finding in enumerate(data["issues"], 1):
        doc.add_heading(str(index) + ". " + finding["title"], level=3)
        doc.add_paragraph("Recommendation: " + finding["rec"])
        doc.add_paragraph("Rationale: " + finding["rationale"])
    if data["followup"].strip():
        doc.add_heading("Follow-up", level=2)
        doc.add_paragraph(data["followup"])
    doc.save(target)
    return target
