"""Prototype-cloning renderer tests on a fully synthetic template; no PHI."""
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import template_report_builder as renderer
from test_template_report_builder import sample

FILL = '17365D'


def _shade(cell, fill):
    pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    pr.append(shd)


def _proto_table(doc, headers):
    table = doc.add_table(rows=2, cols=len(headers))
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
        _shade(table.rows[0].cells[i], FILL)
        table.rows[1].cells[i].text = 'sample'
    return table


def make_prototype_template(path, with_optional=True):
    doc = Document()
    doc.add_paragraph('Header {{HMR_PATIENT_NAME}}' if with_optional else 'Header')
    for name in renderer.TEXT_FIELDS:
        doc.add_paragraph('{{HMR_' + name + '}}')
    for name, (_, labels) in renderer.TABLE_FIELDS.items():
        doc.add_paragraph('{{HMR_' + name + '}}')
        _proto_table(doc, labels)
    if with_optional:
        doc.add_paragraph('Pathology results: {{HMR_PATH_DATE}}')
    doc.add_paragraph(renderer.ISSUES_ANCHOR)
    doc.add_paragraph('{{HMR_ISSUE_TITLE}}')
    doc.add_paragraph('Recommendation: {{HMR_ISSUE_REC}}')
    doc.add_paragraph('{{HMR_ISSUE_RATIONALE}}')
    box = doc.add_table(rows=1, cols=1)
    box.rows[0].cells[0].text = 'Plan / Feedback'
    _shade(box.rows[0].cells[0], 'B8CCE4')
    doc.add_paragraph(renderer.ISSUES_END)
    doc.save(path)


def _fills(table):
    return [c._tc.xpath('./w:tcPr/w:shd/@w:fill') for c in table.rows[0].cells]


def test_prototype_tables_keep_header_shading_and_rows(tmp_path):
    template = tmp_path / 't.docx'
    make_prototype_template(template)
    data = sample()
    data['meds'] = [['M%d' % i, 'a', 'b', 'c'] for i in range(7)]
    data['path'] = [['T%d' % i, '1', 'u', 'r', 's'] for i in range(11)]
    out = tmp_path / 'r.docx'
    renderer.render(data, out, template)
    doc = Document(out)
    meds = next(t for t in doc.tables if t.rows[0].cells[0].text == 'Medicine' and len(t.columns) == 4)
    assert len(meds.rows) == 8 and meds.rows[7].cells[0].text == 'M6'
    assert all(f == [FILL] for f in _fills(meds))
    path = next(t for t in doc.tables if len(t.columns) == 5)
    assert len(path.rows) == 12 and _fills(path)[0] == [FILL]


def test_issue_block_cloned_with_one_box_per_finding(tmp_path):
    template = tmp_path / 't.docx'
    make_prototype_template(template)
    data = sample()
    data['issues'] = [{'title': 'T%d' % i, 'rec': 'R%d' % i, 'rationale': 'X%d' % i} for i in range(4)]
    out = tmp_path / 'r.docx'
    renderer.render(data, out, template)
    doc = Document(out)
    boxes = [t for t in doc.tables if t.rows[0].cells[0].text == 'Plan / Feedback']
    assert len(boxes) == 4
    assert all(b.rows[0].cells[0]._tc.xpath('./w:tcPr/w:shd/@w:fill') == ['B8CCE4'] for b in boxes)
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '1. T0' in text and '4. T3' in text and 'Recommendation: R2' in text
    assert '{{HMR_' not in text


def test_empty_rows_remove_prototype_table_and_optional_markers_fill(tmp_path):
    template = tmp_path / 't.docx'
    make_prototype_template(template)
    data = sample()
    data['otc'] = []
    data['path_date'] = '01/11/2026'
    out = tmp_path / 'r.docx'
    renderer.render(data, out, template)
    doc = Document(out)
    assert not any(len(t.columns) == 3 and t.rows[0].cells[0].text == 'Medicine'
                   and t.rows[0].cells[1].text == 'Use' for t in doc.tables)
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert 'Header Synthetic Person' in text
    assert 'Pathology results: 01/11/2026' in text


def test_line_prototype_gives_each_line_its_own_formatted_paragraph(tmp_path):
    template = tmp_path / 't.docx'
    make_prototype_template(template)
    doc = Document(template)
    table = doc.add_table(rows=1, cols=1)
    cell = table.rows[0].cells[0]
    cell.paragraphs[0].add_run('{{HMR_PATIENT}}').bold = True
    cell.add_paragraph('{{HMR_LINE}}')
    # the standard template needs the PATIENT marker once: move it into the table cell
    for p in list(doc.paragraphs):
        if p.text == '{{HMR_PATIENT}}':
            p._p.getparent().remove(p._p)
    doc.save(template)
    out = tmp_path / 'r.docx'
    data = sample()
    data['patient'] = 'Synthetic Person\nDOB: UNKNOWN'
    renderer.render(data, out, template)
    result = Document(out)
    target = next(t for t in result.tables if 'Synthetic Person' in t.rows[0].cells[0].text)
    paragraphs = target.rows[0].cells[0].paragraphs
    assert [p.text for p in paragraphs] == ['Synthetic Person', 'DOB: UNKNOWN']
    assert paragraphs[0].runs[0].bold and not paragraphs[1].runs[0].bold
    assert '{{HMR_' not in '\n'.join(p.text for p in result.paragraphs)
