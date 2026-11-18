"""Local deterministic DOCX renderer for pharmacist-reviewed HMR reports."""
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


def _display_date(value):
    """Display dates as DD/MM/YYYY like the generated report date; ISO strings from visit records
    otherwise print next to it in a clashing format. Value itself is unchanged, display only."""
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value.strip())
    return match[3] + '/' + match[2] + '/' + match[1] if match else value


# Pathology provenance text (verified-by, sample date, source) is sentence-length; equal-width
# autofit squeezed it into one-word lines. Fixed widths give the notes column room to read.
_PATHOLOGY_WIDTHS_CM = (2.6, 3.2, 3.2, 2.6, 5.0)  # sums to the 16.6cm usable width below


def _fixed_layout(table, widths_cm):
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)
    # Word and LibreOffice size fixed-layout columns from the grid, so set it alongside cell widths.
    for col, width in zip(table._tbl.tblGrid.findall(qn('w:gridCol')), widths_cm):
        col.set(qn('w:w'), str(Cm(width).twips))

# Visible provenance marker for every locally rendered report. It states layout provenance only:
# the owner-approved template was not used. It says nothing about clinical content, which the
# pharmacist always reviews before sign-off regardless of which renderer produced the draft.
PROVISIONAL_LABEL = "PROVISIONAL LOCAL LAYOUT - not the owner-approved report template"


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
    # Repeat the marker in the page header so every printed page carries it, then again in bold
    # directly under the title where the reader starts. The LibreOffice PDF conversion keeps both.
    header_run = sec.header.paragraphs[0].add_run(PROVISIONAL_LABEL)
    header_run.bold = True
    doc.add_heading("Home Medicines Review", 0)
    marker = doc.add_paragraph()
    marker_run = marker.add_run(PROVISIONAL_LABEL)
    marker_run.bold = True
    doc.add_paragraph("Assessment: " + _display_date(data["assess_date"]) + "    Report: " + _display_date(data["report_date"]))
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
        if key == "path":
            table.autofit = False
            _fixed_layout(table, _PATHOLOGY_WIDTHS_CM)
            for row in table.rows:
                for cell, width in zip(row.cells, _PATHOLOGY_WIDTHS_CM):
                    cell.width = Cm(width)
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
