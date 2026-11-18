import json, os, tempfile
from pathlib import Path
from docx import Document
import records
import api, db

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    folder = Path(tmp) / 'patient'; folder.mkdir()
    conn = db.connect(os.path.join(tmp, 'test.db'))
    conn.execute("INSERT INTO patients(key,name,phone,folder,referral_date,state) VALUES ('test person','Test Person','0412345678','patient','01/01/2026','confirmed')")
    conn.execute("INSERT INTO visits(patient_id,kind,visit_date,report_sent,claimed,source) VALUES (1,'hmr','2026-01-10','2026-01-11','2026-01-12','import')")
    for row in [('offer','out','hello','offer','Delivered','2026-01-02T10:00:00'),('reply','in','YES','YES','received','2026-01-03T10:00:00')]:
        conn.execute('INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES (?,1,?,?,?,?,?)', row)
    for ts,typ,detail in [('2026-01-03T11:00:00','state',{'text':'Confirmed by SMS reply'}),('2026-01-04T11:00:00','import_change',{'x':[None,'']}),('2026-01-05T11:00:00','pathology_result',{'saved':['1','2','3','4']})]:
        conn.execute('INSERT INTO events(ts,patient_id,type,detail) VALUES (?,1,?,?)',(ts,typ,json.dumps(detail)))
    conn.commit()
    def call(method, route, body=None): return api.handle(conn, method, '/api/patients/1/' + route, {}, body or {})
    assert call('POST','action',{'action':'call','outcome':'no_answer','note':'morning'})[0] == 200
    assert conn.execute('SELECT state FROM patients').fetchone()[0] == 'confirmed'
    assert call('POST','action',{'action':'call','outcome':'bad'})[0] == 400
    assert call('POST','action',{'action':'followup_claimed','kind':'followup1','date':'2026-02-11'})[0] == 400
    assert call('POST','messages',{'kind':'custom'})[0] == 400
    status, draft = call('POST','messages',{'kind':'custom','body':'My text'})
    assert status == 200 and draft['body'] == 'My text' and draft['state'] == 'draft'
    records.put(conn, 1, 'report_spec.json', (json.dumps({'issues':[{'rec':'Review medicine'}]})).encode('utf-8')); conn.commit()
    status, data = call('GET','followup/1'); assert status == 200 and data['recommendations'] == [['Review medicine','','']]
    data['date'] = '2026-02-10'; data['method'] = 'phone'; data['recommendations'][0][1] = 'partly'
    assert call('POST','followup/1', data)[0] == 200
    assert call('POST','followup/1', data)[0] == 200
    assert conn.execute("SELECT count(*) FROM visits WHERE kind='followup1'").fetchone()[0] == 1
    assert call('POST','action',{'action':'followup_claimed','kind':'followup1','date':'2026-02-11'})[0] == 200
    first = Path(call('POST','followup/1/export')[1]['file']); second = Path(call('POST','followup/1/export')[1]['file'])
    assert first.name == 'HMR Follow-up 1 - Test Person.docx' and second.name == 'HMR Follow-up 1 - Test Person (2).docx'
    assert Document(first).tables[0].rows[1].cells[0].text == 'Review medicine'
    status, timeline = call('GET','timeline'); assert status == 200
    m = timeline['milestones']; labels = [e['label'] for e in timeline['entries']]
    assert all(x in labels for x in ['Offer sent (Delivered)','Reply: "YES" (YES)','Confirmed - Confirmed by SMS reply','Called - no answer','Pathology: 4 reports saved','Follow-up 1 done','Follow-up 1 claimed'])
    assert 'import_change' not in labels and labels.index('Pathology: 4 reports saved') < labels.index('Reply: "YES" (YES)')
    assert (m['referral_date'], m['referral_expiry'], m['first_contact'], m['last_reply'], m['confirmed']) == ('2026-01-01','2026-04-01','2026-01-02','2026-01-03','2026-01-03')
    assert (m['visit'],m['report_sent'],m['claimed'],m['call_attempts']) == ('2026-01-10','2026-01-11','2026-01-12',1)
    assert (m['followup1_due'],m['followup1_done'],m['followup1_claimed'],m['followup2_due'],m['followup2_done']) == ('2026-02-10','2026-02-10','2026-02-11','2026-03-10',None)
    conn.execute("UPDATE patients SET visit_date='2026-11-14',visit_time='09:30' WHERE id=1")
    conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('utc',1,'in','YES','YES','received','2026-11-11T08:45:00+00:00')")
    extra = [
        ('2026-11-11T18:30:00','state',{'from':'offered','to':'confirmed','text':'Booked'}),
        ('2026-11-12T00:01:00','state',{'from':'confirmed','to':'confirmed','text':'Updated'}),
        ('2026-11-11T19:00:00','referral_fields',{'dob':'secret','sex':'F','medicare':'private'}),
        ('2026-11-11T19:01:00','import_change',{'phone':['1','2'],'sex':['F','F']}),
        ('2026-11-11T19:02:00','import_change',{'phone':[None,'']}),
        ('2026-11-11T19:03:00','message_state',{'id':'offer','state':'Delivered'}),
        ('2026-11-11T19:04:00','pathology_result',{'status':'no report to read','saved':[]}),
        ('2026-11-11T19:05:00','pathology_result',{'status':'access code needed','saved':[]}),
    ]
    state_labels = {'offered':'Offered','confirmed':'Confirmed','pathology_ready':'Pathology ready','sheet_ready':'Interview sheet ready','visited':'Visited','report_drafted':'Report drafted','signed_off':'Signed off','sent':'Report sent','claimed':'Claimed','hold':'On hold','declined':'Declined','expired':'Referral expired'}
    extra += [('2026-11-11T20:00:00','state',{'to':key}) for key in state_labels]
    extra += [('2026-11-11T20:00:00',key,{}) for key in ('interview_saved','interview_pack','message_queued','message_drafted','autopilot_move_failed','autopilot_call_list','consent_signed','move_declined','something_new')]
    for ts, typ, detail in extra:
        conn.execute('INSERT INTO events(ts,patient_id,type,detail) VALUES (?,1,?,?)',(ts,typ,json.dumps(detail)))
    result = call('GET','timeline')[1]; entries = result['entries']; labels = [e['label'] for e in entries]
    reply = next(e for e in entries if e['kind']=='message' and e['at']=='2026-11-11T18:45')
    assert reply['at_text'] == 'Wed 11 Nov 2026, 6:45 pm'
    assert labels.index('Details filled from referral: DOB, sex, Medicare') < entries.index(reply) < labels.index('Confirmed - Booked')
    assert all(label in labels for label in state_labels.values())
    assert all(label in labels for label in ['Register updated: phone','Pathology: no reports in My Health Record','Pathology: access code needed','Interview saved','Interview pack made','Message queued','Message drafted','Autopilot: move failed','Autopilot: added to call list','Consent signed','Moved to Declined folder','something_new'])
    assert sum(label.startswith('Register updated:') for label in labels) == 1 and 'message_state' not in labels
    assert 'secret' not in str(entries) and 'private' not in str(entries)
    assert result['milestones']['confirmed'] == '2026-01-03'
    assert result['milestones']['scheduled_visit'] == '2026-11-14T09:30' and result['milestones']['visit'] == '2026-01-10'
    conn.close()
print('timeline self-check ok')
