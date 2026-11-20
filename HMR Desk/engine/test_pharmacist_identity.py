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


# ---- end to end through jobs.report_build (synthetic) ----
import hashlib

import jobs
import report
import template_report_builder
from test_report_save_revision import _setup, _saved_report


def _install_template(tmp_path, monkeypatch, with_placeholder):
    root = tmp_path / 'tpl'; root.mkdir()
    path = root / 'approved-hmr.docx'
    make_template(path)
    if with_placeholder:
        doc = Document(path); doc.add_paragraph('Reviewed by {{HMR_PHARMACIST}}'); doc.save(path)
    (root / 'approved-hmr.json').write_text(json.dumps({
        'version': 'synthetic-test', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'approved_by': 'Synthetic QA', 'approved_on': '2026-11-16'}))
    monkeypatch.setattr(template_report_builder, 'active_template_root', lambda: root)


def _build(tmp_path, monkeypatch, with_template=None, **identity):
    connection = _setup(tmp_path, monkeypatch)
    if with_template is not None:
        _install_template(tmp_path, monkeypatch, with_template)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.', expected_revision=loaded['revision'])
        report.save(conn, patient, loaded)
        if identity:
            settings.update(conn, identity)
        conn.commit()
    output = jobs.report_build(patient['id'])
    with connection() as conn:
        folder = jobs.patient_folder(patient)
        doc = Document(sorted(folder.glob('*.docx'))[0])
        detail = json.loads(conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
                                         (patient['id'],)).fetchone()['detail'])
    return connection, patient, output, text(doc), detail


def test_build_without_template_prints_identity_and_records_hash(tmp_path, monkeypatch):
    c, p, output, out, detail = _build(tmp_path, monkeypatch, pharmacist_name='SIMULATED Pharmacist', pharmacist_phone='0000 000 000')
    assert 'SIMULATED Pharmacist' in out and 'not confirmed' in output and detail['pharmacist_identity_sha256']
    assert 'Credentialed Consultant Pharmacist' not in out


def test_approved_template_without_placeholder_discloses_and_omits(tmp_path, monkeypatch):
    c, p, output, out, detail = _build(tmp_path, monkeypatch, with_template=False, pharmacist_name='SIMULATED Pharmacist')
    assert 'Built approved-layout Word draft' in output
    assert 'Pharmacist details were not placed: the approved layout has no pharmacist placeholder' in output
    assert 'SIMULATED Pharmacist' not in out


def test_approved_template_with_placeholder_places_confirmed_credential(tmp_path, monkeypatch):
    c, p, output, out, detail = _build(tmp_path, monkeypatch, with_template=True, pharmacist_name='SIMULATED Pharmacist',
                                       pharmacist_credential_confirmed=True)
    assert 'Reviewed by SIMULATED Pharmacist' in out and 'Credentialed Consultant Pharmacist' in out
    assert 'not placed' not in output and 'not confirmed' not in output


def test_every_printed_identity_change_makes_the_build_outdated(tmp_path, monkeypatch):
    c, p, output, out, detail = _build(tmp_path, monkeypatch, pharmacist_name='SIMULATED Pharmacist', pharmacist_phone='0000 000 000',
                                       pharmacist_credential_confirmed=True)
    with c() as conn:
        base = report_status.report_status(conn, p)['reasons']
        assert 'pharmacist_identity_changed' not in base, base
    changes = [{'pharmacist_name': 'SIMULATED Other'}, {'pharmacist_name': ''}, {'pharmacist_phone': '1111'}, {'pharmacist_phone': ''},
               {'pharmacist_credential': 'Other credential'}, {'pharmacist_credential_confirmed': False}]
    for change in changes:
        with c() as conn:
            before = {k: settings.get(conn, k) for k in change}
            settings.update(conn, change); conn.commit()
            s = report_status.report_status(conn, p)
            assert 'pharmacist_identity_changed' in s['reasons'], (change, s)
            settings.update(conn, before); conn.commit()
            assert 'pharmacist_identity_changed' not in report_status.report_status(conn, p)['reasons'], change
