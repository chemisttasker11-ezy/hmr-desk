"""Generated tables follow the owner's template table formatting (synthetic, no PHI)."""
from docx import Document

import template_report_builder as renderer
from test_template_report_builder import make_template, sample


def _style_id(table):
    pr = table._tbl.tblPr
    node = pr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tblStyle')
    return None if node is None else node.get(
        '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')


def test_generated_tables_copy_the_template_table_format(tmp_path):
    template = tmp_path / 'owner.docx'
    make_template(template)
    doc = Document(template)
    owner_table = doc.add_table(rows=2, cols=2)
    owner_table.style = 'Light List Accent 1'
    doc.save(template)
    output = tmp_path / 'report.docx'
    renderer.render(sample(), output, template)
    result = Document(output)
    assert _style_id(result.tables[0]) == _style_id(Document(template).tables[0])
    generated = [t for t in result.tables if t.rows[0].cells[0].text in ('Medicine', 'Medicine name', 'Name') or len(t.rows) >= 2]
    assert generated and all(_style_id(t) == 'LightList-Accent1' for t in generated)


def test_template_without_table_falls_back_to_grid(tmp_path):
    template = tmp_path / 'bare.docx'
    make_template(template)
    output = tmp_path / 'report.docx'
    renderer.render(sample(), output, template)
    result = Document(output)
    assert len(result.tables) == 4
    assert all(_style_id(t) == 'TableGrid' for t in result.tables)
