"""Referral intake fills the postcode column only from an explicit leading 4-digit postcode in the suburb text,
and visit timing refuses a missing postcode with an actionable message. Synthetic data only."""
import datetime as dt
from unittest.mock import patch

import fitz
import pytest

import db
import messaging
import referral_entry


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    pdf = tmp_path / 'source.pdf'
    doc = fitz.open(); page = doc.new_page(); page.insert_text((50, 70), 'Referral patient medication details for synthetic test.\n' * 8)
    doc.save(pdf); doc.close()
    class Parser:
        def classify(self, text): return 'referral', [], []
        def extract_fields(self, text): return {'name': 'Synthetic Person', 'gp': 'Test Doctor'}, []
    conn = db.connect(str(tmp_path / 'test.db'))
    with patch.object(referral_entry, 'parser', return_value=Parser()):
        yield conn, pdf
    conn.close()


def commit(conn, pdf, **extra):
    row = referral_entry.review(conn, [str(pdf)])['rows'][0]
    fields = {'name': 'Synthetic Person', 'gp': 'Test Doctor', **extra}
    pid = referral_entry.commit(conn, row['token'], fields)['patient_id']
    return conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()


def test_leading_postcode_in_suburb_text_is_stored(env):
    conn, pdf = env
    p = commit(conn, pdf, suburb='4000 Synthetic City', address='1234 Synthetic Road')
    assert p['postcode'] == '4000'


@pytest.mark.parametrize('suburb,address', [('Synthetic City', '1234 Synthetic Road'), ('', '12 Street 4217'), ('Synthetic 4000', '')])
def test_no_leading_postcode_leaves_column_empty_and_never_guesses(env, suburb, address):
    conn, pdf = env
    p = commit(conn, pdf, suburb=suburb, address=address)
    assert p['postcode'] is None


def test_visit_time_with_postcode_works_and_without_gives_actionable_error(env):
    conn, pdf = env
    with_pc = commit(conn, pdf, suburb='4000 Synthetic City')
    when = dt.datetime(2026, 12, 1, 9, 0)
    assert messaging.visit_time(with_pc, when) == when
    without = dict(with_pc); without['postcode'] = None
    with pytest.raises(ValueError, match='postcode is required.*Edit details'):
        messaging.visit_time(without, when)
    without['postcode'] = '   '
    with pytest.raises(ValueError, match='postcode is required'):
        messaging.visit_time(without, when)
