"""Local deterministic DOCX renderer for pharmacist-reviewed HMR reports."""
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Twips


def _display_date(value):
    """Display dates as DD/MM/YYYY like the generated report date; ISO strings from visit records
    otherwise print next to it in a clashing format. Value itself is unchanged, display only."""
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value.strip())
    return match[3] + '/' + match[2] + '/' + match[1] if match else value


# Pathology provenance text (verified-by, sample date, source) is sentence-length; equal-width
# autofit squeezed it into one-word lines. Fixed widths give the notes column room to read.
_PATHOLOGY_WIDTHS_CM = (2.0, 3.0, 3.0, 2.2, 4.4)  # sums to the 14.6cm usable width (A4, 1800 twip side margins)


def _fixed_layout(table, widths_cm):
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)
    # Word and LibreOffice size fixed-layout columns from the grid, so set it alongside cell widths.
    for col, width in zip(table._tbl.tblGrid.findall(qn('w:gridCol')), widths_cm):
        col.set(qn('w:w'), str(Cm(width).twips))

# Style conventions taken from the pharmacist's recent completed reports (host comparison, non-identifying):
# A4, Aptos throughout at 10 to 18 pt, margins 1400 top / 1440 bottom / 1800 sides (twips), a compact black
# title and date box, boxed profile blocks, navy table headers and light-blue plan and feedback blocks.
# Exact navy and blue values are not confirmed from the reference. The output stays labelled provisional.
FONT = "Aptos"
NAVY = "1F3864"
BLUE_FILL = "DEEAF6"
BLUE_EDGE = "2E75B6"
BLACK = "000000"


def _fonts(style_or_run_element, name=FONT):
    """Set the font explicitly for every script and drop theme-font attributes that would override it."""
    rpr = style_or_run_element
    fonts = rpr.find(qn('w:rFonts'))
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        rpr.insert(0, fonts)
    for attr in ('w:asciiTheme', 'w:hAnsiTheme', 'w:eastAsiaTheme', 'w:cstheme'):
        key = qn(attr)
        if key in fonts.attrib:
            del fonts.attrib[key]
    for attr in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
        fonts.set(qn(attr), name)


def _style(styles, name, size, bold=False, color=None, space_before=0, space_after=4):
    style = styles[name]
    style.font.name = FONT
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = False
    if color:
        style.font.color.rgb = RGBColor.from_string(color)
    _fonts(style.element.get_or_add_rPr())
    fmt = style.paragraph_format
    fmt.space_before = Pt(space_before)
    fmt.space_after = Pt(space_after)


def _shade(element_pr, fill):
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), fill)
    element_pr.append(shading)


def _box(paragraph, fill=None, edge="808080", left_only=False, size=6):
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement('w:pBdr')
    for side in (('left',) if left_only else ('top', 'left', 'bottom', 'right')):
        line = OxmlElement('w:' + side)
        line.set(qn('w:val'), 'single')
        line.set(qn('w:sz'), str(size * 2 if left_only else size))
        line.set(qn('w:space'), '4')
        line.set(qn('w:color'), edge)
        borders.append(line)
    ppr.append(borders)
    if fill:
        _shade(ppr, fill)


def _banner(doc, text, size, fill=BLACK):
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    _fonts(run._r.get_or_add_rPr())
    ppr = paragraph._p.get_or_add_pPr()
    _shade(ppr, fill)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def _header_row(table):
    first = table.rows[0]
    trpr = first._tr.get_or_add_trPr()
    trpr.append(OxmlElement('w:tblHeader'))
    for cell in first.cells:
        _shade(cell._tc.get_or_add_tcPr(), NAVY)
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))


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
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Twips(1400)
    sec.bottom_margin = Twips(1440)
    sec.left_margin = Twips(1800)
    sec.right_margin = Twips(1800)
    styles = doc.styles
    _style(styles, "Normal", 10.5)
    _style(styles, "Heading 2", 14, bold=True, color=NAVY, space_before=10, space_after=4)
    _style(styles, "Heading 3", 12, bold=True, color=NAVY, space_before=8, space_after=3)
    _style(styles, "Header", 9)
    # Repeat the marker in the page header so every printed page carries it, then again in bold
    # directly under the title where the reader starts. The LibreOffice PDF conversion keeps both.
    header_run = sec.header.paragraphs[0].add_run(PROVISIONAL_LABEL)
    header_run.bold = True
    header_run.font.size = Pt(9)
    _fonts(header_run._r.get_or_add_rPr())
    _banner(doc, "Home Medicines Review", 18)
    _banner(doc, "Assessment: " + _display_date(data["assess_date"]) + "    Report: " + _display_date(data["report_date"]), 10)
    marker = doc.add_paragraph()
    marker_run = marker.add_run(PROVISIONAL_LABEL)
    marker_run.bold = True
    marker.paragraph_format.space_before = Pt(6)
    doc.add_heading("Patient details", level=2)
    _box(doc.add_paragraph(data["patient"]))
    doc.add_heading("Referring doctor", level=2)
    _box(doc.add_paragraph(data["doctor"]))
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
        _header_row(table)
        if key == "path":
            table.autofit = False
            _fixed_layout(table, _PATHOLOGY_WIDTHS_CM)
            for row in table.rows:
                for cell, width in zip(row.cells, _PATHOLOGY_WIDTHS_CM):
                    cell.width = Cm(width)
    doc.add_heading("Medication-related findings and recommendations", level=2)
    for index, finding in enumerate(data["issues"], 1):
        doc.add_heading(str(index) + ". " + finding["title"], level=3)
        for label, key in (("Recommendation: ", "rec"), ("Rationale: ", "rationale")):
            block = doc.add_paragraph(label + finding[key])
            _box(block, fill=BLUE_FILL, edge=BLUE_EDGE, left_only=True)
    if data["followup"].strip():
        doc.add_heading("Follow-up", level=2)
        _box(doc.add_paragraph(data["followup"]), fill=BLUE_FILL, edge=BLUE_EDGE, left_only=True)
    doc.save(target)
    return target
