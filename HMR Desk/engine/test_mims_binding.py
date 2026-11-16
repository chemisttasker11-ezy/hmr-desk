"""Synthetic interaction-result binding and stale completion checks."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import api
import db
import steps

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    folder = root / 'person'; folder.mkdir()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO patients(key,name,state,folder) VALUES ('mims','Synthetic','visited','person')"); conn.commit()
        patient = conn.execute('SELECT * FROM patients').fetchone()
        confirmed = folder / 'confirmed_meds.json'
        confirmed.write_text(json.dumps({'meds': [['aspirin', '']], 'allergies': []}), encoding='utf-8')
        with patch.object(api.mims, 'ingredients', side_effect=lambda name: [name.lower()]):
            entry = api.mims_lists(conn)[0]
            old_revision = entry['meds_revision']
            assert old_revision == hashlib.sha256(confirmed.read_bytes()).hexdigest()
            legacy = folder / 'MIMS interactions.txt'; legacy.write_text('legacy', encoding='utf-8')
            os.utime(legacy, ns=(1_000_000_000, 1_000_000_000))
            confirmed.write_text(json.dumps({'meds': [['metformin', '']], 'allergies': []}), encoding='utf-8')
            current_revision = hashlib.sha256(confirmed.read_bytes()).hexdigest()
            content = b'old helper result'
            old_name = 'MIMS interactions generated ' + old_revision + ' ' + hashlib.sha256(content).hexdigest() + '.txt'
            (folder / old_name).write_bytes(content)
            assert not steps.interactions_done(patient)
            conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('a1',?,'interactions','waiting','emims','now',0)", (patient['id'],)); conn.commit()
            status, response = api.handle(conn, 'POST', '/api/run/a1/result', {}, {'state': 'done', 'output': 'Saved', 'mims_result': old_name})
            assert status == 200 and response['state'] == 'failed'
            assert conn.execute("SELECT state FROM tasks WHERE id='a1'").fetchone()[0] == 'failed'
            assert legacy.read_text(encoding='utf-8') == 'legacy'
            content = b'new helper result'
            new_name = 'MIMS interactions generated ' + current_revision + ' ' + hashlib.sha256(content).hexdigest() + '.txt'
            output = folder / new_name; output.write_bytes(content)
            assert steps.interactions_done(patient)
            conn.execute("INSERT INTO tasks(id,patient_id,step,state,waiting_for,created,flow) VALUES ('a2',?,'interactions','waiting','emims','now',0)", (patient['id'],)); conn.commit()
            status, response = api.handle(conn, 'POST', '/api/run/a2/result', {}, {'state': 'done', 'output': 'Saved', 'mims_result': new_name})
            assert status == 200 and response['state'] == 'done'
            output.write_bytes(b'modified')
            assert not steps.interactions_done(patient)
            (folder / ('MIMS interactions generated unverified ' + '0' * 64 + '.txt')).write_text('unverified')
            assert not steps.interactions_done(patient)
            manual = folder / 'MIMS interactions (manual) test.txt'; manual.write_text('manual reviewed', encoding='utf-8')
            assert steps.interactions_done(patient)
            manual.unlink(); confirmed.unlink()
            assert steps.interactions_done(patient)  # Legacy records without a confirmed list remain usable.
    finally: conn.close()
print('MIMS result binding self-check ok')
