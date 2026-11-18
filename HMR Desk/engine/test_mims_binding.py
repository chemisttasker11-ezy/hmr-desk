"""Synthetic interaction-result binding and stale completion checks."""
import records
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import api
import db
import steps

api.MIMS_PATH = Path(__file__)  # Linux CI has no licensed helper; the list code only checks it exists
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    folder = root / 'person'; folder.mkdir()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO patients(key,name,state,folder) VALUES ('mims','Synthetic','visited','person')"); conn.commit()
        patient = conn.execute('SELECT * FROM patients').fetchone()
        pid = patient['id']
        def put_conf(d): records.put(conn, pid, 'confirmed_meds.json', json.dumps(d).encode('utf-8')); conn.commit()
        put_conf({'meds': [['aspirin', '']], 'allergies': []})
        with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower()]):
            entry = api.mims_lists(conn)[0]
            old_revision = entry['meds_revision']
            assert old_revision == hashlib.sha256(records.get(conn, pid, 'confirmed_meds.json')).hexdigest()
            import time; records.put(conn, pid, 'MIMS interactions.txt', b'legacy'); conn.commit(); time.sleep(0.01)
            put_conf({'meds': [['metformin', '']], 'allergies': []})
            current_revision = hashlib.sha256(records.get(conn, pid, 'confirmed_meds.json')).hexdigest()
            content = b'old helper result'
            old_name = 'MIMS interactions generated ' + old_revision + ' ' + hashlib.sha256(content).hexdigest() + '.txt'
            (folder / old_name).write_bytes(content)  # helper output lands as a plain file first
            assert not steps.interactions_done(conn, patient)
            conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('a1',?,'interactions','waiting','emims','now',0)", (patient['id'],)); conn.commit()
            status, response = api.handle(conn, 'POST', '/api/run/a1/result', {}, {'state': 'done', 'output': 'Saved', 'mims_result': old_name})
            assert status == 200 and response['state'] == 'failed'
            assert conn.execute("SELECT state FROM tasks WHERE id='a1'").fetchone()[0] == 'failed'
            assert records.get(conn, pid, 'MIMS interactions.txt') == b'legacy'
            content = b'new helper result'
            new_name = 'MIMS interactions generated ' + current_revision + ' ' + hashlib.sha256(content).hexdigest() + '.txt'
            output = folder / new_name; output.write_bytes(content)
            assert not steps.interactions_done(conn, patient)  # not in the store until the result is posted
            conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('a2',?,'interactions','waiting','emims','now',0)", (patient['id'],)); conn.commit()
            status, response = api.handle(conn, 'POST', '/api/run/a2/result', {}, {'state': 'done', 'output': 'Saved', 'mims_result': new_name})
            assert status == 200 and response['state'] == 'done'
            assert steps.interactions_done(conn, patient)
            records.put(conn, pid, new_name, b'modified'); conn.commit()
            assert not steps.interactions_done(conn, patient)
            records.put(conn, pid, 'MIMS interactions generated unverified ' + '0' * 64 + '.txt', b'unverified'); conn.commit()
            assert not steps.interactions_done(conn, patient)
            records.put(conn, pid, 'MIMS interactions (manual) test.txt', b'manual reviewed'); conn.commit()
            assert steps.interactions_done(conn, patient)
            records.delete(conn, pid, 'MIMS interactions (manual) test.txt'); records.delete(conn, pid, 'confirmed_meds.json'); conn.commit()
            assert steps.interactions_done(conn, patient)  # Legacy records without a confirmed list remain usable.
    finally: conn.close()
print('MIMS result binding self-check ok')
