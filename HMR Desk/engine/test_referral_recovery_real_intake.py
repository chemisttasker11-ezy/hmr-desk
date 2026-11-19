"""Referral demographic recovery with the real intake reader and a synthetic referral PDF.

The patient workspace holds no application scripts (as in a packaged install), so the reader must come from the
application's own resources, as the interview and referral entry code already do."""
import contextlib
import fitz
import pytest
import db, routes_work

LINES = ['Example Medical Centre', '1 Example Street, Exampleton QLD 4000', '', 'RE: Home Medicines Review referral',
         'Patient Details:', 'Name: Mrs Jane Syntheticexample', 'Date of birth: 01/02/1950', 'Medicare: 2123 45670 1',
         'Address: 2 Sample Road, Exampleton QLD 4000', 'Phone: 0400 000 000', '', 'General Practitioner Details:',
         'Name: Dr Test Referrer', 'Provider number: 1234567A', '', 'Current medications: aspirin 100 mg daily', 'Allergies: nil known']


@pytest.fixture
def conn(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'; (workspace / 'patient').mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(workspace)); monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.delenv('HMR_DB_KEY', raising=False)
    (tmp_path / 'userdata').mkdir()
    doc = fitz.open(); page = doc.new_page()
    for i, line in enumerate(LINES): page.insert_text((40, 60 + 18 * i), line, fontsize=11)
    doc.save(str(workspace / 'patient' / 'Syntheticexample Jane referral.pdf')); doc.close()
    with contextlib.closing(db.connect(str(tmp_path / 'userdata' / 'hmr.db'))) as c:
        c.execute("INSERT INTO patients(key,name,state,folder) VALUES ('s','Synthetic Patient','confirmed','patient')"); c.commit()
        yield c


def test_demographics_recovered_from_referral_without_scripts_in_workspace(conn):
    assert not (db.BASE and (__import__('pathlib').Path(db.BASE) / 'scripts').exists())
    patient = routes_work.fill_referral_fields(conn, conn.execute('SELECT * FROM patients WHERE id=1').fetchone())
    assert patient['dob'] == '01/02/1950' and patient['sex'] == 'F' and patient['medicare'] == '2123456701'
    assert conn.execute("SELECT count(*) FROM events WHERE patient_id=1 AND type='referral_fields'").fetchone()[0] == 1
