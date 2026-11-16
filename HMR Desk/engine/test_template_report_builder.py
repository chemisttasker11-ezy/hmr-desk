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
