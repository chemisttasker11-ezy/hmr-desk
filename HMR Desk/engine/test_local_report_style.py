"""Style conventions of the local provisional report (synthetic data only).

Targets come from the host's corroborated spec of the pharmacist's latest pair of reports (non-identifying).
Unconfirmed: heading wording, body size, colour of the conditions section, label text of the medicine tables.
These tests pin the spec'd structure. The renderer stays labelled provisional."""
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Twips

import local_report_builder as builder


def data():
    return dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026",
                patient="Synthetic Patient", doctor="Dr Example GP", dear="Dear Dr Example,",
                thanks="Thank you", reason="Reason", intro="Intro", conditions="Condition", allergies="Allergy",
                obs="Obs", meds=[["a", "b", "c", "d"]], otc=[["o", "p", "q"]], ceased=[["x", "y", "z"]],
                path=[["eGFR", "68", "mL/min/1.73m2", "> 60", "Synthetic source"]],
                issues=[{"title": "Finding", "rec": "Do this", "rationale": "Because"}], followup="Follow up")


def render(tmp_path):
    target = tmp_path / "r.docx"
    builder.render(data(), target)
    return Document(target)


def fills(element):
    return {s.get(qn('w:fill')) for s in element.iter(qn('w:shd'))}


def heading_colors(doc):
    out = {}
    for p in doc.paragraphs:
        if p.style.name == "Heading 2":
            out[p.text] = str(p.runs[0].font.color.rgb)
    return out


def test_provisional_marker_survives(tmp_path):
    doc = render(tmp_path)
    assert builder.PROVISIONAL_LABEL in "\n".join(p.text for p in doc.paragraphs)
    assert builder.PROVISIONAL_LABEL in "\n".join(c.text for t in doc.sections[0].header.tables for c in t._cells)


def test_page_geometry_matches_spec(tmp_path):
    s = render(tmp_path).sections[0]
    assert abs(s.page_width - Cm(21.0)) < 1000 and abs(s.page_height - Cm(29.7)) < 1000
    assert (s.top_margin, s.right_margin, s.bottom_margin, s.left_margin) == (Twips(1985), Twips(991), Twips(1843), Twips(993))
    assert (s.header_distance, s.footer_distance) == (Twips(788), Twips(785))


def test_fonts_are_explicit_montserrat_with_no_theme_override(tmp_path):
    doc = render(tmp_path)
    for name in ("Normal", "Heading 2", "Header", "Footer"):
        fonts = doc.styles[name].element.rPr.find(qn('w:rFonts'))
        assert fonts.get(qn('w:ascii')) == "Montserrat" and fonts.get(qn('w:hAnsi')) == "Montserrat"
        assert not [a for a in fonts.attrib if a.lower().endswith('theme')]
    for run in doc.tables[2].rows[0].cells[0].paragraphs[0].runs:
        assert run.font.size.pt == 9 and run.bold


def test_title_table_is_white_with_black_text_and_single_half_point_borders(tmp_path):
    doc = render(tmp_path)
    table = doc.tables[0]
    assert not fills(table._tbl)
    assert table.cell(0, 0).text == "Home Medication Review"
    assert [table.cell(0, 1).text, table.cell(0, 2).text] == ["Assessment date:", "17/11/2026"]
    assert [table.cell(1, 1).text, table.cell(1, 2).text] == ["Report date:", "17/11/2026"]
    for t in doc.tables[:3]:
        for side in t._tbl.tblPr.find(qn('w:tblBorders')):
            assert side.get(qn('w:val')) == 'single' and side.get(qn('w:sz')) == '4' and side.get(qn('w:color')) == '000000'


def test_details_table_has_patient_doctor_pharmacist_columns(tmp_path):
    table = render(tmp_path).tables[1]
    assert [c.text for c in table.rows[0].cells] == ["Patient Details", "Doctor Details", "Accredited Pharmacist Details"]
    assert table.rows[1].cells[0].text == "Synthetic Patient" and table.rows[1].cells[1].text == "Dr Example GP"
    assert "Not supplied" in table.rows[1].cells[2].text


def test_heading_order_and_colours(tmp_path):
    colours = heading_colors(render(tmp_path))
    assert list(colours)[:1] == ["Patient Profile"] and list(colours)[-2:] == ["Review Findings", "Follow-up"]
    order = [h for h in colours if h in ("Current medication as per the patient", "OTC medications / Additional medications (Identified During Interview)",
                                         "Medication as per the referral ceased or not used", "Review Findings")]
    assert order == ["Current medication as per the patient", "OTC medications / Additional medications (Identified During Interview)",
                     "Medication as per the referral ceased or not used", "Review Findings"]
    assert colours["Patient Profile"] == colours["Review Findings"] == "01A1DD"
    assert colours["Current medication as per the patient"] == colours["OTC medications / Additional medications (Identified During Interview)"] == "00B050"
    assert colours["Medication as per the referral ceased or not used"] == "C00000"


def test_medicine_tables_have_17365d_repeating_header_and_spec_column_counts(tmp_path):
    doc = render(tmp_path)
    meds, otc, ceased = doc.tables[2], doc.tables[3], doc.tables[4]
    assert [len(t.columns) for t in (meds, otc, ceased)] == [4, 3, 3]
    assert [c.text for c in meds.rows[0].cells] == ["Drug Regimen", "Directions", "Comments", "Recommendation"]
    assert [c.text for c in otc.rows[0].cells] == [c.text for c in ceased.rows[0].cells] == ["Drug Regimen", "Directions", "Comments"]
    for t in (meds, otc, ceased, doc.tables[5]):
        assert fills(t.rows[0]._tr) == {"17365D"}
        assert t.rows[0]._tr.trPr.find(qn('w:tblHeader')) is not None


def test_pathology_table_fits_inside_the_text_width(tmp_path):
    table = render(tmp_path).tables[5]
    assert sum(c.width for c in table.rows[0].cells) <= Cm(17.55)


def test_findings_have_orange_leadin_and_borderless_b8cce4_single_column_block(tmp_path):
    doc = render(tmp_path)
    lead = next(p for p in doc.paragraphs if p.text == "1. Finding")
    run = lead.runs[0]
    assert run.bold and run.font.size.pt == 10 and str(run.font.color.rgb) == "E97132"
    block = doc.tables[6]
    assert len(block.columns) == 1 and fills(block._tbl) == {"B8CCE4"}
    assert all(s.get(qn('w:val')) == 'nil' for s in block._tbl.tblPr.find(qn('w:tblBorders')))
    label = block.rows[0].cells[0].paragraphs[0].runs[0]
    assert label.text == "Plan/Feedback" and label.bold and label.font.size.pt == 10


def test_reference_range_header_column_is_wide_enough(tmp_path):
    table = render(tmp_path).tables[5]
    assert table.rows[0].cells[3].width >= Cm(3.5)


def test_signoff_states_missing_pharmacist_data(tmp_path):
    text = "\n".join(p.text for p in render(tmp_path).paragraphs)
    assert "Yours Sincerely," in text and "not supplied in the report data" in text


def test_footer_table_has_page_field(tmp_path):
    footer = render(tmp_path).sections[0].footer
    assert footer.tables and 'PAGE' in footer.tables[0]._tbl.xml


def grid(table):
    return tuple(int(c.get(qn('w:w'))) for c in table._tbl.tblGrid.findall(qn('w:gridCol')))


def test_column_grids_match_the_reference_twips(tmp_path):
    doc = render(tmp_path)
    t = doc.tables
    assert grid(t[0]) == (6487, 1985, 1701) and grid(t[1]) == (2965, 4299, 2909)
    assert grid(t[2]) == (2155, 1045, 3330, 3235)
    assert grid(t[3]) == (3690, 1313, 5167) and grid(t[4]) == (3690, 2970, 3420)
    assert grid(t[6]) == (10138,)


def test_sizes_title_headings_and_normal(tmp_path):
    doc = render(tmp_path)
    assert doc.styles["Normal"].font.size.pt == 12
    assert doc.styles["Heading 1"].font.size.pt == 16 and doc.styles["Heading 1"].font.bold
    title = doc.tables[0].cell(0, 0).paragraphs[0]
    assert title.style.name == "Heading 1" and title.runs[0].font.size.pt == 16
    for p in doc.paragraphs:
        if p.style.name == "Heading 2":
            assert p.runs[0].font.size.pt == 12 and p.runs[0].bold


def test_table_header_text_is_black_on_17365d_as_in_the_reference(tmp_path):
    # Reference truth: header text inherits black on navy. Reproduced as specified, readability is flagged separately.
    for table in render(tmp_path).tables[2:5]:
        for cell in table.rows[0].cells:
            run = cell.paragraphs[0].runs[0]
            assert run.bold and run.font.size.pt == 9 and str(run.font.color.rgb) == "000000"
