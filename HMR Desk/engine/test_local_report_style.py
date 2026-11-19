"""Style conventions of the local provisional report (synthetic data only).

The conventions come from the pharmacist's recent completed reports as compared on the host. The exact navy and
blue values are not confirmed, and this renderer stays labelled provisional. These tests pin structure, not taste."""
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, RGBColor, Twips

import local_report_builder as builder


def data():
    return dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026",
                patient="Synthetic Patient\nSynthetic Street", doctor="Dr Example GP", dear="Dear Dr Example,",
                thanks="Thank you", reason="Reason", intro="Intro", conditions="Condition", allergies="Allergy",
                obs="Obs", meds=[["a", "b", "c", "d"]], otc=[], ceased=[],
                path=[["eGFR", "68", "mL/min/1.73m2", "> 60", "Synthetic source"]],
                issues=[{"title": "Finding", "rec": "Do this", "rationale": "Because"}], followup="Follow up")


def render(tmp_path):
    target = tmp_path / "r.docx"
    builder.render(data(), target)
    return Document(target)


def shading(element):
    return {s.get(qn('w:fill')) for s in element.iter(qn('w:shd'))}


def test_provisional_marker_survives(tmp_path):
    doc = render(tmp_path)
    assert builder.PROVISIONAL_LABEL in "\n".join(p.text for p in doc.paragraphs)
    assert builder.PROVISIONAL_LABEL in doc.sections[0].header.paragraphs[0].text


def test_page_is_a4_with_reference_margins(tmp_path):
    section = render(tmp_path).sections[0]
    assert abs(section.page_width - Cm(21.0)) < 1000 and abs(section.page_height - Cm(29.7)) < 1000
    assert (section.top_margin, section.bottom_margin) == (Twips(1400), Twips(1440))
    assert (section.left_margin, section.right_margin) == (Twips(1800), Twips(1800))


def test_fonts_are_explicit_aptos_with_no_theme_override(tmp_path):
    doc = render(tmp_path)
    for name in ("Normal", "Heading 2", "Heading 3", "Header"):
        fonts = doc.styles[name].element.rPr.find(qn('w:rFonts'))
        assert fonts.get(qn('w:ascii')) == "Aptos" and fonts.get(qn('w:hAnsi')) == "Aptos"
        assert not [a for a in fonts.attrib if a.endswith('Theme') or a.endswith('theme')]
    assert doc.styles["Normal"].font.size.pt == 10.5


def test_title_is_black_text_on_white_with_a_small_bordered_date_box(tmp_path):
    doc = render(tmp_path)
    paragraphs = doc.paragraphs
    assert paragraphs[0].text == "Home Medicines Review" and not shading(paragraphs[0]._p)
    assert paragraphs[0].runs[0].font.color.rgb == RGBColor(0, 0, 0)
    assert paragraphs[1].text == "Assessment: 17/11/2026    Report: 17/11/2026" and not shading(paragraphs[1]._p)
    assert paragraphs[1]._p.pPr.find(qn('w:pBdr')) is not None
    assert paragraphs[1].paragraph_format.right_indent > 0


def test_data_tables_have_navy_repeating_header_rows(tmp_path):
    doc = render(tmp_path)
    assert len(doc.tables) == 2
    for table in doc.tables:
        header = table.rows[0]
        assert shading(header._tr) == {builder.NAVY}
        assert header._tr.trPr.find(qn('w:tblHeader')) is not None
        assert all(run.font.bold for cell in header.cells for p in cell.paragraphs for run in p.runs)


def test_pathology_table_fits_inside_the_text_width(tmp_path):
    table = render(tmp_path).tables[1]
    assert sum(c.width for c in table.rows[0].cells) <= Cm(14.65)


def test_profile_blocks_are_boxed_and_plan_blocks_are_blue(tmp_path):
    doc = render(tmp_path)
    by_text = {p.text: p for p in doc.paragraphs}
    for text in ("Synthetic Patient\nSynthetic Street", "Dr Example GP"):
        assert by_text[text]._p.pPr.find(qn('w:pBdr')) is not None
    for text in ("Recommendation: Do this", "Rationale: Because", "Follow up"):
        assert shading(by_text[text]._p) == {builder.BLUE_FILL}
