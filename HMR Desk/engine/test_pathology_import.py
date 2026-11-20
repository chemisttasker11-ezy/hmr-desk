"""Synthetic pathology source import, hash and page-level provenance."""
import hashlib
import json
from pathlib import Path

import fitz
import pytest

import pathology_import


def make_source(path):
    with fitz.open() as doc:
        one = doc.new_page()
        one.insert_text((40,60),'Synthetic pathology: serum creatinine 98 umol/L')
        two = doc.new_page()
        doc.save(path)


def test_local_pdf_import_preserves_original_and_marks_all_pages_unconfirmed(tmp_path,monkeypatch):
    folder = tmp_path / 'patient'
    folder.mkdir()
    monkeypatch.setattr(pathology_import.jobs,'patient_folder',lambda _:folder)
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    source = tmp_path / 'external pathology.pdf'
    make_source(source)
    patient = {'id':1}
    receipt = pathology_import.import_pdf(conn,patient,str(source))
    assert receipt['page_count'] == 2
    assert receipt['pages'][0]['method'] == 'pdf_text'
    assert receipt['pages'][1]['method'] == 'unreadable_or_scanned'
    assert receipt['verification'].startswith('unconfirmed')
    copied = folder / 'Pathology' / receipt['name']
    assert copied.read_bytes() == source.read_bytes()
    assert receipt['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert pathology_import.sources(conn,patient)['sources'][0]['id'] == receipt['id']
    with pytest.raises(ValueError,match='already imported'):
        pathology_import.import_pdf(conn,patient,str(source))
    assert len(list((folder / 'Pathology').iterdir())) == 1


def test_corrupt_and_passwordless_non_pdf_rejected_without_patient_changes(tmp_path,monkeypatch):
    folder = tmp_path / 'patient'
    folder.mkdir()
    monkeypatch.setattr(pathology_import.jobs,'patient_folder',lambda _:folder)
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    source = tmp_path / 'damaged.pdf'
    source.write_bytes(b'%PDF-invalid')
    with pytest.raises(ValueError,match='damaged|unreadable'):
        pathology_import.import_pdf(conn,{'id':1},str(source))
    assert pathology_import.sources(conn,{'id':1})['sources'] == []


def test_original_pathology_import_rejects_symlinks(tmp_path,monkeypatch):
    folder = tmp_path / 'patient'
    folder.mkdir()
    monkeypatch.setattr(pathology_import.jobs,'patient_folder',lambda _:folder)
    import db; conn = db.connect(str(tmp_path / 'p.db'))
    source = tmp_path / 'plain.pdf'
    make_source(source)
    shortcut = tmp_path / 'link.pdf'
    try:
        shortcut.symlink_to(source)
    except OSError:
        pytest.skip('symlink unavailable')
    with pytest.raises(ValueError,match='regular pathology'):
        pathology_import.import_pdf(conn,{'id':1},str(shortcut))
