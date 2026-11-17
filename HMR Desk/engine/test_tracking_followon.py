"""Offline regression checks for proposal, archive and multi-episode tracking."""
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import api, db, importer, inbox, lifecycle, messaging, steps

with TemporaryDirectory() as tmp, patch.object(db, 'BASE', tmp), closing(db.connect(str(Path(tmp) / 'test.db'))) as c:
    root = Path(tmp); now = dt.datetime.now(dt.timezone.utc); day = dt.date.today()
    c.execute("INSERT INTO patients(key,name,phone,state,visit_date,visit_time) VALUES ('proposal','Proposed Patient','0412345678','offered','2030-01-01','09:00')")
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at,visit_date,visit_time) VALUES ('proposal-out',1,'out','new time','change_request','Sent',?,'2030-01-02','10:00')", (now.isoformat(),))
    with patch('inbox.append_decline') as register:
        msg = inbox.ingest(c, 'proposal-in', '0412345678', 'no thanks', (now + dt.timedelta(seconds=1)).isoformat(), 'test')
        p = c.execute('SELECT * FROM patients WHERE id=1').fetchone()
        assert msg['kind'] == 'OTHER' and p['state'] == 'offered' and p['visit_date'] == '2030-01-01'
        assert messaging.waiting_replies(c, 1) and not register.called
        inbox.resolve(c, msg, {'as':'decline'})
        p = c.execute('SELECT * FROM patients WHERE id=1').fetchone()
        assert p['state'] == 'declined' and p['visit_date'] is None and register.called
    c.execute("UPDATE patients SET state='offered',visit_date='2030-01-01',visit_time='09:00' WHERE id=1")
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,offer_ref,created_at) VALUES ('proposal-other',1,'in','That works?','OTHER','received','proposal-out',?)", (now.isoformat(),))
    inbox.resolve(c, c.execute("SELECT * FROM messages WHERE id='proposal-other'").fetchone(), {'as':'yes'})
    assert tuple(c.execute('SELECT state,visit_date,visit_time FROM patients WHERE id=1').fetchone()) == ('confirmed','2030-01-02','10:00')
    c.execute("INSERT INTO patients(key,name,state,call_list,archived_at,visit_date) VALUES ('archived','Archived Patient','claimed',1,'2026-01-01',?)", (str(day),))
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('archived-in',2,'in','question','OTHER','received',?)", (now.isoformat(),))
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('archived-draft',2,'out','reply','custom','draft',?)", (now.isoformat(),))
    for section in ('needs_you','waiting','upcoming','recent'):
        assert all(x.get('patient_id') != 2 for x in messaging.board(c)[section])
    assert all(item.get('patient_id') != 2 for group in lifecycle.attention(c)['groups'] for item in group['items'])
    assert all(item['id'] != 2 for item in api.handle(c,'GET','/api/today',{},None)[1]['visits'])
    assert any(x['id'] == 'archived-in' for x in api.handle(c,'GET','/api/patients/2',{},None)[1]['messages'])
    c.execute("INSERT INTO patients(key,name,state) VALUES ('multi','Multi Patient','claimed')")
    old, newer = str(day-dt.timedelta(days=120)), str(day-dt.timedelta(days=60))
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (3,'hmr',?,'import')", (newer,))
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (3,'hmr',?,'import')", (old,))
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (3,'hmr',NULL,'app')")
    db.log(c, 3, 'not_visited', {'date':str(day)}, 'app')
    assert api.patient_followups(c, 3)['visit_date'] == newer
    assert steps.event_date(c, c.execute('SELECT * FROM patients WHERE id=3').fetchone(), 'claimed') is None
    plan = root / 'Appointment_Plan_1.json'
    plan.write_text(json.dumps({'patients':[{'Name':'Import Patient','Status':'Suggested','Conversation note':'external','Reply':'legacy reply'}]}))
    importer.run(c, root)
    row = c.execute("SELECT * FROM patients WHERE key='import patient'").fetchone(); pid = row['id']
    db.log(c, pid, 'state', {'from':'pooled','to':'pooled','text':'unrelated'}, 'app')
    data = json.loads(plan.read_text()); data['patients'][0]['Conversation note'] = 'updated external'
    plan.write_text(json.dumps(data)); importer.run(c, root)
    assert c.execute('SELECT note FROM patients WHERE id=?',(pid,)).fetchone()[0] == 'updated external'
    p = c.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    api.action(c, p, {'action':'hold','note':'manual hold'})
    data['patients'][0].update(Status='Confirmed', Date='2000-01-01', **{'Conversation note':'stale external'})
    plan.write_text(json.dumps(data)); report = importer.run(c, root)
    row = c.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    assert row['state'] == 'hold' and row['note'] == 'manual hold' and row['visit_date'] is None
    assert any('App-owned plan conflict' in item for item in report['checks'])
