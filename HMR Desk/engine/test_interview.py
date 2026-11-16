"""Interview checks: synthetic data in system temporary folders only."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from docx import Document
import fitz
import agents
import db
import interview
import jobs
import steps

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    folder = root / 'Scheduled' / 'Test Person'; folder.mkdir(parents=True)
    (folder / 'Pathology').mkdir(); (folder / 'Pathology' / '2026-01-02 FBC.pdf').write_bytes(b'')
    (root / 'scripts' / 'intake').mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts' / 'intake' / 'intake.py', root / 'scripts' / 'intake' / 'intake.py')
    conn = db.connect(); conn.execute("INSERT INTO patients(key,name,state,folder,dob,medicare) VALUES ('test person','Test Person','confirmed',?,'2000-01-01','123')", (str(folder.relative_to(root)),)); conn.commit()
    p = conn.execute('SELECT * FROM patients').fetchone()
    data = interview.load(conn, p); assert not data['saved'] and data['header']['name'] == 'Test Person' and data['pathology'] == [['FBC', '', '2026-01-02', '']]
    pdf = fitz.open(); page = pdf.new_page(); page.insert_text((72,72), 'DOMICILIARY MEDICATION MANAGEMENT\nMedication List\nZinc 10mg tablet\nOne daily.\nAspirin 100mg tablet\nOne daily.\nConditions\nDiabetes\nAllergies\nRash\nMeasurements\nHeight\n170 cm\nWeight\n70 kg\nBP\n120/80\neGFR\n65 mL/min\nSocial History\nSmoking: Never\nAlcohol: None'); pdf.save(folder / 'referral.pdf'); pdf.close()
    data = interview.load(conn, p); assert [row[0] for row in data['meds']] == ['Zinc 10mg tablet', 'Aspirin 100mg tablet'] and data['conditions'] == 'Diabetes' and data['allergies'] == 'Rash' and all('from referral - check' in x for x in data['sources'] if 'referral' in x)
    assert '170 cm' in data['obs'][0][1] and data['obs'][1][1] == '120/80' and '65 mL/min' in data['obs'][3][1]
    assert 'Never' in data['alcohol_smoking'] and 'None' in data['alcohol_smoking'] and data['social']
    (folder / 'referral.pdf').rename(folder / 'Test Person_ AB.pdf')
    data = interview.load(conn, p); assert [row[0] for row in data['meds']] == ['Zinc 10mg tablet', 'Aspirin 100mg tablet']
    (folder / 'Test Person_ AB.pdf').unlink()
    pdf = fitz.open(); pdf.new_page(); pdf.save(folder / 'Test Person_ AB.pdf'); pdf.close()
    original_spec = interview.importlib.util.spec_from_file_location
    def with_ocr(fake):
        def make_spec(*args, **kwargs):
            spec = original_spec(*args, **kwargs); execute = spec.loader.exec_module
            def load_module(module):
                execute(module); module.ocr_pdfs = fake
            spec.loader.exec_module = load_module
            return spec
        return patch.object(interview.importlib.util, 'spec_from_file_location', side_effect=make_spec)
    ocr_text = 'DOMICILIARY MEDICATION MANAGEMENT\nMedication List\nZinc 10mg tablet\nOne daily.\nConditions\nDiabetes'
    with with_ocr(lambda paths: {str(paths[0]): [ocr_text]}):
        data = interview.load(conn, p); assert data['meds'][0][0] == 'Zinc 10mg tablet'
    def failed_ocr(paths): raise RuntimeError('OCR unavailable')
    with with_ocr(failed_ocr):
        data = interview.load(conn, p); assert 'Referral is a scan; OCR failed - check by eye' in data['clarify']
    with with_ocr(lambda paths: {str(paths[0]): []}):
        data = interview.load(conn, p); assert 'Referral is a scan; OCR failed - check by eye' in data['clarify']
    (folder / 'Test Person_ AB.pdf').unlink()
    pdf = fitz.open(); page = pdf.new_page(); page.insert_text((72,72), 'DOMICILIARY MEDICATION MANAGEMENT\nMedication List\nZinc 10mg tablet\nOne daily.\nAspirin 100mg tablet\nOne daily.\nConditions\nDiabetes\nAllergies\nRash\nMeasurements\nHeight\n170 cm\nWeight\n70 kg\nBP\n120/80\neGFR\n65 mL/min\nSocial History\nSmoking: Never\nAlcohol: None'); pdf.save(folder / 'referral.pdf'); pdf.close()
    data = interview.load(conn, p)
    data['header'].update(visit='2026-11-15 11:00', gp='Dr Test', referral_date='2026-10-01')
    interview.save(conn, p, data); conn.commit()
    assert [r[0] for r in interview.load(conn, p)['meds']] == ['Zinc 10mg tablet', 'Aspirin 100mg tablet']
    exported = Document(interview.export(conn, p, 'docx'))
    headers = [p.text for p in exported.paragraphs[1:12]]
    assert headers == ['Name: Test Person', 'DOB: 01/01/2000', 'Age: ' + data['header']['age'], 'Address: ', 'Phone: ', 'GP: Dr Test', 'Visit: 15/11/2026 11:00', 'Referral date: 2026-10-01', 'Pharmacist: ' + data['header']['pharmacist'], 'Pharmacist phone: ' + data['header']['pharmacist_phone'], 'Credential: ' + data['header']['pharmacist_credential']]
    med_table = next(t for t in exported.tables if t.rows[0].cells[0].text == 'Medicine')
    assert [med_table.rows[i].cells[0].text for i in (1, 2)] == ['Zinc 10mg tablet', 'Aspirin 100mg tablet']
    (folder / 'interview.json').unlink()
    specs = root / 'Scheduled' / '_interview specs'; specs.mkdir(); spec = specs / 'test_person.json'
    spec.write_text(json.dumps({'conditions':'Prior', 'allergies':'None known', 'meds':[['Drug','Daily','Question']], 'pathology':[['FBC','normal','2026','']], 'clarify':['Ask'], 'obs_from_referral':'value'}), encoding='utf-8')
    data = interview.load(conn,p); assert data['conditions'] == 'Prior' and data['meds'][0] == ['Drug','Daily','','Question',''] and data['obs'][0][1] == 'value'
    data['details'].update(manager='other', manager_details='Daughter', daa='yes', daa_type='webster', daa_pharmacy='Local', smoking='unknown', alcohol='no', height_referral='170 cm', height_actual='171 cm')
    data['details']['meds'][0] = {'packed': 'unknown', 'as_instructed': False, 'checked': True, 'priority': 3, 'use_status': 'not_using', 'use_reason': 'side_effects', 'use_details': 'Rash reported'}
    data['meds'][0][2] = 'Actual use and clinical note'; data['meds'][0][4] = 'Annotation'
    data['consent'].update(by='authorised', relationship=0, authorised_name='')
    interview.save(conn,p,data); loaded = interview.load(conn,p)
    assert loaded['details'] == data['details'] and loaded['details']['meds'][0]['checked'] and loaded['details']['meds'][0]['priority'] == 3 and loaded['meds'][0][2] == 'Actual use and clinical note'
    assert 'Unknown' in interview.details_text(loaded) and 'DAA: unknown' in interview.medicine_rows(loaded)[0][4] and 'Not using — Side effects: Rash reported' in interview.medicine_rows(loaded)[0][4]
    old = interview.load(conn, p)
    for key in interview.NEW_FIELDS: old['details'].pop(key)
    old['details']['meds'][0].pop('prn_use')
    old['other_meds'].append(['Supplement', 'daily', '', '']); old['details']['other_meds'].append({'checked': False, 'priority': 0})
    interview.validate(json.loads(json.dumps(old)))
    (folder / 'interview.json').write_text(json.dumps(old), encoding='utf-8')
    old = interview.load(conn, p); interview.validate(old); interview.save(conn, p, old); old = interview.load(conn, p)
    assert all(old['details'][k] == '' for k in interview.NEW_FIELDS) and old['details']['meds'][0]['prn_use'] == '' and old['details']['other_meds'][0]['kind'] == ''
    old['details'].update(present='with_other', present_details='Family', sx_falls='yes'); old['details']['meds'][0]['prn_use'] = 'weekly'; old['details']['other_meds'][0]['kind'] = 'otc'
    interview.save(conn, p, old); new = interview.load(conn, p)
    assert new['details'] == old['details'] and 'With carer or family' in interview.details_text(new) and 'How often used: weekly' in interview.medicine_rows(new)[0][4]
    for key, value in [('sx_falls', 'bad'), ('unexpected', 'x')]:
        invalid = json.loads(json.dumps(new)); invalid['details'][key] = value
        try: interview.validate(invalid); raise AssertionError('invalid details accepted')
        except ValueError: pass
    invalid = json.loads(json.dumps(new)); invalid['details']['other_meds'][0]['kind'] = 'bad'
    try: interview.validate(invalid); raise AssertionError('invalid kind accepted')
    except ValueError: pass
    with patch.object(jobs, 'interview_spec_path', return_value=root / 'absent'), patch.object(interview, 'referral_text', return_value=('synthetic', [])), patch.object(interview.referral, 'parse', return_value={'meds': [('Drug', 'daily')], 'ceased': ['Old drug 5mg daily'], 'reason': '', 'conditions': [], 'allergies': [], 'obs': {'height': '', 'weight': '', 'bmi': '', 'bp': ''}, 'renal': '', 'alcohol': '', 'smoking': '', 'social': '', 'unparsed': []}):
        prefill = interview.blank(conn, p)
    assert prefill['meds'][1][0] == 'Old drug 5mg daily' and prefill['details']['meds'][1]['use_status'] == 'not_using' and prefill['details']['meds'][1]['use_details'] == 'Ceased per referral'
    with patch.object(interview, 'referral_text', return_value=('Reason for referral\nReview medicines\nCeased medicines\nDrug\nOld drug 5mg daily', [])), patch.object(interview.referral, 'parse', return_value={'reason': 'Review medicines', 'ceased': ['drug', 'Old drug 5mg daily']}):
        prefill = interview.blank(conn, p)
    assert prefill['details']['reason'] == 'Review medicines' and [r[0] for r in prefill['meds']] == ['Drug', 'Old drug 5mg daily']
    assert not prefill['details']['meds'][0].get('use_status') and prefill['details']['meds'][1]['use_status'] == 'not_using'
    data['revision'] = interview.revision(folder / 'interview.json')
    invalid = json.loads(json.dumps(data)); invalid['consent']['signed'] = True
    try: interview.validate(invalid); raise AssertionError('incomplete signed consent accepted')
    except ValueError: pass
    assert loaded['details']['other_meds'] == []
    invalid = json.loads(json.dumps(data)); invalid['details']['meds'][0]['use_reason'] = 'invented'
    try: interview.validate(invalid); raise AssertionError('invalid use reason accepted')
    except ValueError: pass
    invalid = json.loads(json.dumps(data)); invalid['details']['smoking'] = 'invented'
    try: interview.validate(invalid); raise AssertionError('invalid answer accepted')
    except ValueError: pass
    invalid = json.loads(json.dumps(data)); invalid['details']['meds'].append({'packed': '', 'as_instructed': False})
    try: interview.validate(invalid); raise AssertionError('orphan medicine metadata accepted')
    except ValueError: pass
    data['consent'].update(by='patient')
    data['notes'] = 'First'; interview.save(conn,p,data); conn.commit(); data['notes'] = 'Second'; interview.save(conn,p,data); conn.commit()
    assert json.loads((folder / 'interview.json.bak').read_text(encoding='utf-8'))['notes'] == 'First'
    for field, bad in [('notes', 'x'*20001), ('meds', [['x']]), ('pathology', [['']*4]*81)]:
        invalid = dict(data); invalid[field] = bad
        try: interview.save(conn,p,invalid); raise AssertionError('validation accepted ' + field)
        except ValueError: pass
    first = Path(interview.export(conn,p,'docx')); second = Path(interview.export(conn,p,'docx')); assert first != second and first.exists() and second.exists()
    roundtrip = Document(first); assert 'Medicine management: Someone else' in '\n'.join(x.text for x in roundtrip.paragraphs)
    med_export = next(t for t in roundtrip.tables if t.rows[0].cells[0].text == 'Medicine'); assert 'Actual use and clinical note' in med_export.rows[1].cells[2].text and 'Annotation' in med_export.rows[1].cells[4].text and 'DAA: unknown' in med_export.rows[1].cells[4].text
    headings = [x.text for x in roundtrip.paragraphs]; assert headings.index('Interview notes') < headings.index('Allergies / adverse reactions') < headings.index('Medicines on referral')
    with patch('interview.subprocess.run', side_effect=OSError('Word unavailable')):
        try: interview.export(conn,p,'pdf'); raise AssertionError('conversion should fail')
        except RuntimeError as exc: assert 'DOCX kept' in str(exc)
    def convert(args, **kwargs):
        Path(args[-1]).write_bytes(b'synthetic pdf')
    with patch('interview.subprocess.run', side_effect=convert):
        output = Path(interview.export(conn,p,'both')); assert output.with_suffix('.pdf').read_bytes() == b'synthetic pdf'
    assert 'PPA consent form not added' in interview.pack(conn,p)
    templates = root / 'TEMPLATES'; templates.mkdir(); (templates / 'PPA Consent.pdf').write_bytes(b'consent')
    interview.pack(conn,p); consent = folder / 'PPA Consent - Test Person.pdf'; assert consent.read_bytes() == b'consent'
    (templates / 'PPA Consent.pdf').write_bytes(b'changed'); interview.pack(conn,p); assert consent.read_bytes() == b'consent'; consent.unlink(); (templates / 'PPA Consent.pdf').unlink()
    form = fitz.open(); page = form.new_page()
    for i, field in enumerate(('Patient Name Given name and family name', 'Patient signature')):
        widget = fitz.Widget(); widget.field_name = field; widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = fitz.Rect(40, 40 + i * 40, 240, 65 + i * 40); page.add_widget(widget)
    form.save(templates / 'PPA Consent.pdf'); form.close()
    interview.pack(conn,p)
    with fitz.open(consent) as form:
        values = {w.field_name: w.field_value for page in form for w in page.widgets() or []}
        assert values['Patient Name Given name and family name'] == 'Test Person' and not values['Patient signature']
    signed = folder / 'consent signed.pdf'; signed.write_bytes(b'synthetic')
    assert interview.load(conn,p)['consent_file'] == signed.name
    signed.unlink(); consent.unlink(); (templates / 'PPA Consent.pdf').unlink()
    doc = Document(); para = doc.add_paragraph(); para.add_run('{{na'); para.add_run('me}} {{dob}} {{address}} {{medicare}} {{date}} {{pharmacist}}'); doc.save(templates / 'PPA Consent.docx')
    interview.pack(conn,p); assert 'Test Person 2000-01-01' in Document(folder / 'PPA Consent - Test Person.docx').paragraphs[0].text
    data = interview.load(conn,p); data['meds'] = [['Drug','','','Mine',''], ['Other','','','','']]; data['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in data['meds']]; interview.save(conn,p,data); conn.commit()
    with patch.object(agents, 'selected', return_value='stub'), patch.object(agents, 'run', return_value=json.dumps({'points': {'Drug':'Replace', 'Other':'Suggested'}, 'clarify':['Question']})):
        jobs.interview_assist(p['id'])
    data = interview.load(conn,p); assert data['meds'][0][3] == 'Mine' and data['meds'][1][3] == 'Suggested' and data['clarify'][-1] == 'Question'
    conn.execute("UPDATE patients SET state='sent' WHERE id=?", (p['id'],)); db.log(conn,p['id'],'visited',{'date':'2026-01-01'}); db.log(conn,p['id'],'report_sent',{'date':'2026-01-02'}); conn.commit(); p = conn.execute('SELECT * FROM patients').fetchone()
    assert steps.ready('claim',conn,p) == (False, 'PPA consent not recorded')
    data['consent'].update(signed=True,date='2026-01-01'); interview.save(conn,p,data); conn.commit(); assert steps.ready('claim',conn,p)[0]
    conn.close()
print('interview self-check ok')

# A legacy file gets a content token without rewriting it; concurrent stale saves cannot win.
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(Path(tmp) / 'race.db')
    folder = Path(tmp) / 'person'; folder.mkdir()
    conn = db.connect()
    conn.execute("INSERT INTO patients(key,name,state,folder) VALUES ('race','Synthetic','confirmed','person')"); conn.commit()
    p = conn.execute('SELECT * FROM patients').fetchone()
    initial = interview.load(conn, p); interview.save(conn, p, initial); conn.commit()
    old = json.loads((folder / 'interview.json').read_text(encoding='utf-8')); del old['details']['reason']
    interview.validate(old); (folder / 'interview.json').write_text(json.dumps(old), encoding='utf-8')
    raw = (folder / 'interview.json').read_bytes()
    first = interview.load(conn, p); second = interview.load(conn, p)
    assert (folder / 'interview.json').read_bytes() == raw and first['revision'] == second['revision'] and first['details']['reason'] == ''
    first['notes'] = 'first edit'; second['notes'] = 'second edit'
    barrier = Barrier(2)
    class FakeConnection:
        def execute(self, *args): pass
        def commit(self): pass
        def rollback(self): pass
    def compete(record):
        barrier.wait()
        try: interview.save(FakeConnection(), p, record); return 'saved'
        except interview.Conflict: return 'conflict'
    with patch.object(db, 'log'):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, (first, second)))
    assert sorted(results) == ['conflict', 'saved']
    assert interview.load(conn, p)['notes'] in ('first edit', 'second edit')
    stale = first if results[0] == 'conflict' else second
    current = interview.load(conn, p); current['consent'].update(signed=True, date='2026-01-01')
    interview.save(conn, p, current); conn.commit()
    try: interview.save(conn, p, stale); raise AssertionError('stale save erased signature')
    except interview.Conflict: pass
    assert interview.load(conn, p)['consent']['signed'] is True
    pending = interview.load(conn, p); pending['consent'].update(signed=False, by='authorised', relationship=0, authorised_name='')
    pending['consent_signed_draft'] = True; interview.save(conn, p, pending); conn.commit()
    assert interview.load(conn, p)['consent_signed_draft'] is True
    try: interview.export(conn, p, 'docx'); raise AssertionError('incomplete consent exported')
    except ValueError: pass
    # Failures after the file write restore both the record and its previous backup.
    original = (folder / 'interview.json').read_bytes(); backup = (folder / 'interview.json.bak').read_bytes()
    changed = interview.load(conn, p); changed['notes'] = 'not committed'; old_revision = changed['revision']
    with patch.object(db, 'log', side_effect=RuntimeError('audit failed')):
        try: interview.save(conn, p, changed); raise AssertionError('audit failure ignored')
        except RuntimeError as exc: assert str(exc) == 'audit failed'
    assert (folder / 'interview.json').read_bytes() == original and (folder / 'interview.json.bak').read_bytes() == backup
    assert changed['revision'] == old_revision
    class CommitFailure:
        def execute(self, *args): return conn.execute(*args)
        def commit(self): raise RuntimeError('commit failed')
        def rollback(self): return conn.rollback()
    try: interview.save(CommitFailure(), p, changed); raise AssertionError('commit failure ignored')
    except RuntimeError as exc: assert str(exc) == 'commit failed'
    assert (folder / 'interview.json').read_bytes() == original and (folder / 'interview.json.bak').read_bytes() == backup
    assert changed['revision'] == old_revision
    conn.close()
