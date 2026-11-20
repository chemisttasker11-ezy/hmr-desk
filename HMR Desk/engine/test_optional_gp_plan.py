"""Synthetic regression coverage for the optional GP Plan report column."""
import sqlite3
import pytest
from docx import Document

import settings
import local_report_builder
import template_report_builder as owner_renderer
from test_template_report_builder import make_template, sample


def test_setting_defaults_off_persists_and_validates_bool():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
    assert settings.get(conn, 'report_include_gp_plan') is False
    entry = next(x for x in settings.listing(conn) if x['key'] == 'report_include_gp_plan')
    assert entry['type'] == 'bool' and entry['default'] is False
    with pytest.raises(ValueError, match='report_include_gp_plan'):
        settings.update(conn, {'report_include_gp_plan': 'true'})
    settings.update(conn, {'report_include_gp_plan': True})
    assert settings.get(conn, 'report_include_gp_plan') is True
    settings.update(conn, {'report_include_gp_plan': False})
    assert settings.get(conn, 'report_include_gp_plan') is False


@pytest.mark.parametrize('enabled', (False, True))
def test_owner_template_without_prototype_is_four_or_five_columns(tmp_path, enabled):
    template = tmp_path / 'owner.docx'
    make_template(template)
    data = sample()
    before = [row[:] for row in data['meds']]
    report = tmp_path / 'output.docx'
    owner_renderer.render(data, report, template, include_gp_plan=enabled)
    med = Document(report).tables[0]
    assert len(med.columns) == (5 if enabled else 4)
    assert med.rows[1].cells[0].text == 'Medicine A'
    if enabled:
        assert med.rows[0].cells[-1].text == 'GP Plan'
        assert med.rows[1].cells[-1].text == ''
    else:
        assert 'GP Plan' not in [c.text for c in med.rows[0].cells]
    assert data['meds'] == before  # No mutation of the four-column saved clinical spec.


@pytest.mark.parametrize('enabled', (False, True))
def test_provisional_report_is_four_or_five_columns(tmp_path, enabled):
    output = tmp_path / 'provisional.docx'
    data = sample()
    local_report_builder.render(data, output, include_gp_plan=enabled)
    meds = next(t for t in Document(output).tables if t.rows[0].cells[0].text == 'Drug Regimen')
    assert len(meds.columns) == (5 if enabled else 4)
    if enabled:
        assert meds.rows[0].cells[-1].text == 'GP Plan'
        assert meds.rows[1].cells[-1].text == ''


def _prototype_template(path, columns):
    make_template(path)
    doc = Document(path)
    marker = next(p for p in doc.paragraphs if p.text == '{{HMR_MEDS_TABLE}}')
    template_row = doc.add_table(rows=2, cols=columns)
    for i, label in enumerate(('Medicine', 'Actual use', 'Notes', 'Review') + (('GP Plan',) if columns == 5 else ())):
        template_row.cell(0, i).text = label
    template_row.cell(1, 0).text = 'PROTOTYPE ROW'
    marker._p.addnext(template_row._tbl)
    doc.save(path)


@pytest.mark.parametrize(('original', 'enabled', 'expected'), (
    (4, True, 5),
    (4, False, 4),
    (5, True, 5),
    (5, False, 4),
))
def test_owner_prototype_supports_both_settings_without_changing_source(tmp_path, original, enabled, expected):
    template = tmp_path / 'template.docx'
    _prototype_template(template, original)
    untouched = template.read_bytes()
    report = tmp_path / 'rendered.docx'
    owner_renderer.render(sample(), report, template, include_gp_plan=enabled)
    med = Document(report).tables[0]
    assert len(med.columns) == expected
    assert med.rows[1].cells[0].text == 'Medicine A'
    assert med.rows[1].cells[-1].text == ('' if enabled else 'Review')
    if enabled:
        assert med.rows[0].cells[-1].text == 'GP Plan'
    assert template.read_bytes() == untouched


def test_unknown_fifth_owner_column_never_silently_removed(tmp_path):
    template = tmp_path / 'template.docx'
    _prototype_template(template, 5)
    doc = Document(template)
    doc.tables[0].rows[0].cells[-1].text = 'Critical other data'
    doc.save(template)
    with pytest.raises(ValueError, match='GP Plan'):
        owner_renderer.render(sample(), tmp_path / 'out.docx', template, include_gp_plan=False)
    assert not (tmp_path / 'out.docx').exists()
