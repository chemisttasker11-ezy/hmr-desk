"""Cross-patient legacy-import safety tests (entirely invented bytes).

These exercise the production migration functions, not a parsing replica. A link
must never cause records from another workspace to be admitted as this patient.
The mocked-link test runs on Windows accounts without symlink privileges.
"""
import sqlite3
from pathlib import Path

import pytest

import records


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    try:
        yield db
    finally:
        db.close()


def test_regular_legacy_record_import_remains_verbatim(conn, tmp_path):
    folder = tmp_path / 'fictional-patient'
    folder.mkdir()
    original = b'{"notes":"invented ordinary record"}'
    (folder / 'interview.json').write_bytes(original)
    assert records.import_folder(conn, 11, folder) == {'interview.json': 'imported'}
    assert records.get(conn, 11, 'interview.json') == original
    assert (folder / 'interview.json').read_bytes() == original


def test_mocked_link_is_not_admitted_even_without_windows_symlink_privilege(conn, tmp_path, monkeypatch):
    folder = tmp_path / 'fictional-patient'
    folder.mkdir()
    entry = folder / 'interview.json'
    entry.write_bytes(b'{"notes":"invented-other-patient"}')
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink',
                        lambda self: True if self == entry else real_is_symlink(self))
    assert records.import_folder(conn, 11, folder) == {}
    assert records.get(conn, 11, 'interview.json') is None
    assert records.import_file(conn, 11, 'interview.json', entry) is None


def test_real_link_to_other_patient_is_never_imported(conn, tmp_path):
    folder = tmp_path / 'fictional-patient'
    folder.mkdir()
    other = tmp_path / 'fictional-other-patient.json'
    other.write_bytes(b'{"notes":"invented private source belonging elsewhere"}')
    link = folder / 'interview.json'
    try:
        link.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip('real symlink needs privileges on this host')
    assert records.import_folder(conn, 11, folder) == {}
    assert records.import_file(conn, 11, 'interview.json', link) is None
    assert records.get(conn, 11, 'interview.json') is None
    assert other.read_bytes() == b'{"notes":"invented private source belonging elsewhere"}'


def test_linked_parent_directory_is_not_imported(conn, tmp_path):
    source = tmp_path / 'fictional-external'
    source.mkdir()
    (source / 'report_spec.json').write_bytes(b'{"notes":"invented external report"}')
    linked_folder = tmp_path / 'fictional-patient'
    try:
        linked_folder.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('real directory symlink needs privileges on this host')
    assert records.import_folder(conn, 11, linked_folder) == {}
    assert records.get(conn, 11, 'report_spec.json') is None
