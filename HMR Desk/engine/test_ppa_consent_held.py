"""PPA 'written consent held' may only be asserted from the signed consent the app saved."""
import json

import fitz

import api
import db
import records

PNG = None


def _png():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
    pix.clear_with(0)
    return pix.tobytes('png')


def _setup(tmp_path, monkeypatch, signed_flag=True):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'test.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    c = db.connect()
    folder = tmp_path / 'Visited' / 'Synthetic One'
    folder.mkdir(parents=True)
    c.execute("INSERT INTO patients (key,name,state,folder) VALUES ('1','Synthetic One','sent',?)", (str(folder.relative_to(tmp_path)),))
    records.put(c, 1, 'interview.json', json.dumps({'consent': {'signed': signed_flag}}).encode('utf-8'))
    return c, c.execute('SELECT * FROM patients WHERE id=1').fetchone(), folder


def _pdf(path, with_signature=True, pages=2):
    doc = fitz.open()
    for _ in range(pages): doc.new_page()
    if with_signature: doc[pages - 1].insert_image(fitz.Rect(50, 50, 150, 100), stream=_png())
    doc.save(path); doc.close()


SIGNED = 'PPA Consent - Synthetic One signed.pdf'


def test_exact_saved_signed_file_with_signature_and_flag_is_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _pdf(folder / SIGNED)
    assert api.consent_held(c, p) is True


def test_no_interview_record_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    assert api.consent_held(c, dict(p, id=999)) is False


def test_flag_without_the_saved_file_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    assert api.consent_held(c, p) is False


def test_file_without_signed_flag_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch, signed_flag=False)
    _pdf(folder / SIGNED)
    assert api.consent_held(c, p) is False


def test_unrelated_file_with_signed_in_its_name_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _pdf(folder / 'Referral signed by GP.pdf')
    (folder / 'notes signed.txt').write_text('x')
    assert api.consent_held(c, p) is False


def test_stub_or_unsigned_pdf_is_not_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    (folder / SIGNED).write_bytes(b'%PDF-1.4 stub')
    assert api.consent_held(c, p) is False
    _pdf(folder / SIGNED, with_signature=False)
    assert api.consent_held(c, p) is False
    _pdf(folder / SIGNED, pages=1)
    assert api.consent_held(c, p) is False


def test_signed_file_for_a_previous_name_does_not_carry_over(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _pdf(folder / SIGNED)
    c.execute("UPDATE patients SET name='Renamed Person' WHERE id=1")
    assert api.consent_held(c, c.execute('SELECT * FROM patients WHERE id=1').fetchone()) is False


def test_removing_the_signed_file_withdraws_consent(tmp_path, monkeypatch):
    c, p, folder = _setup(tmp_path, monkeypatch)
    _pdf(folder / SIGNED)
    assert api.consent_held(c, p) is True
    (folder / SIGNED).unlink()
    assert api.consent_held(c, p) is False
