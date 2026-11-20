"""Synthetic approval contract and exact-template round-trip tests; no PHI."""
import hashlib
import json

import pytest
from docx import Document

import template_report_builder as renderer


def sample():
    return dict(
        assess_date='12/11/2026', report_date='16/11/2026',
        patient='Synthetic Person\\nDOB: UNKNOWN',
        doctor='Dr Example', dear='Dear Dr Example,',
        thanks='Thank you for the referral.',
        reason='Medicine reconciliation',
        intro='Synthetic patient interview.',
        conditions='Not recorded', allergies='Unknown, verify source',
        obs='Not measured', followup='Review in four weeks',
        meds=[['Medicine A', 'One tablet daily', 'Taking differently', 'Review']],
        otc=[['Supplement Z', 'PRN', 'Reported use']],
        ceased=[['Medicine B', 'One daily', 'Patient ceased']],
        path=[['Creatinine', '98', 'umol/L', '60-110', 'synthetic.pdf p.2']],
        issues=[{'title': 'Review medicine use',
                 'rec': 'GP could review adherence.',
                 'rationale': 'Patient described a different regimen.'}],
    )


def make_template(path):
    doc = Document()
    section = doc.sections[0]
    section.header.paragraphs[0].text = 'SYNTHETIC LETTERHEAD'
    section.footer.paragraphs[0].text = 'SYNTHETIC FOOTER'
    doc.add_heading('HMR approved-layout simulation', level=1)
    for marker in renderer.TEXT_FIELDS:
        doc.add_paragraph('{{HMR_' + marker + '}}')
    for marker in renderer.TABLE_FIELDS:
        doc.add_paragraph('{{HMR_' + marker + '}}')
    doc.add_paragraph(renderer.ISSUES_ANCHOR)
    doc.save(path)


def test_template_layout_and_tables_are_retained(tmp_path):
    template = tmp_path / 'example.docx'
    make_template(template)
    output = tmp_path / 'report.docx'
    renderer.render(sample(), output, template)
    doc = Document(output)
    body = '\n'.join(p.text for p in doc.paragraphs)
    assert 'HMR approved-layout simulation' in body
    assert 'Medicine reconciliation' in body
    assert 'Review medicine use' in body
    assert '{{HMR_' not in body
    assert doc.sections[0].header.paragraphs[0].text == 'SYNTHETIC LETTERHEAD'
    assert doc.sections[0].footer.paragraphs[0].text == 'SYNTHETIC FOOTER'
    assert len(doc.tables) == 4
    assert doc.tables[0].rows[1].cells[0].text == 'Medicine A'
    with pytest.raises(FileExistsError):
        renderer.render(sample(), output, template)


def test_owner_manifest_rejects_missing_and_tampered_template(tmp_path):
    with pytest.raises(FileNotFoundError):
        renderer.approved_template(tmp_path)
    template = tmp_path / 'approved-hmr.docx'
    make_template(template)
    meta = {'version': 'synthetic-1',
            'sha256': hashlib.sha256(template.read_bytes()).hexdigest(),
            'approved_by': 'Synthetic QA only', 'approved_on': '2026-11-16'}
    (tmp_path / 'approved-hmr.json').write_text(json.dumps(meta))
    assert renderer.approved_template(tmp_path)[1] == meta
    template.write_bytes(template.read_bytes() + b'changes')
    with pytest.raises(ValueError, match='checksum'):
        renderer.approved_template(tmp_path)


def test_missing_anchor_rejected_without_output(tmp_path):
    template = tmp_path / 'incomplete.docx'
    Document().save(template)
    target = tmp_path / 'output.docx'
    with pytest.raises(ValueError, match='exactly one'):
        renderer.render(sample(), target, template)
    assert not target.exists()


def test_owner_template_registration_preserves_old_layout_and_rejects_unapproved(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    source = tmp_path / 'source approved.docx'
    make_template(source)
    with pytest.raises(ValueError, match='Explicit owner authorisation'):
        renderer.register(source, 'synthetic-1', 'Owner Test', False)
    result = renderer.register(source, 'synthetic-1', 'Owner Test', True)
    assert result['registered']
    assert renderer.active_template_root() == tmp_path / 'userdata' / 'templates'
    current, manifest = renderer.approved_template(renderer.active_template_root())
    assert current.is_file() and manifest['version'] == 'synthetic-1'
    # New approved revision must retain prior editable template and approval.
    doc = Document(source)
    doc.add_paragraph('SYNTHETIC NEW VERSION, NOT CLINICAL APPROVAL')
    doc.save(source)
    next_version = renderer.register(source, 'synthetic-2', 'Owner Test', True)
    assert next_version['previous_version_preserved']
    history = list((renderer.active_template_root() / 'history').glob('*.docx'))
    assert len(history) == 1
    assert renderer.approved_template(renderer.active_template_root())[1]['version'] == 'synthetic-2'


def test_unmapped_docx_cannot_be_registered_as_owner_layout(tmp_path,monkeypatch):
    import db
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path / 'userdata'))
    template = tmp_path / 'unmapped.docx'
    doc=Document()
    doc.add_paragraph('A sample old patient report without explicit placeholders')
    doc.save(template)
    with pytest.raises(ValueError,match='placeholders'):
        renderer.register(template,'synthetic-unmapped','Synthetic Owner',True)
    assert not (tmp_path / 'userdata' / 'templates' / 'approved-hmr.docx').exists()


def test_tables_repeat_header_and_keep_rows_whole(tmp_path):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location('smoke_tpl', pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'smoke-template-pdf.py')
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    template = smoke.make_template(tmp_path)
    out = tmp_path / 'long.docx'
    renderer.render(smoke.data(True), out, template)
    from docx import Document
    from docx.oxml.ns import qn
    tables = Document(out).tables
    assert tables
    for table in tables:
        for index, row in enumerate(table.rows):
            props = row._tr.trPr
            assert props is not None and props.find(qn('w:cantSplit')) is not None
            assert (props.find(qn('w:tblHeader')) is not None) == (index == 0)
    renderer.render(smoke.data(True), tmp_path / 'again.docx', template)  # idempotent re-render


def test_long_medicine_table_pagination_with_real_converter(tmp_path, monkeypatch):
    import importlib.util, pathlib, pdf_export
    if not pdf_export.available():
        pytest.skip('No PDF converter: pagination NOT tested here')
    spec = importlib.util.spec_from_file_location('smoke_tpl2', pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'smoke-template-pdf.py')
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    template = smoke.make_template(tmp_path)
    renderer.render(smoke.data(True), tmp_path / 'long.docx', template)
    pdf_export.convert(tmp_path / 'long.docx', tmp_path / 'long.pdf')
    import fitz
    with fitz.open(tmp_path / 'long.pdf') as doc:
        pages = [p.get_text() for p in doc]
    table_pages = [t for t in pages if 'Synthetic medicine' in t]
    assert len(table_pages) >= 2
    for text in table_pages:
        assert text.count('Actual use') >= 1  # header row on every page that has medicine rows
    # no row is cut: a medicine's label number and its 'Recorded use N' cell sit on the same page
    import re
    flat = [' '.join(p.split()) for p in pages]
    for i in range(35):
        label = [k for k, t in enumerate(flat) if re.search(r'Synthetic medicine %d(?!\d)' % i, t)]
        use = [k for k, t in enumerate(flat) if re.search(r'Recorded use %d(?!\d)' % i, t)]
        assert len(label) == 1 and label == use, (i, label, use)
