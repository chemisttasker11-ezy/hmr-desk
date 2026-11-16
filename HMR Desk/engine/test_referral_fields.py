"""Synthetic checks for referral demographic recovery before pathology."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import api
import db
import interview
import jobs

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    (Path(tmp) / 'patient').mkdir()
    conn = db.connect(str(Path(tmp) / 'test.db'))
    for key, dob in [('one person', None), ('two person', '1999-01-01'), ('three person', None)]:
        conn.execute("INSERT INTO patients(key,name,state,folder,dob) VALUES (?,?,'confirmed','patient',?)", (key, key.title(), dob))
    conn.execute("UPDATE patients SET clinic='Existing Clinic' WHERE id=2")
    conn.commit()
    fields = {'dob': '01/02/1950', 'sex': 'F', 'medicare': '1234567890', 'irn': '2', 'clinic': 'Referral Clinic'}
    def run(pid):
        return api.handle(conn, 'POST', '/api/run', {}, {'steps': ['pathology'], 'patient_ids': [pid]})
    def spec_for(extract):
        def execute(module): module.extract_fields = extract
        return SimpleNamespace(loader=SimpleNamespace(exec_module=execute))
    with patch.object(interview, 'referral_text', return_value=('synthetic referral', [])), \
         patch.object(api.importlib.util, 'spec_from_file_location', return_value=spec_for(lambda text: (fields, []))), \
         patch.object(api.importlib.util, 'module_from_spec', side_effect=lambda spec: SimpleNamespace()), \
         patch.object(jobs, 'ensure_worker'):
        status, result = run(1)
        assert status == 200 and len(result['enqueued']) == 1 and not result['skipped']
        patient = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
        assert all(patient[k] == v for k, v in fields.items())
        event = conn.execute("SELECT * FROM events WHERE patient_id=1 AND type='referral_fields'").fetchall()
        assert len(event) == 1 and event[0]['source'] == 'engine' and json.loads(event[0]['detail']) == fields
        conn.execute("UPDATE patients SET clinic=NULL WHERE id=1")
        assert api.fill_referral_fields(conn, conn.execute('SELECT * FROM patients WHERE id=1').fetchone())['clinic'] == 'Referral Clinic'
        assert run(2)[1]['enqueued']
        patient = conn.execute('SELECT * FROM patients WHERE id=2').fetchone()
        assert patient['dob'] == '1999-01-01' and patient['medicare'] == fields['medicare'] and patient['clinic'] == 'Existing Clinic'
        assert 'dob' not in json.loads(conn.execute("SELECT detail FROM events WHERE patient_id=2 AND type='referral_fields'").fetchone()[0])
    def fail(text): raise ValueError('extraction failed')
    with patch.object(interview, 'referral_text', return_value=('synthetic referral', [])), \
         patch.object(api.importlib.util, 'spec_from_file_location', return_value=spec_for(fail)), \
         patch.object(api.importlib.util, 'module_from_spec', side_effect=lambda spec: SimpleNamespace()):
        status, result = run(3)
        assert status == 200 and not result['enqueued']
        assert result['skipped'][0]['reason'] == 'surname, DOB, sex and Medicare or IHI required'
        assert not conn.execute("SELECT 1 FROM events WHERE patient_id=3 AND type='referral_fields'").fetchone()
    conn.close()
print('referral field checks passed')
