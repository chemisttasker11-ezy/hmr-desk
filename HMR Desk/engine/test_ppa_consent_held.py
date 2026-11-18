"""PPA 'written consent held' may only be asserted from signed-consent evidence."""
import json
import os

import api
import db
import records


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'test.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    c = db.connect()
    folder = tmp_path / 'Visited' / 'Synthetic One'
    folder.mkdir(parents=True)
    c.execute("INSERT INTO patients (key,name,state,folder) VALUES ('1','Synthetic One','sent',?)", (str(folder.relative_to(tmp_path)),))
    return c, c.execute('SELECT * FROM patients WHERE id=1').fetchone(), folder


def _interview(c, signed):
    records.put(c, 1, 'interview.json', json.dumps({'consent': {'signed': signed}}).encode('utf-8'))


def test_no_interview_record_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    assert api.consent_held(c, p) is False


def test_signed_flag_without_signed_file_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _interview(c, True)
    assert api.consent_held(c, p) is False


def test_signed_file_without_signed_flag_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _interview(c, False)
    (folder / 'PPA Consent - Synthetic One signed.pdf').write_bytes(b'%PDF-1.4 synthetic')
    assert api.consent_held(c, p) is False


def test_signed_flag_and_signed_file_is_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _interview(c, True)
    (folder / 'PPA Consent - Synthetic One signed.pdf').write_bytes(b'%PDF-1.4 synthetic')
    assert api.consent_held(c, p) is True
