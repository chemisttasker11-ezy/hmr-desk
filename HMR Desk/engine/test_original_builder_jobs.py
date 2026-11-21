"""Synthetic: report_build with the original builder present. The builder, template and Word are stand-ins;
this proves routing, pinning, no-fallback, no-overwrite and evidence, not the real layout or Word."""
import hashlib
import json

import pytest

import db
import jobs
import original_builder_adapter as adapter
import report
import report_auth
import local_report_builder
from test_build_snapshot import _setup, _saved_report
from test_original_builder_adapter import fake_runner


def _ready(tmp_path, monkeypatch, files=None):
    connection = _setup(tmp_path, monkeypatch)
    folder = adapter.asset_dir(db.DATA_DIR)
    folder.mkdir(parents=True)
    files = files or {'build.py': b'# synthetic builder', 'Template - Copy.docx': b'synthetic template', 'word2pdf.ps1': b'# synthetic helper'}
    for name, content in files.items():
        (folder / name).write_bytes(content)
    monkeypatch.setattr(adapter, 'PINNED', {'build.py': hashlib.sha256(b'# synthetic builder').hexdigest(),
                                            'Template - Copy.docx': hashlib.sha256(b'synthetic template').hexdigest(),
                                            'word2pdf.ps1': hashlib.sha256(b'# synthetic helper').hexdigest()})
    monkeypatch.setattr(adapter, 'run_worker', fake_runner())
    monkeypatch.setattr(adapter, '_fonts', lambda pdf: {'Montserrat'})
    import settings
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        settings.update(conn, {'report_use_original_builder': True})
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.',
                      expected_revision=loaded['revision'])
        report.save(conn, patient, loaded)
        conn.commit()
    return connection, patient


def _last(connection, pid):
    with connection() as conn:
        return json.loads(conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()['detail'])


def test_original_path_routes_to_builder_keeps_word_pdf_and_records_unapproved_evidence(tmp_path, monkeypatch):
    connection, patient = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(local_report_builder, 'render', lambda *a, **k: pytest.fail('fallback renderer used'))
    import pdf_export
    monkeypatch.setattr(pdf_export, 'convert', lambda *a, **k: pytest.fail('LibreOffice converter used'))
    out = jobs.report_build(patient['id'], pdf=True)
    assert 'original report builder' in out and 'Word PDF created' in out
    detail = _last(connection, patient['id'])
    assert detail['renderer'] == 'original_builder'
    assert detail['template_approved'] is False and detail['template_version'] == 'original-template-copy'
    assert detail['template_sha256'] == adapter.PINNED['Template - Copy.docx']
    folder = jobs.patient_folder(patient)
    docx = folder / detail['file']
    assert docx.read_bytes() == b'docx' and docx.with_suffix('.pdf').read_bytes() == b'pdf'
    assert detail['pdf_sha256'] == hashlib.sha256(b'pdf').hexdigest()
    assert not [p for p in folder.iterdir() if p.name.startswith('.hmr')]


def test_second_build_does_not_overwrite_and_failures_leave_nothing(tmp_path, monkeypatch):
    connection, patient = _ready(tmp_path, monkeypatch)
    jobs.report_build(patient['id'], pdf=True)
    jobs.report_build(patient['id'], pdf=True)
    names = sorted(p.name for p in jobs.patient_folder(patient).glob('HMR*'))
    assert len(names) == 4 and any('-v2' in n for n in names)
    monkeypatch.setattr(adapter, 'run_worker', fake_runner(code=2))
    before = sorted(p.name for p in jobs.patient_folder(patient).iterdir())
    with pytest.raises(RuntimeError):
        jobs.report_build(patient['id'], pdf=True)
    assert sorted(p.name for p in jobs.patient_folder(patient).iterdir()) == before


def test_wrong_or_missing_assets_fail_closed_without_fallback(tmp_path, monkeypatch):
    connection, patient = _ready(tmp_path, monkeypatch, files={'build.py': b'# tampered', 'Template - Copy.docx': b'synthetic template', 'word2pdf.ps1': b'# synthetic helper'})
    monkeypatch.setattr(local_report_builder, 'render', lambda *a, **k: pytest.fail('fallback renderer used'))
    before = sorted(p.name for p in jobs.patient_folder(patient).iterdir())
    with pytest.raises(RuntimeError, match='do not match'):
        jobs.report_build(patient['id'])
    assert sorted(p.name for p in jobs.patient_folder(patient).iterdir()) == before
    (adapter.asset_dir(db.DATA_DIR) / 'build.py').write_bytes(b'# synthetic builder')
    (adapter.asset_dir(db.DATA_DIR) / 'Template - Copy.docx').unlink()
    with pytest.raises(FileNotFoundError):
        jobs.report_build(patient['id'])


def test_without_the_private_folder_the_existing_path_is_unchanged(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    assert adapter.assets_present(db.DATA_DIR) is False
    import settings
    with connection() as conn:
        assert settings.get(conn, 'report_use_original_builder') is False


def test_signoff_stays_blocked_for_original_builder_evidence_until_approval_rule_is_decided(tmp_path, monkeypatch):
    connection, patient = _ready(tmp_path, monkeypatch)
    jobs.report_build(patient['id'], pdf=True)
    detail = _last(connection, patient['id'])
    with connection() as conn:
        p = conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
        with pytest.raises(ValueError, match='owner-approved'):
            report_auth.check_approval(conn, p, {'action': 'signed_off', 'report_file': detail['file'], 'report_sha256': detail['sha256'],
                                                 'reviewer': 'Synthetic Pharmacist', 'clinical_reviewed': True})


def test_private_assets_alone_never_override_standalone_default(tmp_path, monkeypatch):
    # Put private-looking assets in place without enabling the optional mode.
    connection = _setup(tmp_path, monkeypatch)
    folder = adapter.asset_dir(db.DATA_DIR)
    folder.mkdir(parents=True)
    for name in adapter.PINNED:
        (folder / name).write_bytes(b'placeholder')
    import settings
    assert adapter.assets_present(db.DATA_DIR)
    with connection() as conn:
        assert settings.get(conn, 'report_use_original_builder') is False
        patient, saved = _saved_report(conn)
    monkeypatch.setattr(adapter, 'build_with_assets', lambda *a, **k: pytest.fail('Original builder started despite being off'))
    output = jobs.report_build(patient['id'], pdf=False)
    assert 'original report builder' not in output.lower()
    assert 'provisional' in output.lower() or 'approved-layout' in output.lower()


def test_original_builder_enabled_without_assets_fails_explicitly(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    import settings
    with connection() as conn:
        patient, saved = _saved_report(conn)
        settings.update(conn, {'report_use_original_builder': True})
        conn.commit()
    assert not adapter.assets_present(db.DATA_DIR)
    with pytest.raises(ValueError, match='private assets are unavailable'):
        jobs.report_build(patient['id'], pdf=False)
