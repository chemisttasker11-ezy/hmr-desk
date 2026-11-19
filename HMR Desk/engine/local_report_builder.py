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
_TEXT_WIDTH_CM = 17.5


def _tw(width):
    """Column width: ints are twips (reference grids), floats are cm."""
    return width if isinstance(width, int) else Cm(width).twips


def _fixed_layout(table, widths_cm):
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    table._tbl.tblPr.append(layout)
    # Word and LibreOffice size fixed-layout columns from the grid, so set it alongside cell widths.
    for col, width in zip(table._tbl.tblGrid.findall(qn('w:gridCol')), widths_cm):
        col.set(qn('w:w'), str(_tw(width)))
    table.autofit = False
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Twips(_tw(width))
    _direct_table_props(table, sum(_tw(w) for w in widths_cm))


_TBLPR_ORDER = ('tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize', 'tblStyleColBandSize', 'tblW',
                'jc', 'tblCellSpacing', 'tblInd', 'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook')


def _direct_table_props(table, total_tw):
    """Reference tables use direct formatting only: no named table style, tblW = grid sum, tblInd -5, fixed layout,
    tblLook 04A0. Default cell margins (0 top/bottom, 108 left/right) come from the document default table style."""
    pr = table._tbl.tblPr
    for tag in ('tblStyle', 'tblW', 'tblInd', 'tblLook'):
        for el in pr.findall(qn('w:' + tag)):
            pr.remove(el)
    width = OxmlElement('w:tblW')
    width.set(qn('w:w'), str(total_tw))
    width.set(qn('w:type'), 'dxa')
    indent = OxmlElement('w:tblInd')
    indent.set(qn('w:w'), '-5')
    indent.set(qn('w:type'), 'dxa')
    look = OxmlElement('w:tblLook')
    for key, val in (('val', '04A0'), ('firstRow', '1'), ('lastRow', '0'), ('firstColumn', '1'), ('lastColumn', '0'),
                     ('noHBand', '0'), ('noVBand', '1')):
        look.set(qn('w:' + key), val)
    for el in (width, indent, look):
        pr.append(el)
    kids = sorted(list(pr), key=lambda e: _TBLPR_ORDER.index(e.tag.split('}')[1]) if e.tag.split('}')[1] in _TBLPR_ORDER else 99)
    for el in list(pr):
        pr.remove(el)
    for el in kids:
        pr.append(el)

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
BODY_PT = 12  # Normal paragraph style per spec
PLAN_PT = 10
# Reference column grids (twips) from the host spec; contents of the reference cells are only partly known.
TITLE_GRID = (6487, 1985, 1701)
DETAILS_GRID = (2965, 4299, 2909)
PROFILE_GRID = (2660, 7478)
MEDS_GRID = (2520, 1800, 2700, 3145)  # 4 columns, host map table 5 of the newest reference
OTC_GRID = (4140, 2070, 3870)  # 3 columns, host map tables 6 and 7
CEASED_GRID = (4140, 2070, 3870)
RESULTS_GRID = (1885, 1105, 1870, 1620, 3820)
PLAN_WIDTH = 10138


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


def _title_table(doc, assess, report):
    """Unfilled 3-column, 2-row title table, black text. Title in Heading 1 (16 pt bold black), spanning both rows."""
    table = doc.add_table(rows=2, cols=3)
    _borders(table)
    title = table.cell(0, 0).merge(table.cell(1, 0))
    title.paragraphs[0].style = doc.styles["Heading 1"]
    _run(title.paragraphs[0], "Home Medication Review", 16, True, BLACK)
    _cell_text(table.cell(0, 1), "Assessment date:", 9, True)
    _cell_text(table.cell(0, 2), assess, 9)
    _cell_text(table.cell(1, 1), "Report date:", 9, True)
    _cell_text(table.cell(1, 2), report, 9)
    _fixed_layout(table, TITLE_GRID)
    return table


def _details_table(doc, patient, doctor):
    """Three columns: patient, doctor, accredited pharmacist. Pharmacist data is not in the report spec."""
    table = doc.add_table(rows=2, cols=3)
    _borders(table)
    for cell, label, value in zip(table.rows[0].cells, ("Patient Details", "Doctor Details", "Accredited Pharmacist Details"),
                                  (None, None, None)):
        _cell_text(cell, label, 9, True)
    for cell, value in zip(table.rows[1].cells, (patient, doctor, "Not supplied in the report data")):
        _cell_text(cell, value, 9)
    _fixed_layout(table, DETAILS_GRID)
    return table


def _heading(doc, text, color):
    paragraph = doc.add_paragraph(style="Heading 2")
    _run(paragraph, text, 12, True, color)
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def _header_row(table, fill=NAVY):
    """Header row: fill 17365D and NO explicit text colour (auto), as in the reference. Auto text renders white on the
    dark fill. Pass fill=None for the results table, which has no fill in the reference."""
    first = table.rows[0]
    trpr = first._tr.get_or_add_trPr()
    trpr.append(OxmlElement('w:tblHeader'))
    for cell in first.cells:
        if fill:
            _shade(cell._tc.get_or_add_tcPr(), fill)
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
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
        _run(paragraph, label, PLAN_PT, True, BLACK)
        if text:
            _run(paragraph, text, PLAN_PT)
    _fixed_layout(table, (PLAN_WIDTH,))
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
    _style(styles, "Heading 1", 16, bold=True, color=BLACK, space_before=0, space_after=2)
    _style(styles, "Heading 2", 12, bold=True, color=HEAD_BLUE, space_before=10, space_after=4)
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
    _title_table(doc, _display_date(data["assess_date"]), _display_date(data["report_date"]))
    marker = doc.add_paragraph()
    _run(marker, PROVISIONAL_LABEL, 9, True)
    marker.paragraph_format.space_before = Pt(6)
    _details_table(doc, data["patient"], data["doctor"])
    _heading(doc, "Patient Profile", HEAD_BLUE)
    # Reference profile table: 2 columns, 3 rows. Row labels are the earlier host heading wording. The row-to-field
    # correspondence is inferred from the row count and is unconfirmed.
    profile = doc.add_table(rows=0, cols=2)
    _borders(profile)
    for label, key in (("Current Conditions:", "conditions"), ("Allergies", "allergies"), ("Obs from interview", "obs")):
        cells = profile.add_row().cells
        _cell_text(cells[0], label, 9, True)
        _cell_text(cells[1], data[key].strip() or "Not recorded in the report data", 9)
    _fixed_layout(profile, PROFILE_GRID)
    doc.add_paragraph(data["dear"])
    for field in ("thanks", "reason", "intro"):
        if data[field].strip():
            doc.add_paragraph(data[field])
    for heading, key, labels, color, grid, fill in (
        ("Current medication as per the patient", "meds", ("Drug Regimen", "Dose", "Comments", "Recommendation"), HEAD_GREEN, MEDS_GRID, NAVY),
        ("OTC medications / Additional medications (Identified During Interview)", "otc", ("Drug Regimen", "Directions", "Comments"), HEAD_GREEN, OTC_GRID, NAVY),
        ("Medication as per the referral ceased or not used", "ceased", ("Drug Regimen", "Directions", "Comments"), HEAD_RED, CEASED_GRID, NAVY),
    ):
        if not data[key]:
            continue
        _heading(doc, heading, color)
        table = doc.add_table(rows=1, cols=len(labels))
        _borders(table)
        for cell, label in zip(table.rows[0].cells, labels):
            _cell_text(cell, label, 9, True)
        for values in data[key]:
            for cell, value in zip(table.add_row().cells, values):
                _cell_text(cell, value, 9)
        _header_row(table, fill)
        _fixed_layout(table, grid)
    _heading(doc, "Review Findings", HEAD_BLUE)
    for index, finding in enumerate(data["issues"], 1):
        lead = doc.add_paragraph()
        _run(lead, str(index) + ". " + finding["title"], PLAN_PT, True, LEAD_ORANGE)
        lead.paragraph_format.keep_with_next = True
        _plan_block(doc, (("Plan/Feedback: ", finding["rec"]), ("Rationale: ", finding["rationale"])))
    if data["path"]:
        when = _display_date(str(data.get("path_date") or "").strip())
        _heading(doc, "Pathology results" + (": " + when if when else ""), HEAD_BLUE)
        table = doc.add_table(rows=1, cols=5)
        _borders(table)
        # Fifth label stays "Source / notes": that column holds provenance text, not a pharmacist interpretation.
        for cell, label in zip(table.rows[0].cells, ("Test", "Result", "Units", "Normal range", "Source / notes")):
            _cell_text(cell, label, 9, True)
        for values in data["path"]:
            for cell, value in zip(table.add_row().cells, values):
                _cell_text(cell, value, 9)
        _header_row(table, None)
        _fixed_layout(table, RESULTS_GRID)
    if data["followup"].strip():
        _heading(doc, "Follow-up", BLACK)
        _plan_block(doc, (("Follow-up: ", data["followup"]),))
    _run(doc.add_paragraph(), "Yours Sincerely,", PLAN_PT, True)
    signoff = doc.add_paragraph()
    _run(signoff, "Pharmacist name, credentials, phone and email: not supplied in the report data (provisional).", PLAN_PT, True)
    doc.save(target)
    return target
