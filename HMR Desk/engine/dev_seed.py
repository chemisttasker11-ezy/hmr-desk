"""Developer and test-only seeding of a synthetic visit-stage patient.

Strictly off by default: nothing here runs unless the environment variable HMR_DEV_TOOLS is exactly "1".
There is no API route and no UI button; the only entry point is `engine_main --dev-seed-visit`
(see docs/dev-tools.md). All data is synthetic and the patient name is labelled DEV SEED.
Nothing is sent, so the SMS/phone gateway is never touched.
"""
import json
import os
import datetime as dt
from pathlib import Path

import api
import db

ENV_FLAG = 'HMR_DEV_TOOLS'


class DevToolsDisabled(RuntimeError):
    pass


def enabled():
    return os.environ.get(ENV_FLAG) == '1'


def require_enabled():
    if not enabled():
        raise DevToolsDisabled('Developer tools are off. Set %s=1 to use them (never on a pharmacist\'s machine).' % ENV_FLAG)


def seed_visit(conn):
    """Create a synthetic patient whose visit is recorded and whose medicines and interaction check are done.

    The new patient is ready for the "start report" step, so report generation, the sandboxed report viewer
    and the draft vault can be exercised without a referral, an SMS exchange or a real record.
    """
    require_enabled()
    n = conn.execute("SELECT COUNT(*) FROM patients WHERE key LIKE 'dev-seed-%'").fetchone()[0] + 1
    name = 'DEV SEED Synthetic Patient %d' % n
    folder = 'Visited/DEV SEED Synthetic Patient %d' % n  # stage folder, as for real visited patients
    path = Path(db.BASE) / folder
    path.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    conn.execute(
        "INSERT INTO patients(key,name,state,folder,gp,clinic,phone,address,suburb,postcode,dob,sex,medicare,"
        "referral_date,visit_date,visit_time,has_pathology,note,status_text,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ('dev-seed-%d' % n, name, 'visited', folder, 'Dr Test Synthetic', 'Synthetic Test Clinic', '0400000000',
         '1 Test Street', 'Testville', '4000', '1950-01-01', 'F', '0000000000', today, today, '10:00', 1,
         'Synthetic dev seed. Not a real patient.', 'Visited (dev seed)', db.now()))
    conn.commit()
    patient = conn.execute('SELECT * FROM patients WHERE key=?', ('dev-seed-%d' % n,)).fetchone()
    import records
    records.put_json(conn, patient['id'], 'confirmed_meds.json', {
        'meds': [['Synthetic medicine A 10 mg tablet', 'Brand A'], ['Synthetic medicine B 5 mg tablet', '']],
        'allergies': ['No known allergies (synthetic)']})
    conn.commit()
    api.action(conn, patient, {'action': 'interactions_manual', 'text': 'Synthetic dev seed: no interactions reviewed.'})
    db.log(conn, patient['id'], 'dev_seed', {'synthetic': True}, 'dev')
    conn.commit()
    return {'patient_id': patient['id'], 'name': name, 'folder': str(path), 'next_step': 'start report'}
