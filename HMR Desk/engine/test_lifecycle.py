import datetime as dt
import os, tempfile
from pathlib import Path
import db, api, lifecycle

with tempfile.TemporaryDirectory() as tmp:
    os.environ['HMR_DB'] = str(Path(tmp)/'test.db')
    db.BASE = tmp
    c = db.connect()
    today = dt.date.today(); now = dt.datetime.now().replace(microsecond=0)
    def patient(state='new', **kw):
        n = c.execute('SELECT count(*) FROM patients').fetchone()[0] + 1
        kw.update(key=str(n), name='Patient '+str(n), state=state)
        c.execute('INSERT INTO patients ('+','.join(kw)+') VALUES ('+','.join('?' for _ in kw)+')', list(kw.values()))
        return c.execute('SELECT * FROM patients WHERE id=last_insert_rowid()').fetchone()
    def update(p, **kw):
        c.execute('UPDATE patients SET '+','.join(k+'=?' for k in kw)+' WHERE id=?', [*kw.values(),p['id']])
        return c.execute('SELECT * FROM patients WHERE id=?',(p['id'],)).fetchone()
    for state, expected in {'new':('intake','new referral'), 'pooled':('booking','to offer'), 'offered':('booking','offered'), 'visited':('report','to write'), 'report_drafted':('report','drafted'), 'signed_off':('report','signed'), 'sent':('claim','to claim'), 'claimed':('done','claimed'), 'hold':('hold',''), 'declined':('declined',''), 'expired':('expired','')}.items():
        assert tuple(lifecycle.stage(c,patient(state)).values()) == expected
    folder = Path(tmp)/'folder'; folder.mkdir(); (folder/'HMR interview.docx').write_text('test')
    for state in lifecycle.BOOKED:
        p = patient(state,folder='folder')
        assert lifecycle.stage(c,p)['stage'] == 'booking'
        assert lifecycle.stage(c,update(p,has_pathology=1)) == {'stage':'ready','step':'ready'}
    p = patient('claimed')
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (?,'hmr',?,'app')", (p['id'],str(today-dt.timedelta(days=40))))
    assert lifecycle.stage(c,p)['step'] == 'follow-up 1 due'
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (?,'followup1',?,'app')", (p['id'],str(today-dt.timedelta(days=31))))
    assert lifecycle.stage(c,p)['step'] == 'follow-up 1 to claim'
    c.execute("UPDATE visits SET claimed=? WHERE patient_id=? AND kind='followup1'", (str(today),p['id']))
    assert lifecycle.stage(c,p)['step'] == 'follow-up 2 due'
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (?,'followup2',?,'app')", (p['id'],str(today)))
    assert lifecycle.stage(c,p)['step'] == 'follow-up 2 to claim'
    c.execute("UPDATE visits SET claimed=? WHERE patient_id=? AND kind='followup2'", (str(today),p['id']))
    assert lifecycle.stage(c,p)['stage'] == 'done'
    p = patient('confirmed',call_list=1,visit_date=str(today-dt.timedelta(days=1)),referral_date=str(today-dt.timedelta(days=91)),folder='on Excel')
    assert {'needs_call','visit_passed','referral_expired','no_folder'} <= set(lifecycle.flags(c,p))
    assert lifecycle.next_step(c,p) == 'record the visit'
    p = update(p,state='offered',visit_time='00:00',referral_date=str(today-dt.timedelta(days=89)),folder='folder')
    assert {'offer_passed','referral_expiring'} <= set(lifecycle.flags(c,p)) and 'no_folder' not in lifecycle.flags(c,p)
    assert lifecycle.next_step(c,p) == 'offer a new time'
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('reply',?,'in','hello','OTHER','received',?)",(p['id'],str(now)))
    assert lifecycle.next_step(c,p) == 'read reply'
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('sent',?,'out','ok','reply','Sent',?)",(p['id'],str(now)))
    assert 'reply_waiting' in lifecycle.flags(c,p)
    # a reply stamped with an offset still waits when the last SMS (plain local time) went out before it
    c.execute("UPDATE messages SET created_at=? WHERE id='reply'",((now+dt.timedelta(hours=1)).astimezone().isoformat(),))
    assert 'reply_waiting' in lifecycle.flags(c,p)
    c.execute("UPDATE messages SET sent_at=? WHERE id='sent'",(str(now+dt.timedelta(hours=2))[:16],))
    assert 'reply_waiting' in lifecycle.flags(c,p)
    c.execute('DELETE FROM messages'); c.execute('DELETE FROM visits'); c.execute('DELETE FROM patients')
    groups = api.handle(c,'GET','/api/attention',{},None)[1]['groups']
    assert len(groups)==10 and all(not g['items'] for g in groups)
    booked = patient('confirmed',visit_date=str(today),visit_time='09:00')
    past = patient('confirmed',visit_date=str(today-dt.timedelta(days=1)))
    c.commit()
    assert lifecycle.auto_visit(c, today, dry_run=True)[0]['id'] == past['id']
    assert c.execute('SELECT state FROM patients WHERE id=?', (past['id'],)).fetchone()[0] == 'confirmed'
    assert lifecycle.auto_visit(c, today)[0]['notes'] is False
    offer = patient('offered',visit_date=str(today-dt.timedelta(days=1)),visit_time='09:00',referral_date=str(today-dt.timedelta(days=91)))
    patient('visited'); patient('sent'); follow = patient('claimed')
    c.execute("INSERT INTO visits(patient_id,kind,visit_date,source) VALUES (?,'hmr',?,'app')",(follow['id'],str(today-dt.timedelta(days=40))))
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('incoming',?,'in','hello','OTHER','received',?)",(offer['id'],str(now)))
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('draft',?,'out','hello','offer','draft',?)",(offer['id'],str(now)))
    c.execute("INSERT INTO tasks(id,patient_id,step,state,created) VALUES ('failed',?,'pathology','failed',?)",(booked['id'],str(now)))
    c.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('failed-message',?,'out','oops','offer','Failed',?)",(booked['id'],str(now)))
    c.execute("INSERT INTO meta(key,value) VALUES ('gateway_online','false')")
    patient('sent',is_test=1)
    groups = api.handle(c,'GET','/api/attention',{},None)[1]['groups']
    assert all(g['items'] for g in groups) and len(groups[6]['items'])==1
    assert len(groups[2]['items'])==2 and len(groups[4]['items'])==2
    assert {i['action'] for i in groups[9]['items']} == {'retry','open_messages','check_phone'}
    assert any(i['detail']=='Phone gateway offline' and i['patient_id'] is None for i in groups[9]['items'])
    check = groups[1]['items'][0]
    assert groups[1]['key'] == 'visits_to_check' and check['action'] == 'not_visited'
    past = c.execute('SELECT * FROM patients WHERE id=?', (past['id'],)).fetchone()
    api.action(c, past, {'action': 'not_visited'})
    corrected = c.execute('SELECT * FROM patients WHERE id=?', (past['id'],)).fetchone()
    assert corrected['state'] == 'pooled' and corrected['offered_date'] == str(today-dt.timedelta(days=1)) and corrected['visit_date'] is None
    visit = c.execute('SELECT * FROM visits WHERE patient_id=?', (past['id'],)).fetchone()
    assert visit['visit_date'] is None and visit['note'] == 'auto-recorded, did not happen'
    try: api.action(c, corrected, {'action': 'not_visited'}); assert False
    except ValueError: pass
    assert 'flags' in api.handle(c,'GET','/api/patients',{},None)[1]['patients'][0]
    assert 'stage_step' in api.handle(c,'GET',f"/api/patients/{booked['id']}",{},None)[1]
    # Notes, date boundary, test exclusion, and one backup for a multi-patient run.
    import json
    from unittest.mock import patch
    (folder/'interview.json').write_text(json.dumps({'notes': '  useful notes  '}), encoding='utf-8')
    noted = patient('sheet_ready', folder='folder', visit_date=str(today-dt.timedelta(days=2)))
    blank = patient('pathology_ready', visit_date=str(today-dt.timedelta(days=3)))
    patient('confirmed', visit_date=str(today), folder='folder')
    patient('confirmed', visit_date=str(today-dt.timedelta(days=1)), is_test=1)
    c.commit()
    with patch('lifecycle.db.backup', wraps=db.backup) as backup:
        result = lifecycle.auto_visit(c, today)
        assert backup.call_count == 1 and {x['id'] for x in result} == {noted['id'], blank['id']}
        assert next(x for x in result if x['id'] == noted['id'])['notes'] is True
        assert lifecycle.auto_visit(c, today) == [] and backup.call_count == 1
    event = json.loads(c.execute("SELECT detail FROM events WHERE patient_id=? AND type='visited'", (noted['id'],)).fetchone()[0])
    assert event['date'] == str(today-dt.timedelta(days=2)) and event['auto'] is True and event['notes'] is True
    assert any(x['patient_id'] == noted['id'] for x in lifecycle.attention(c, today)['groups'][1]['items'])
    # Archive visibility, suggestions, and read-only folder checks.
    done = patient('claimed'); assert 'archive_suggested' in lifecycle.flags(c, done)
    old = patient('declined')
    db.log(c, old['id'], 'state', {'from':'new','to':'declined'}, 'app')
    c.execute("UPDATE events SET ts=? WHERE id=(SELECT max(id) FROM events)", ((now-dt.timedelta(days=31)).isoformat(),))
    assert 'archive_suggested' in lifecycle.flags(c, old, today, now)
    recent = patient('expired'); db.log(c, recent['id'], 'state', {'from':'new','to':'expired'}, 'app')
    assert 'archive_suggested' not in lifecycle.flags(c, recent, today, now)
    for state, expected in [('new','Scheduled'), ('hold','Scheduled'), ('visited','Visited'), ('report_drafted','Visited'), ('signed_off','Visited'), ('sent','To CLAIM'), ('claimed','Completed & Claimed'), ('declined','Declined-Exp'), ('expired','Declined-Exp')]:
        (Path(tmp)/expected/'Example').mkdir(parents=True, exist_ok=True)
        p = patient(state, folder=str(Path(expected)/'Example'))
        assert lifecycle.folder_check(p) == {'actual':expected, 'expected':expected, 'ok':True}
    mismatch = patient('sent', folder='folder')
    assert lifecycle.folder_check(mismatch) == {'actual':'folder','expected':'To CLAIM','ok':False}
    assert 'folder_mismatch' in lifecycle.flags(c,mismatch)
    missing = patient('sent', folder='missing')
    assert lifecycle.folder_check(missing)['ok'] and 'folder_mismatch' not in lifecycle.flags(c,missing)
    api.action(c, done, {'action':'archive'}); done = c.execute('SELECT * FROM patients WHERE id=?',(done['id'],)).fetchone()
    assert lifecycle.stage(c,done)['stage'] == 'archived' and 'archived' in lifecycle.flags(c,done)
    assert 'archive_suggested' not in lifecycle.flags(c,done)
    listing = lambda query: api.handle(c,'GET','/api/patients',query,None)[1]['patients']
    assert done['id'] not in [x['id'] for x in listing({})]
    assert next(x for x in listing({'archived':'1'}) if x['id']==done['id'])['archived'] is True
    assert any(x['id']==done['id'] for x in listing({'q':done['name']}))
    assert not any(i['patient_id']==done['id'] for g in lifecycle.attention(c)['groups'] for i in g['items'])
    assert api.handle(c,'GET',f"/api/patients/{mismatch['id']}",{},None)[1]['folder_check']['ok'] is False
    c.close()
print('lifecycle self-check ok')

# Existing database migration preserves rows and is repeatable.
import sqlite3
with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp)/'old.db')
    old = sqlite3.connect(path); old.executescript(db.SCHEMA)
    old.execute("INSERT INTO patients(key,name) VALUES ('old','Old Patient')"); old.commit(); old.close()
    first = db.connect(path)
    assert {'archived_at','hold_from'} <= {r[1] for r in first.execute('PRAGMA table_info(patients)')}
    assert first.execute("SELECT name FROM patients WHERE key='old'").fetchone()[0] == 'Old Patient'
    first.close()
    second = db.connect(path)
    assert second.total_changes == 0 and second.execute('SELECT count(*) FROM patients').fetchone()[0] == 1
    second.close()
