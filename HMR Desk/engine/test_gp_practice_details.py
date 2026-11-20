"""Synthetic GP and practice metadata acceptance. No patient identifiers or external services."""
import sqlite3

import db
import jobs
import referral_entry
import report
import steps


def test_schema_v1_to_v2_adds_gp_details_without_changing_existing_rows():
    db_v1 = db.SCHEMA.replace(
        "gp TEXT, clinic TEXT, gp_provider TEXT, clinic_address TEXT, clinic_phone TEXT, referral_date TEXT,",
        "gp TEXT, clinic TEXT, referral_date TEXT,")
    assert db_v1 != db.SCHEMA
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(db_v1)
        conn.execute("INSERT INTO patients(key,name,gp,clinic) VALUES ('synthetic','Fictional Person','Dr Example','Example Practice')")
        conn.execute('PRAGMA user_version = 1')
        db.migrate_schema(conn)
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        columns = {row[1] for row in conn.execute('PRAGMA table_info(patients)')}
        assert {'gp_provider', 'clinic_address', 'clinic_phone'} <= columns
        conn.execute("UPDATE patients SET gp_provider='123456AB', clinic_address='1 Example St', clinic_phone='0700000000' WHERE key='synthetic'")
        assert conn.execute("SELECT name,gp_provider,clinic_address,clinic_phone FROM patients WHERE key='synthetic'").fetchone() == (
            'Fictional Person', '123456AB', '1 Example St', '0700000000')
        db.migrate_schema(conn)  # idempotent, no data loss
        assert conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 1
    finally:
        conn.close()


def test_gp_practice_fields_allowed_in_review_and_legacy_corrections():
    fields = {'gp_provider', 'clinic_address', 'clinic_phone'}
    assert fields <= set(referral_entry.FIELDS)
    assert fields <= jobs.FIELDS


def test_confirmed_gp_practice_details_reach_report_without_guessing(monkeypatch):
    monkeypatch.setattr(steps, 'event_date', lambda *_args: None)
    patient = {
        'name': 'Fictional Person', 'gp': 'Dr Example', 'clinic': 'Example Practice',
        'gp_provider': '123456AB', 'clinic_address': '1 Example Street, QLD',
        'clinic_phone': '(07) 0000 0000', 'referral_date': '2026-11-18',
        'dob': '1950-05-03', 'phone': '0400000000', 'address': '99 Fiction Street',
        'suburb': 'Sample', 'visit_date': '2026-11-19'}
    interview = {'header': {'gp': '', 'dob': '1950-05-03', 'visit': '2026-11-19'}}
    doctor = report._demographics(None, patient, interview)['doctor']
    for value in ('Dr Example', 'Provider number: 123456AB', 'Example Practice',
                  'Practice address: 1 Example Street, QLD',
                  'Practice phone: (07) 0000 0000', 'Request date: 18/11/2026'):
        assert value in doctor
    for field in ('gp_provider', 'clinic_address', 'clinic_phone'):
        patient[field] = None
    without = report._demographics(None, patient, interview)['doctor']
    assert 'Provider number:' not in without
    assert 'Practice address:' not in without
    assert 'Practice phone:' not in without
