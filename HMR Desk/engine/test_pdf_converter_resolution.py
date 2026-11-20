import sys
from pathlib import Path

import pytest

import app_paths
import pdf_export


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.delenv('HMR_PDF_CONVERTER', raising=False)
    monkeypatch.setattr(app_paths, 'resource_root', lambda: tmp_path)
    monkeypatch.setattr(pdf_export.shutil, 'which', lambda name: None)
    return tmp_path


def _bundled(root):
    exe = root / 'vendor' / 'libreoffice' / 'program' / 'soffice.exe'
    exe.parent.mkdir(parents=True); exe.write_bytes(b'x')
    return str(exe)


def test_source_run_uses_the_bundled_portable_converter_without_any_env(checkout):
    assert not pdf_export.available()
    exe = _bundled(checkout)
    assert pdf_export.available() and pdf_export.resolve_converter() == exe


def test_configured_path_wins_over_the_bundled_copy_and_a_bad_one_is_not_replaced(checkout, tmp_path, monkeypatch):
    _bundled(checkout)
    chosen = tmp_path / 'chosen.exe'; chosen.write_bytes(b'x')
    monkeypatch.setenv('HMR_PDF_CONVERTER', str(chosen))
    assert pdf_export.resolve_converter() == str(chosen)
    monkeypatch.setenv('HMR_PDF_CONVERTER', str(tmp_path / 'missing.exe'))
    assert pdf_export.resolve_converter() is None and not pdf_export.available()


def test_bundled_copy_is_preferred_to_a_path_install(checkout, monkeypatch):
    exe = _bundled(checkout)
    monkeypatch.setattr(pdf_export.shutil, 'which', lambda name: '/usr/bin/soffice')
    assert pdf_export.resolve_converter() == exe


def test_packaged_run_never_looks_at_the_checkout_or_the_path(checkout, monkeypatch):
    _bundled(checkout)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(pdf_export.shutil, 'which', lambda name: '/usr/bin/soffice')
    assert pdf_export.resolve_converter() is None and not pdf_export.available()
    docx = checkout / 'a.docx'; docx.write_bytes(b'x')
    with pytest.raises(RuntimeError, match='reinstall complete application'):
        pdf_export.convert(docx, checkout / 'a.pdf')


def test_missing_converter_error_in_a_source_run_says_how_to_provide_it(checkout):
    docx = checkout / 'a.docx'; docx.write_bytes(b'x')
    with pytest.raises(RuntimeError, match='bundle-libreoffice.ps1 or set HMR_PDF_CONVERTER'):
        pdf_export.convert(docx, checkout / 'a.pdf')
