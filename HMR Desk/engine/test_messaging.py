import datetime as dt
import os
import tempfile
from unittest.mock import patch
import api, db, inbox, messaging, outbox


def call(conn, method, path, body=None):
    return api.handle(conn, method, path, {}, body or {})


with tempfile.TemporaryDirectory() as tmp:
    outbox.config = lambda: {'test_number': '0412345678'}
    conn = db.connect(os.path.join(tmp, 'test.db'))
    conn.execute("INSERT INTO patients(key,name,phone,address,postcode,gp,state,visit_date,visit_time) VALUES ('a','Mrs Jane Smith','0412345678','1 Main St','2486','Dr John Jones','pooled','2026-11-11','10:30')")
    conn.execute("INSERT INTO patients(key,name,phone,address,postcode,gp,state,visit_date,visit_time,call_list) VALUES ('b','John Brown','0412345679','2 Main St','4216','Jones','confirmed','2026-11-11','10:30',1)")
    conn.commit()
    a = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    b = conn.execute('SELECT * FROM patients WHERE id=2').fetchone()
    when = dt.datetime(2026, 11, 11, 10, 30)
    short = 'Kind regards,\nConsultant Pharmacist, Consultant Pharmacist\n'
    offer = "Dear Mrs Jane Smith,\n\nAs part of your health assessment plan, Dr John Jones has referred you for a Home Medicines Review. I will visit you at home to go through your medicines with you, and then send a report to Dr Jones. The review is covered by Medicare, so there is no cost to you. It takes about 20 to 30 minutes.\n\nYour appointment is on Wednesday 11 November at 11:30 am, at 1 Main St.\n\nPlease reply YES to confirm. If the time does not suit you, reply with a better day or time. If you would prefer not to go ahead, reply DECLINE and I will let Dr Jones know.\n\nKind regards,\nConsultant Pharmacist\nCredentialed Consultant Pharmacist\n"
    assert messaging.render(conn, a, 'offer', when) == offer
    follow = messaging.render(conn, a, 'follow_up', when)
    assert follow == f'Dear Mrs Jane Smith, I am following up my message about the Home Medicines Review that Dr Jones referred you for. Your appointment is on Wednesday 11 November at 11:30 am.\n\n{short}'
    assert 'Reply YES' not in follow
    assert messaging.render(conn, a, 'confirmation') == f'Dear Mrs Jane Smith, thank you. Your Home Medicines Review is confirmed for Wednesday 11 November at 11:30 am at your home. I will send you a reminder the day before. Please have all your medicines nearby, including vitamins, creams, puffers and eye drops.\n\n{short}'
    assert messaging.render(conn, a, 'thanks_decline') == 'Dear Mrs Jane Smith, thank you for letting me know. I will let Dr Jones know. If you change your mind, you are welcome to reply to this message.\n\nKind regards,\nConsultant Pharmacist'
    assert messaging.render(conn, a, 'reminder') == 'Dear Mrs Jane Smith, this is a reminder of your Home Medicines Review tomorrow, Wednesday 11 November, at 11:30 am. Please have your medicines nearby. If anything has changed, please let me know.\n\nKind regards,\nConsultant Pharmacist\n'
    assert messaging.render(conn, b, 'offer', when).startswith('Dear John Brown,') and '10:30 am' in messaging.render(conn, b, 'offer', when)
    conn.execute("UPDATE patients SET gp='Dr.  Samir   Ibrahim' WHERE id=1")
    mapped = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert 'Dr Samir   Ibrahim at Harbourtown Day/Night Surgery has referred you' in messaging.render(conn, mapped, 'offer', when)
    assert conn.execute('SELECT clinic FROM patients WHERE id=1').fetchone()[0] == 'Harbourtown Day/Night Surgery'
    changes = conn.total_changes
    assert messaging.clinic(conn, mapped) == 'Harbourtown Day/Night Surgery'
    assert conn.total_changes == changes
    conn.execute("UPDATE patients SET clinic='Existing Clinic' WHERE id=1")
    assert messaging.clinic(conn, mapped) == 'Existing Clinic'
    assert conn.execute('SELECT clinic FROM patients WHERE id=1').fetchone()[0] == 'Existing Clinic'
    current = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert 'at Existing Clinic has referred you' in messaging.render(conn, current, 'offer', when)
    assert call(conn, 'POST', '/api/patients/2/messages', {'kind':'offer', 'date':'2026-11-11', 'time':'08:00'})[0] == 400
    status, draft = call(conn, 'POST', '/api/patients/1/messages', {'kind':'offer','date':'2026-11-11','time':'10:30'})
    assert status == 200 and draft['state'] == 'draft'
    class Fake:
        def send_message(self, *args): raise AssertionError('draft was sent')
        def get_message_status(self, *args): raise AssertionError('draft was checked')
    outbox.process(conn, Fake(), {'test_number': '0412345678', 'sim_number': 1}, when)
    status, queued = call(conn, 'POST', f"/api/messages/{draft['id']}/approve", {'body':'Edited offer'})
    assert status == 200 and queued['state'] == 'queued' and queued['id'] == draft['id'] and queued['body'] == 'Edited offer'
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time']) == ('offered','2026-11-11','10:30')
    assert conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    _, duplicate = call(conn, 'POST', '/api/patients/1/messages', {'kind':'offer','date':'2026-11-11','time':'10:30','body':'Edited offer'})
    assert call(conn, 'POST', f"/api/messages/{duplicate['id']}/approve")[0] == 400
    assert conn.execute('SELECT state FROM messages WHERE id=?', (duplicate['id'],)).fetchone()[0] == 'draft'
    assert call(conn, 'POST', f"/api/messages/{duplicate['id']}/discard")[1]['state'] == 'discarded'
    call(conn, 'POST', '/api/patients/2/messages', {'kind':'thanks_decline'})
    conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES ('reply',1,'in','Please call','OTHER','received','2026-11-11T00:00:00+00:00')")
    conn.commit()
    conn.execute("UPDATE patients SET visit_date='2099-11-11' WHERE id=2")
    status, board = call(conn, 'GET', '/api/messages/board')
    assert status == 200 and board['outbox_mode'] == 'test'
    assert {r['kind'] for r in board['needs_you']} == {'OTHER','thanks_decline','call_list'}
    assert board['waiting'][0]['patient_id'] == 1 and board['upcoming'][0]['patient_id'] == 2 and not board['upcoming'][0]['reminder_sent']
    assert len(board['recent']) == 3 and all(r['state'] != 'draft' for r in board['recent'])
    conn.execute("UPDATE patients SET visit_date='2000-01-01' WHERE id=2")
    assert not any(x['patient_id'] == 2 for x in messaging.board(conn)['upcoming'])
    conn.execute("UPDATE patients SET visit_date='2099-11-11' WHERE id=2")
    conn.execute("UPDATE messages SET state='Sent',sent_at='2026-11-12T00:00:00+00:00' WHERE id=?", (draft['id'],))
    _, board = call(conn, 'GET', '/api/messages/board')
    assert any(r['kind'] == 'OTHER' for r in board['needs_you'])
    assert call(conn, 'GET', '/api/patients/1')[1]['suggested_kind'] == 'change'
    conn.execute("INSERT INTO patients(key,name,state) VALUES ('no-visit','No Visit','new')")
    assert call(conn, 'GET', '/api/patients/3')[1]['suggested_kind'] == 'offer'
    assert call(conn, 'POST', '/api/patients/1/messages', {'kind':'change'})[0] == 400
    assert call(conn, 'POST', '/api/patients/1/messages', {'kind':'change','date':'2026-11-16','time':'07:00'})[0] == 400
    status, change = call(conn, 'POST', '/api/patients/1/messages', {'kind':'change','date':'2026-11-16','time':'10:30'})
    assert status == 200
    assert change['body'] == "Hi Jane, unfortunately I have to change our appointment on Wednesday 11 November at 11:30 am due to unforeseen circumstances, and I'm sorry for the inconvenience. Would 11:30 am on Monday 16 November suit you instead? If so, just reply YES. If not, let me know a day or time that works better for you.\n\nKind regards,\nConsultant Pharmacist\nCredentialed Consultant Pharmacist\n"
    conn.execute("UPDATE patients SET state='confirmed' WHERE id=1")
    assert call(conn, 'POST', f"/api/messages/{change['id']}/approve")[0] == 200
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time'], p['offered_date']) == ('offered','2026-11-16','10:30','2026-11-16')
    assert call(conn, 'GET', '/api/messages/board')[1]['waiting'][0]['id'] == change['id']
    reply = inbox.ingest(conn, 'change-yes', '0412345678', 'YES', dt.datetime.now(dt.timezone.utc).isoformat(), 'test')
    assert reply['offer_ref'] == change['id']
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time']) == ('confirmed','2026-11-16','10:30')
    assert call(conn, 'GET', '/api/patients/1')[1]['change_kinds'] == ['change_request', 'change']
    conn.execute("INSERT OR IGNORE INTO patients(key,name,state) VALUES ('no-visit','No Visit','new')")
    conn.commit()
    assert call(conn, 'GET', '/api/patients/3')[1]['change_kinds'] == []
    status, missing = call(conn, 'POST', '/api/patients/3/messages', {'kind':'change_request','date':'2026-11-16','time':'10:30'})
    assert status == 400 and 'use offer instead' in missing['error']
    class FixedDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 10, 12, tzinfo=tz)
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    with patch('messaging.dt.datetime', FixedDateTime):
        assert messaging.render(conn, p, 'change_request', FixedDateTime(2026, 11, 16, 12, 0)) == 'Hi Jane, would 1:00 pm on Monday 16 November suit you instead of 11:30 am? It would help with my schedule, but no worries at all if 11:30 am is better for you.\n\nKind regards,\nConsultant Pharmacist, '
        assert messaging.render(conn, p, 'change_request', FixedDateTime(2026, 11, 18, 10, 0)) == 'Hi Jane, would 11:00 am on Wednesday 18 November suit you instead of 11:30 am on Monday 16 November? It would help with my schedule, but no worries at all if the original time is better for you.\n\nKind regards,\nConsultant Pharmacist, '
        assert '11:00 am tomorrow, Wednesday 11 November' in messaging.render(conn, p, 'change_request', FixedDateTime(2026, 11, 11, 10, 0))
    status, request = call(conn, 'POST', '/api/patients/1/messages', {'kind':'change_request','date':'2026-11-18','time':'10:00'})
    assert status == 200 and call(conn, 'POST', f"/api/messages/{request['id']}/approve")[0] == 200
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time']) == ('confirmed','2026-11-16','10:30')
    assert any(x['id'] == request['id'] for x in messaging.board(conn)['waiting'])
    reply = inbox.ingest(conn, 'request-no', '0412345678', 'NO', (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3)).isoformat(), 'test')
    assert reply['offer_ref'] == request['id']
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time']) == ('confirmed','2026-11-16','10:30')
    assert not any(x.get('id') == request['id'] for x in messaging.board(conn)['waiting'])
    reply = inbox.ingest(conn, 'request-yes', '0412345678', 'YES', (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=180)).isoformat(), 'test')
    assert reply['offer_ref'] == request['id']
    p = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert (p['state'], p['visit_date'], p['visit_time']) == ('confirmed','2026-11-18','10:00')
    conn.close()
print('messaging checks passed')




# "Check messages now": phone unreachable gives a clear error; success polls and runs the autopilot
def _check_now_tests():
    import tempfile, os, sqlite3
    from unittest.mock import patch
    import messaging, outbox
    tmp = tempfile.mkdtemp()
    conn = sqlite3.connect(os.path.join(tmp, 'c.db')); conn.row_factory = sqlite3.Row
    with patch('outbox.make_client', side_effect=outbox.BridgeError('Tailscale peer unavailable')):
        try: messaging.check_now(conn); assert False
        except ValueError as e: assert 'Phone not reachable' in str(e)
    with patch('outbox.make_client', return_value=object()), patch('outbox.config', return_value={}), \
         patch('outbox.process') as proc, patch('inbox.poll', return_value=[{'id': 'a'}, {'id': 'b'}]), patch('messaging.autopilot') as auto:
        result = messaging.check_now(conn)
        assert result['new_replies'] == 2 and proc.called and auto.called
    conn.close()
    print('check_now checks passed')
_check_now_tests()
