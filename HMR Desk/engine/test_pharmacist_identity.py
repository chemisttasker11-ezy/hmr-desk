"""Reviewing-pharmacist identity in exported reports (synthetic data only)."""
import json

from docx import Document

import db
import local_report_builder
import pharmacist_identity
import report_status
import settings
import template_report_builder as renderer
from test_local_report_style import data as local_data
from test_report_auth import case
from test_template_report_builder import make_template, sample


def conn_for(tmp_path):
    return db.connect(str(tmp_path / 'hmr.db'))


def text(doc):
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        parts += [c.text for row in table.rows for c in row.cells]
    return '\n'.join(parts)


def test_blank_name_keeps_not_supplied_text(tmp_path):
    conn = conn_for(tmp_path)
    ident = pharmacist_identity.resolve(conn)
    assert ident['lines'] == [] and 'not set' in ident['note']
    target = tmp_path / 'r.docx'
    local_report_builder.render(local_data(), target)
    out = text(Document(target))
    assert 'Not supplied in the report data' in out and 'not supplied in the report data (provisional)' in out


def test_default_credential_is_not_printed_until_confirmed(tmp_path):
    conn = conn_for(tmp_path)
    with conn:
        settings.update(conn, {'pharmacist_name': 'SIMULATED Pharmacist', 'pharmacist_phone': '0000 000 000'})
    ident = pharmacist_identity.resolve(conn)
    assert ident['lines'] == ['SIMULATED Pharmacist', 'Phone: 0000 000 000']
    assert 'not confirmed' in ident['note'] and 'Credentialed' not in ident['text']
    with conn:
        settings.update(conn, {'pharmacist_credential_confirmed': True})
    ident = pharmacist_identity.resolve(conn)
    assert ident['lines'][1] == 'Credentialed Consultant Pharmacist' and ident['note'] == ''
    with conn:
        settings.update(conn, {'pharmacist_credential': 'Custom credential', 'pharmacist_credential_confirmed': False})
    assert 'Custom credential' not in pharmacist_identity.resolve(conn)['text']


def test_local_builder_prints_only_supplied_fields_and_no_email(tmp_path):
    d = local_data(); d['pharmacist_details'] = 'SIMULATED Pharmacist\nPhone: 0000 000 000'
    target = tmp_path / 'r.docx'
    local_report_builder.render(d, target)
    out = text(Document(target))
    assert 'SIMULATED Pharmacist' in out and 'Phone: 0000 000 000' in out
    assert 'not supplied in the report data (provisional)' not in out and 'email' not in out.lower()


def test_template_with_and_without_optional_placeholder(tmp_path):
    plain = tmp_path / 'plain.docx'; make_template(plain)
    withp = tmp_path / 'withp.docx'; make_template(withp)
    doc = Document(withp); doc.add_paragraph('Reviewed by {{HMR_PHARMACIST}}'); doc.save(withp)
    assert renderer.validate_layout(plain) and renderer.validate_layout(withp)
    assert not renderer.has_marker(plain, 'PHARMACIST') and renderer.has_marker(withp, 'PHARMACIST')
    d = sample(); d['pharmacist_details'] = 'SIMULATED Pharmacist'
    renderer.render(d, tmp_path / 'a.docx', plain)
    renderer.render(d, tmp_path / 'b.docx', withp)
    assert 'SIMULATED Pharmacist' not in text(Document(tmp_path / 'a.docx'))
    assert 'Reviewed by SIMULATED Pharmacist' in text(Document(tmp_path / 'b.docx'))
    d.pop('pharmacist_details')
    renderer.render(d, tmp_path / 'c.docx', withp)  # older callers: placeholder fills empty
    assert '{{HMR_' not in text(Document(tmp_path / 'c.docx'))


def test_pharmacist_change_after_build_marks_report_outdated_only_when_evidence_has_it(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert report_status.report_status(conn, patient)['status'] == 'current'  # old build evidence: no identity key
    with conn:
        settings.update(conn, {'pharmacist_name': 'SIMULATED Pharmacist'})
        row = conn.execute("SELECT id, detail FROM events WHERE type='report_build'").fetchone()
        detail = json.loads(row['detail'])
        detail['pharmacist_identity_sha256'] = pharmacist_identity.digest(pharmacist_identity.resolve(conn))
        conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(detail), row['id']))
    assert report_status.report_status(conn, patient)['status'] == 'current'
    with conn:
        settings.update(conn, {'pharmacist_name': 'SIMULATED Other'})
    s = report_status.report_status(conn, patient)
    assert s['status'] == 'outdated' and 'pharmacist_identity_changed' in s['reasons']
    conn.close()
