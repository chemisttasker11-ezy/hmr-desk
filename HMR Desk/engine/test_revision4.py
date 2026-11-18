"""Revision 4 checks: temporary database and synthetic forms only."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import fitz
import api, db, interview, jobs, settings

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; os.environ['HMR_DB'] = str(root / 'test.db')
    folder = root / 'patient'; folder.mkdir(); templates = root / 'TEMPLATES'; templates.mkdir()
    conn = db.connect()
    # The product has no default pharmacist name, so the fixture sets the name the consent form should carry.
    settings.update(conn, {'pharmacist_name': 'Consultant Pharmacist'})
    try:
        conn.execute("INSERT INTO patients(key,name,state,folder,visit_date,visit_time) VALUES ('test','Test Person','confirmed','patient','2026-11-12','10:30')"); conn.commit()
        p = conn.execute('SELECT * FROM patients').fetchone()
        textfields = ['Name of Pharmacist Providing Service','Date of Service','Patient Name Given name and family name','Patient signature','Date of Consent','Authorised Person Signature','Date of Consent_2','Authorised Person Name']
        doc = fitz.open(); page = doc.new_page()
        for i, name in enumerate(textfields + ['Check Box' + str(x) for x in range(1,6)]):
            w = fitz.Widget(); w.field_name = name
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT if i < len(textfields) else fitz.PDF_WIDGET_TYPE_CHECKBOX
            w.rect = fitz.Rect(40, 30+i*40, 220 if i < len(textfields) else 60, 50+i*40)
            page.add_widget(w)
        doc.save(templates / 'PPA Consent.pdf'); doc.close()
        def save_fresh(record):
            # Interview saves are revision-checked against the records store; a client reloads before it saves.
            record['revision'] = interview.load(conn,p)['revision']
            return interview.save(conn,p,record)
        data = interview.load(conn,p); data['consent'] = {'signed':False,'date':''}
        (folder / 'interview.json').write_text(json.dumps(data),encoding='utf-8')
        data = interview.load(conn,p); assert data['consent'] == {'signed':False,'date':'','by':'patient','relationship':0,'authorised_name':''}
        def values():
            with fitz.open(folder / 'PPA Consent - Test Person.pdf') as form:
                return {w.field_name:w.field_value for pg in form for w in pg.widgets() or []}
        with patch('interview.export', return_value='synthetic'):
            interview.pack(conn,p)
            v = values()
            with fitz.open(folder / 'PPA Consent - Test Person.pdf') as form:
                fonts = {w.field_name: w.text_fontsize for pg in form for w in pg.widgets() or []}
                assert all(fonts[name] == 10 for name in textfields if name not in ('Patient signature', 'Authorised Person Signature'))
                assert all(fonts[name] == 0 for name in ('Patient signature', 'Authorised Person Signature'))
            assert v['Name of Pharmacist Providing Service'] == 'Consultant Pharmacist' and v['Date of Service'] == '12/11/2026' and v['Patient Name Given name and family name'] == 'Test Person'
            assert v['Date of Consent'] == '12/11/2026' and not v['Date of Consent_2'] and not v['Authorised Person Name']
            assert all(v['Check Box'+str(i)] in ('Off', None, '') for i in range(1,6))
            assert not v['Patient signature'] and not v['Authorised Person Signature']
            consent_path = folder / 'PPA Consent - Test Person.pdf'
            with fitz.open(consent_path) as form:
                page = form[0]; widget = next(w for w in page.widgets() if w.field_name == 'Date of Consent')
                widget.text_fontsize = 0; widget.update(); old_font = form.tobytes()
            consent_path.write_bytes(old_font); interview.pack(conn,p)
            with fitz.open(consent_path) as form:
                page = form[0]; assert next(w for w in page.widgets() if w.field_name == 'Date of Consent').text_fontsize == 10
            for i in range(1,6):
                data['consent'].update(by='authorised',relationship=i,authorised_name='Representative')
                save_fresh(data); v = values()
                assert not v['Date of Consent'] and v['Date of Consent_2'] == '12/11/2026' and v['Authorised Person Name'] == 'Representative'
                assert [v['Check Box'+str(n)] == 'Yes' for n in range(1,6)] == [n == i for n in range(1,6)]
                assert not v['Patient signature'] and not v['Authorised Person Signature']
            data['consent'].update(by='patient', relationship=0, authorised_name='')
            save_fresh(data); v = values()
            assert v['Date of Consent'] == '12/11/2026' and not v['Date of Consent_2'] and not v['Authorised Person Name']
            assert all(v['Check Box'+str(i)] in ('Off', None, '') for i in range(1,6))
            consent_path = folder / 'PPA Consent - Test Person.pdf'
            with fitz.open(consent_path) as signed_form:
                page = signed_form[0]; widget = next(w for w in page.widgets() if w.field_name == 'Patient signature')
                widget.field_value = 'entered signature'; widget.update()
                signed_bytes = signed_form.tobytes()
            consent_path.write_bytes(signed_bytes)
            data['consent'].update(by='authorised', relationship=2, authorised_name='Representative')
            save_fresh(data); assert consent_path.read_bytes() == signed_bytes
            consent_path.unlink(); interview.pack(conn,p)
            original = (folder / 'PPA Consent - Test Person.pdf').read_bytes()
            data['consent']['signed'] = True; save_fresh(data); interview.pack(conn,p)
            assert (folder / 'PPA Consent - Test Person.pdf').read_bytes() == original
            data['consent'].update(signed=False, relationship=1); save_fresh(data)
            (folder / 'signed document.pdf').write_bytes(b'signed')
            interview.pack(conn,p); assert (folder / 'PPA Consent - Test Person.pdf').read_bytes() == original
        for bad in [dict(by='authorised',relationship=0,authorised_name='Person'),dict(by='authorised',relationship=1,authorised_name=' '),dict(by='patient',relationship=True,authorised_name='')]:
            invalid = dict(data); invalid['consent'] = dict(data['consent'], signed=True, **bad)
            try: interview.validate(invalid); assert False
            except ValueError: pass
        def call(method,path,body=None): return api.handle(conn,method,path,{},body)
        listed = {x['key']:x for x in call('GET','/api/settings')[1]['settings']}
        assert len(listed) >= 10 and listed['referral_valid_days']['min'] == 30 and listed['referral_warn_days']['max'] == 90
        for bad in [{'unknown':1}, {'referral_warn_days':0}, {'referral_valid_days':366}, {'flow_includes_ai_assist':1}, {'interview_export_format':'other'}, {'pharmacist_name':False}, {'new_hmr_after_months':0}]:
            status, result = call('POST','/api/settings',bad); assert status == 400 and next(iter(bad)) in result['error']
        assert call('POST','/api/settings',{'referral_warn_days':5,'pharmacist_name':'New Name','pharmacist_phone':'123','pharmacist_credential':'CP','interview_export_format':'both','flow_includes_ai_assist':True})[0] == 200
        assert conn.execute("SELECT count(*) FROM events WHERE type='settings_updated'").fetchone()[0] == 1
        header = interview.load(conn,p)['header']; assert (header['pharmacist'],header['pharmacist_phone'],header['pharmacist_credential']) == ('New Name','123','CP')
        referral = (dt.date.today()-dt.timedelta(days=80)).isoformat(); conn.execute('UPDATE patients SET referral_date=? WHERE id=?',(referral,p['id'])); conn.commit()
        assert not any(a['type']=='referral expires' for a in call('GET','/api/today')[1]['alerts'])
        assert call('POST','/api/settings',{'referral_warn_days':10})[0] == 200
        assert any(a['type']=='referral expires' for a in call('GET','/api/today')[1]['alerts'])
        with patch.object(jobs, 'start', return_value='id') as start:
            assert call('POST','/api/jobs',{'job':'interview_pack','patient_id':p['id']})[0] == 200
            assert start.call_args.args[-1] == 'both'
        with patch.object(jobs, 'enqueue', return_value='task') as enqueue:
            # The medicine list and interaction result live in the records store now, not on disk (case.txt is still a plain file). Interactions are written after the confirmed list so they count as current.
            import records
            (folder / 'case.txt').write_text('case',encoding='utf-8')
            for record_name, body in (('confirmed_meds.json', b'{"meds":[],"allergies":[]}'), ('MIMS interactions.txt', b'done')): records.put(conn, p['id'], record_name, body)
            conn.execute("UPDATE patients SET state='visited' WHERE id=?",(p['id'],)); conn.commit()
            # AI report assist is off by default (it needs the privacy acknowledgement), so this check opts in explicitly.
            settings.update(conn, {'flow_includes_ai_assist':True,'clinical_ai_privacy_ack':True,'ai_report_assist':True})
            assert jobs.advance(conn,p['id'],after=3) == 'task' and enqueue.call_args.args[1] == 'report_assist'
            settings.update(conn, {'flow_includes_ai_assist':False})
            assert jobs.advance(conn,p['id'],after=3) == 'task' and enqueue.call_args.args[1] == 'report_start'
    finally: conn.close()
print('revision 4 self-check ok')

