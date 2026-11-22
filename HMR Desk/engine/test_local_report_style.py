"""Style conventions of the local provisional report (synthetic data only).

Targets come from the host's corroborated spec of the pharmacist's latest pair of reports (non-identifying).
Unconfirmed: heading wording, body size, colour of the conditions section, label text of the medicine tables.
These tests pin the spec'd structure. The renderer stays labelled provisional."""
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Twips

import pytest
import local_report_builder as builder


def data():
    return dict(name="Synthetic Patient", assess_date="2026-11-17", report_date="17/11/2026",
                patient="Synthetic Patient", doctor="Dr Example GP", dear="Dear Dr Example,",
                thanks="Thank you", reason="Reason", intro="Intro", conditions="Condition", allergies="Allergy",
                obs="Obs", meds=[["a", "b", "c", "d"]], otc=[["o", "p", "q"]], ceased=[["x", "y", "z"]],
                path=[["eGFR", "68", "mL/min/1.73m2", "> 60", "Synthetic source"]],
                issues=[{"title": "Finding", "rec": "Do this", "rationale": "Because"}], followup="Follow up", path_date="2026-11-17")


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


def grid(table):
    return tuple(int(c.get(qn('w:w'))) for c in table._tbl.tblGrid.findall(qn('w:gridCol')))


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
    assert doc.styles["Normal"].font.size.pt == 12
    assert doc.styles["Heading 1"].font.size.pt == 16 and doc.styles["Heading 1"].font.bold


def test_table_order_and_grids_follow_the_host_map(tmp_path):
    t = render(tmp_path).tables
    assert [grid(x) for x in t[:6]] == [(6487, 1985, 1701), (2965, 4299, 2909), (2660, 7478), (2520, 1800, 2700, 3145),
                                        (4140, 2070, 3870), (4140, 2070, 3870)]
    assert grid(t[6]) == (10138,) and grid(t[7]) == (1885, 1105, 1870, 1620, 3820)


def test_title_table_is_unfilled_with_title_spanning_two_rows(tmp_path):
    doc = render(tmp_path)
    table = doc.tables[0]
    assert not fills(table._tbl) and len(table.rows) == 2
    assert table.cell(0, 0).text == "Home Medication Review"
    assert table.cell(0, 0)._tc is table.cell(1, 0)._tc  # merged vertically
    assert [table.cell(0, 1).text, table.cell(0, 2).text] == ["Assessment date:", "17/11/2026"]
    assert [table.cell(1, 1).text, table.cell(1, 2).text] == ["Report date:", "17/11/2026"]
    title = table.cell(0, 0).paragraphs[0]
    assert title.style.name == "Heading 1" and title.runs[0].font.size.pt == 16


def test_all_tables_use_single_half_point_borders_except_plan_blocks(tmp_path):
    doc = render(tmp_path)
    for index, t in enumerate(doc.tables):
        vals = {(s.get(qn('w:val')), s.get(qn('w:sz'))) for s in t._tbl.tblPr.find(qn('w:tblBorders'))}
        assert vals == ({('nil', None)} if index in (6, 8) else {('single', '4')}), index


def test_tables_use_direct_formatting_like_the_reference(tmp_path):
    for table in render(tmp_path).tables:
        pr = table._tbl.tblPr
        assert pr.find(qn('w:tblStyle')) is None
        assert pr.find(qn('w:tblLayout')).get(qn('w:type')) == 'fixed'
        assert pr.find(qn('w:tblInd')).get(qn('w:w')) == '-5'
        assert pr.find(qn('w:tblLook')).get(qn('w:val')) == '04A0'
        assert int(pr.find(qn('w:tblW')).get(qn('w:w'))) == sum(grid(table))
        tags = [e.tag.split('}')[1] for e in pr]
        assert tags.index('tblW') < tags.index('tblInd') < tags.index('tblBorders') < tags.index('tblLayout') < tags.index('tblLook')


def test_details_table_headings(tmp_path):
    table = render(tmp_path).tables[1]
    assert [c.text for c in table.rows[0].cells] == ["Patient Details", "Doctor Details", "Accredited Pharmacist Details"]
    assert table.rows[1].cells[0].text == "Synthetic Patient" and table.rows[1].cells[1].text == "Dr Example GP"
    assert "Not supplied" in table.rows[1].cells[2].text


def test_profile_table_rows_are_labelled_and_unknown_stays_visible(tmp_path):
    table = render(tmp_path).tables[2]
    assert [r.cells[0].text for r in table.rows] == ["Current Conditions:", "Allergies", "Obs from interview"]
    assert [r.cells[1].text for r in table.rows] == ["Condition", "Allergy", "Obs"]
    d = data()
    d["allergies"] = ""
    target = tmp_path / "blank.docx"
    builder.render(d, target)
    assert Document(target).tables[2].rows[1].cells[1].text == "Not recorded in the report data"


def test_heading_order_and_colours(tmp_path):
    doc = render(tmp_path)
    colours = heading_colors(doc)
    names = list(colours)
    assert names == ["Patient Profile", "Current medication as per the patient",
                     "OTC medications / Additional medications (Identified During Interview)",
                     "Medication as per the referral ceased or not used", "Review Findings",
                     "Pathology results: 17/11/2026", "Follow-up"]
    assert colours["Patient Profile"] == colours["Review Findings"] == colours["Pathology results: 17/11/2026"] == "01A1DD"
    assert colours["Current medication as per the patient"] == colours[names[2]] == "00B050"
    assert colours[names[3]] == "C00000"
    for p in doc.paragraphs:
        if p.style.name == "Heading 2":
            assert p.runs[0].font.size.pt == 12 and p.runs[0].bold


def test_medicine_tables_labels_fill_and_auto_header_text(tmp_path):
    doc = render(tmp_path)
    meds, otc, ceased = doc.tables[3], doc.tables[4], doc.tables[5]
    assert [c.text for c in meds.rows[0].cells] == ["Drug Regimen", "Dose", "Comments", "Recommendation"]
    assert [c.text for c in otc.rows[0].cells] == [c.text for c in ceased.rows[0].cells] == ["Drug Regimen", "Directions", "Comments"]
    for t in (meds, otc, ceased):
        assert fills(t.rows[0]._tr) == {"17365D"}
        assert t.rows[0]._tr.trPr.find(qn('w:tblHeader')) is not None
        for cell in t.rows[0].cells:
            run = cell.paragraphs[0].runs[0]
            assert run.bold and run.font.size.pt == 9
            assert run._r.rPr.find(qn('w:color')) is None  # auto colour, as in the reference: white on the navy fill
    for t in (meds, otc, ceased):
        assert fills(t._tbl) == {"17365D"}


def test_results_table_has_no_fill_and_keeps_a_source_column(tmp_path):
    table = render(tmp_path).tables[7]
    assert not fills(table._tbl)
    assert [c.text for c in table.rows[0].cells] == ["Test", "Result", "Units", "Normal range", "Source / notes"]


def test_findings_have_orange_leadin_and_borderless_b8cce4_single_column_block(tmp_path):
    doc = render(tmp_path)
    lead = next(p for p in doc.paragraphs if p.text == "1. Finding")
    run = lead.runs[0]
    assert run.bold and run.font.size.pt == 10 and str(run.font.color.rgb) == "E97132"
    block = doc.tables[6]
    assert len(block.columns) == 1 and fills(block._tbl) == {"B8CCE4"} and len(block.rows) == 2
    label = block.rows[0].cells[0].paragraphs[0].runs[0]
    assert label.text == "Plan/Feedback: " and label.bold and label.font.size.pt == 10


def test_signoff_states_missing_pharmacist_data(tmp_path):
    text = "\n".join(p.text for p in render(tmp_path).paragraphs)
    assert "Yours Sincerely," in text and "not supplied in the report data" in text


def test_footer_table_has_page_field(tmp_path):
    footer = render(tmp_path).sections[0].footer
    assert footer.tables and 'PAGE' in footer.tables[0]._tbl.xml


def _keep(element):
    return element.find('.//' + qn('w:keepNext')) is not None


def test_closing_is_kept_with_the_content_above_it(tmp_path):
    doc = render(tmp_path)
    body = [el for el in doc.element.body if el.tag in (qn('w:p'), qn('w:tbl'))]
    texts = [''.join(el.itertext()) for el in body]
    at = next(i for i, t in enumerate(texts) if t.startswith('Yours Sincerely'))
    assert _keep(body[at])                                    # closing travels with the pharmacist line
    assert body[at + 1].find('.//' + qn('w:keepLines')) is not None
    spacer, plan = body[at - 1], body[at - 2]
    assert not texts[at - 1].strip() and _keep(spacer)       # empty spacer after the follow-up block
    assert plan.tag == qn('w:tbl') and all(_keep(p) for p in plan.findall(qn('w:tr'))[-1].iter(qn('w:p')))
    assert [t for t in texts if t.strip()][-2:] == [texts[at], texts[at + 1]]   # text and order unchanged


def test_signoff_is_not_orphaned_on_a_last_page_of_its_own(tmp_path):
    import shutil, subprocess
    fitz = pytest.importorskip('fitz')
    if not shutil.which('soffice'): pytest.skip('LibreOffice not available')
    d = data()
    d.update(pharmacist_details='Simulation Pharmacist\nSynthetic credentials', meds=[["Med %d 10 mg tablet" % i, "1 daily", "c", "r"] for i in range(4)],
             issues=[{"title": "Finding %d" % i, "rec": "Do this " * 6, "rationale": "Because " * 8} for i in range(9)])
    target = tmp_path / 'long.docx'
    builder.render(d, target)
    subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', str(tmp_path), str(target)], capture_output=True, timeout=90)
    with fitz.open(tmp_path / 'long.pdf') as pdf: last = pdf[-1].get_text()
    assert 'Yours Sincerely' in last and 'Follow-up' in last   # the closing shares its page with the follow-up content
