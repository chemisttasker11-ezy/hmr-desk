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
_PATHOLOGY_WIDTHS_CM = (1.9, 3.3, 3.5, 3.9, 4.9)  # sums to the 17.5cm usable width (A4, 993/991 twip side margins)
_TEXT_WIDTH_CM = 17.5


def _fixed_layout(table, widths_cm):
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)
    # Word and LibreOffice size fixed-layout columns from the grid, so set it alongside cell widths.
    for col, width in zip(table._tbl.tblGrid.findall(qn('w:gridCol')), widths_cm):
        col.set(qn('w:w'), str(Cm(width).twips))
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)

# Style conventions from the host's corroborated spec of the pharmacist's latest pair of reports (non-identifying):
# A4; margins top 1985 / right 991 / bottom 1843 / left 993 twips; header 788 / footer 785; Montserrat runs, 9 pt bold
# labels; white title table with black title and date text; all table borders single 0.5 pt black; three details
# columns (patient, doctor, accredited pharmacist); heading colours blue 01A1DD (profile, findings), green 00B050
# (current and OTC medicines), red C00000 (ceased); table header fill 17365D; findings have a bold 10 pt orange
# E97132 lead-in then a borderless full-width block filled B8CCE4 with bold 10 pt black labels; table-based header
# and footer with a PAGE field. Wording and colours follow the operator's 16:06 spec. Not confirmed: body size, run colours of
# the conditions, allergies and observations headings, field-row arrangement of the details table, pathology heading.
# The output stays labelled provisional.
FONT = "Montserrat"
NAVY = "17365D"
BLUE_FILL = "B8CCE4"
HEAD_BLUE = "01A1DD"
HEAD_GREEN = "00B050"
HEAD_RED = "C00000"
LEAD_ORANGE = "E97132"
BLACK = "000000"
BODY_PT = 10


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


def _borders(table, val='single', size=4):
    tbl_pr = table._tbl.tblPr
    old = tbl_pr.find(qn('w:tblBorders'))
    if old is not None:
        tbl_pr.remove(old)
    borders = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        line = OxmlElement('w:' + side)
        line.set(qn('w:val'), val)
        if val != 'nil':
            line.set(qn('w:sz'), str(size))  # 4 eighths of a point = 0.5 pt
            line.set(qn('w:space'), '0')
            line.set(qn('w:color'), BLACK)
        borders.append(line)
    tbl_pr.append(borders)


def _run(paragraph, text, size=BODY_PT, bold=False, color=None):
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    _fonts(run._r.get_or_add_rPr())
    return run


def _cell_text(cell, text, size=BODY_PT, bold=False, color=None):
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(2)
    _run(paragraph, text, size, bold, color)


def _title_table(doc, date_text):
    """White, unfilled title table: black title and date text, single black borders."""
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    _borders(table)
    _cell_text(table.cell(0, 0), "Home Medication Review", 18, True, BLACK)
    _cell_text(table.cell(0, 1), date_text, 9, True, BLACK)
    _fixed_layout(table, (11.0, 6.5))
    return table


def _details_table(doc, patient, doctor):
    """Three columns: patient, doctor, accredited pharmacist. Pharmacist data is not in the report spec."""
    table = doc.add_table(rows=2, cols=3)
    table.style = "Table Grid"
    _borders(table)
    for cell, label, value in zip(table.rows[0].cells, ("Patient Details", "Doctor Details", "Accredited Pharmacist Details"),
                                  (None, None, None)):
        _cell_text(cell, label, 9, True)
    for cell, value in zip(table.rows[1].cells, (patient, doctor, "Not supplied in the report data")):
        _cell_text(cell, value, 9)
    _fixed_layout(table, (6.0, 6.0, 5.5))
    return table


def _heading(doc, text, color):
    paragraph = doc.add_paragraph(style="Heading 2")
    _run(paragraph, text, 14, True, color)
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
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))


def _plan_block(doc, rows):
    """Full-width single-column block, B8CCE4 fill, no borders, bold 10 pt black labels."""
    table = doc.add_table(rows=0, cols=1)
    _borders(table, 'nil')
    for label, text in rows:
        cell = table.add_row().cells[0]
        _shade(cell._tc.get_or_add_tcPr(), BLUE_FILL)
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(3)
        _run(paragraph, label, 10, True, BLACK)
        if text:
            _run(paragraph, text, BODY_PT)
    _fixed_layout(table, (_TEXT_WIDTH_CM,))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def _page_field(paragraph):
    for kind, text in (('begin', None), (None, ' PAGE '), ('end', None)):
        run = paragraph.add_run()
        _fonts(run._r.get_or_add_rPr())
        run.font.size = Pt(9)
        if kind:
            el = OxmlElement('w:fldChar')
            el.set(qn('w:fldCharType'), kind)
        else:
            el = OxmlElement('w:instrText')
            el.set(qn('xml:space'), 'preserve')
            el.text = text
        run._r.append(el)


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
    sec.top_margin = Twips(1985)
    sec.right_margin = Twips(991)
    sec.bottom_margin = Twips(1843)
    sec.left_margin = Twips(993)
    sec.header_distance = Twips(788)
    sec.footer_distance = Twips(785)
    styles = doc.styles
    _style(styles, "Normal", BODY_PT)
    _style(styles, "Heading 2", 14, bold=True, color=HEAD_BLUE, space_before=10, space_after=4)
    _style(styles, "Header", 9)
    _style(styles, "Footer", 9)
    # Table-based header and footer. The marker repeats on every printed page, again in bold under the title.
    header = sec.header
    htable = header.add_table(1, 1, Cm(_TEXT_WIDTH_CM))
    _borders(htable)
    _cell_text(htable.cell(0, 0), PROVISIONAL_LABEL, 9, True)
    footer = sec.footer
    ftable = footer.add_table(1, 2, Cm(_TEXT_WIDTH_CM))
    _borders(ftable)
    _cell_text(ftable.cell(0, 0), PROVISIONAL_LABEL, 9, True)
    ftable.cell(0, 1).paragraphs[0].add_run("Page ")
    _page_field(ftable.cell(0, 1).paragraphs[0])
    _title_table(doc, "Assessment date: " + _display_date(data["assess_date"]) + "    Report date: " + _display_date(data["report_date"]))
    marker = doc.add_paragraph()
    _run(marker, PROVISIONAL_LABEL, 9, True)
    marker.paragraph_format.space_before = Pt(6)
    _heading(doc, "Patient Profile", HEAD_BLUE)
    _details_table(doc, data["patient"], data["doctor"])
    doc.add_paragraph(data["dear"])
    for field in ("thanks", "reason", "intro"):
        if data[field].strip():
            doc.add_paragraph(data[field])
    # Run colours of these three headings are not in the host spec: left at the default text colour.
    for heading, key in (("Current Conditions:", "conditions"), ("Allergies", "allergies"),
                         ("Obs from interview", "obs")):
        if data[key].strip():
            _heading(doc, heading, BLACK)
            doc.add_paragraph(data[key])
    for heading, key, labels, color in (
        ("Current medication as per the patient", "meds", ("Drug Regimen", "Directions", "Comments", "Recommendation"), HEAD_GREEN),
        ("OTC medications / Additional medications (Identified During Interview)", "otc", ("Drug Regimen", "Directions", "Comments"), HEAD_GREEN),
        ("Medication as per the referral ceased or not used", "ceased", ("Drug Regimen", "Directions", "Comments"), HEAD_RED),
        ("Pathology", "path", ("Test", "Result", "Unit", "Reference range", "Source / notes"), HEAD_BLUE),
    ):
        if not data[key]:
            continue
        _heading(doc, heading, color)
        table = doc.add_table(rows=1, cols=len(labels))
        table.style = "Table Grid"
        _borders(table)
        for cell, label in zip(table.rows[0].cells, labels):
            _cell_text(cell, label, 9, True)
        for values in data[key]:
            for cell, value in zip(table.add_row().cells, values):
                _cell_text(cell, value, 9)
        _header_row(table)
        widths = _PATHOLOGY_WIDTHS_CM if key == "path" else tuple(_TEXT_WIDTH_CM / len(labels) for _ in labels)
        _fixed_layout(table, widths)
    _heading(doc, "Review Findings", HEAD_BLUE)
    for index, finding in enumerate(data["issues"], 1):
        lead = doc.add_paragraph()
        _run(lead, str(index) + ". " + finding["title"], 10, True, LEAD_ORANGE)
        lead.paragraph_format.keep_with_next = True
        _plan_block(doc, (("Plan/Feedback", ""), ("Recommendation: ", finding["rec"]), ("Rationale: ", finding["rationale"])))
    if data["followup"].strip():
        _heading(doc, "Follow-up", BLACK)
        _plan_block(doc, (("Follow-up: ", data["followup"]),))
    _run(doc.add_paragraph(), "Yours Sincerely,", 10)
    signoff = doc.add_paragraph()
    _run(signoff, "Pharmacist name, credentials, phone and email: not supplied in the report data (provisional).", 9, True)
    doc.save(target)
    return target
