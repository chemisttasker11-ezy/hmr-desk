import datetime as dt, json, os, tempfile
from unittest.mock import patch
import db, inbox, messaging, outbox, settings

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    conn = db.connect(os.path.join(tmp, 'db.sqlite'))
    outbox.config = lambda: {'test_number': '0412345678'}
    conn.execute("INSERT INTO meta VALUES ('autopilot_since','2026-01-01T00:00:00+10:00')")
    settings.update(conn, {'auto_reminder':'off', 'auto_follow_up':'off'})
    now = dt.datetime(2026, 11, 11, 15)
    seen = []
    def response(intent='question', confidence=0.9):
        def fake(prompt):
            seen.append(prompt)
            return json.dumps({'intent':intent, 'proposed':None, 'summary':'Patient replied', 'confidence':confidence, 'suggested_reply':'Thanks.\n\nKind regards,\nConsultant Pharmacist\nPh: '})
        return fake
    def add(n):
        phone = '04000000' + str(n).zfill(2)
        conn.execute("INSERT INTO patients(key,name,phone,address,suburb,postcode,gp,dob,medicare,state,visit_date,visit_time) VALUES (?,?,?,?,?,?,?,?,?,'offered','2026-11-20','10:30')", (str(n), 'Mrs Jane Smith', phone, '99 Secret Street', 'Southport', '4215', 'Dr John Jones', '1980-02-03', '1234567890'))
        p = conn.execute('SELECT * FROM patients WHERE key=?', (str(n),)).fetchone()
        conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at,visit_date,visit_time) VALUES (?,?,'out','offer','offer','Sent','2026-11-10T10:00:00+10:00','2026-11-20','10:30')", ('offer'+str(n), p['id']))
        conn.commit()
        inbox.ingest(conn, 'reply'+str(n), phone, 'Can you do it?', '2026-11-11T03:00:00Z', 'test')
    def row(n): return conn.execute('SELECT * FROM messages WHERE id=?', ('reply'+str(n),)).fetchone()
    add(1); messaging.autopilot(conn, now, response('yes'))
    a = row(1)
    assert a['ai_intent'] == 'yes' and a['ai_draft_id'] and conn.execute('SELECT state FROM patients WHERE id=?', (a['patient_id'],)).fetchone()[0] == 'offered'
    item = next(x for x in messaging.board(conn)['needs_you'] if x['id'] == a['id'])
    assert item['ai_draft_id'] == a['ai_draft_id'] and item['ai_confidence'] == .9
    prompt = seen[-1]
    assert all(secret not in prompt for secret in ('1980-02-03', '1234567890', '99 Secret Street', '0400000001'))
    assert all(x in prompt for x in ('Jane', 'Southport', 'Jones', 'Friday'))
    settings.update(conn, {'ai_reply_reading':'auto'})
    add(2); messaging.autopilot(conn, now, response('yes', .9))
    b = row(2)
    assert b['kind'] == 'YES' and conn.execute('SELECT state FROM patients WHERE id=?', (b['patient_id'],)).fetchone()[0] == 'confirmed'
    assert conn.execute("SELECT state FROM messages WHERE patient_id=? AND kind='confirmation'", (b['patient_id'],)).fetchone()[0] == 'draft'
    add(3); messaging.autopilot(conn, now, response('yes', .84))
    assert row(3)['kind'] == 'OTHER' and row(3)['ai_draft_id']
    add(4)
    with patch('messaging.logging.exception'): messaging.autopilot(conn, now, lambda prompt: 'bad JSON')
    assert row(4)['ai_summary'] == 'Could not read - check by eye' and not row(4)['ai_draft_id']
    count = len(seen); messaging.autopilot(conn, now, response()); assert len(seen) == count
    add(5); messaging.autopilot(conn, now, response('decline', .95))
    assert row(5)['kind'] == 'DECLINE' and conn.execute('SELECT state FROM patients WHERE id=?', (row(5)['patient_id'],)).fetchone()[0] == 'declined'
    assert conn.execute("SELECT 1 FROM messages WHERE patient_id=? AND kind='thanks_decline'", (row(5)['patient_id'],)).fetchone()
    assert os.path.isfile(os.path.join(tmp, 'Declined-Exp', 'Declines register.csv'))
    settings.update(conn, {'ai_reply_reading':'off'})
    add(6); count = len(seen); messaging.autopilot(conn, now, response()); assert len(seen) == count and row(6)['ai_summary'] is None
    settings.update(conn, {'ai_reply_reading':'auto'})
    conn.execute("INSERT INTO patients(key,name,phone,state) VALUES ('shared','Other Person','0400000006','new')")
    messaging.autopilot(conn, now, response('yes', .99))
    assert row(6)['kind'] == 'OTHER' and row(6)['ai_draft_id']
    conn.close()
print('reply checks passed')

# Whole-message rules, including sign-offs and phrases that must stay for review.
cases = {
    'YES': ['yes', 'Yes please!', 'yep', 'yeah', 'OK', 'okay', "that’s fine", 'that is fine',
            'sounds good', 'confirmed', 'confirm', 'see you then', 'that works', 'perfect',
            'no problem', 'will do', 'Yes, thanks 😊', 'Yes, thank you, Jane Smith', 'yes Consultant',
            'Yes thank you Consultant, that will be fine', 'Hi yes please'],  # the older pathway's prefix rule still applies
    'DECLINE': ['decline', 'no thanks', 'no thank you', 'not interested', 'no longer needed',
                'no longer required', 'please cancel', 'not to go ahead', 'no need', 'decline, thank you'],
    'OTHER': ['yes but no', 'yes?', 'yes 2', 'yes Monday', 'yes January', 'yes can you',
              'yes could you', 'yes instead', 'yes change', 'yes another', 'yes later', 'yes earlier',
              'yes please call', 'no', 'no problem but later', 'decline please call', 'yes tomorrow',
              'not sure', 'yes or no', 'please phone me', 'ok tomorrow morning'],
}
for expected, texts in cases.items():
    for text in texts:
        assert inbox.classify(text, 'Mrs Jane Smith', 'Consultant Pharmacist') == expected, text


def resolution_tests():
    import api, lifecycle
    with tempfile.TemporaryDirectory() as tmp:
        db.BASE = tmp
        conn = db.connect(os.path.join(tmp, 'test.db'))
        settings.update(conn, {'ai_reply_reading': 'off', 'auto_confirmation': 'ask', 'auto_thanks_decline': 'ask',
                               'auto_reminder': 'off', 'auto_follow_up': 'off'})
        conn.execute("INSERT INTO meta VALUES ('autopilot_since','2026-01-01T00:00:00+10:00')")
        outbox.config = lambda: {'test_number': '0412345678'}
        for i, action in enumerate(('yes', 'decline', 'new_time', 'call', 'done'), 1):
            phone = '04000000' + str(i).zfill(2)
            conn.execute("INSERT INTO patients(key,name,phone,address,postcode,gp,state,visit_date,visit_time) VALUES (?,?,?,?,?,?,'offered','2099-11-20','10:30')", (str(i), 'Jane Smith', phone, '1 Main St', '4215', 'Dr John Jones'))
            pid = conn.execute('SELECT id FROM patients WHERE key=?', (str(i),)).fetchone()[0]
            conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES (?,?,'out','draft','custom','draft','2026-11-11T03:00:00Z')", ('draft'+str(i), pid))
            inbox.ingest(conn, 'in'+str(i), phone, 'Can you call?', '2026-11-11T03:00:00Z', 'test')
            conn.execute('UPDATE messages SET ai_draft_id=?,ai_summary=?,ai_intent=? WHERE id=?', ('draft'+str(i), 'summary', 'question', 'in'+str(i)))
            conn.commit()
            board = messaging.board(conn)
            item = next(x for x in board['needs_you'] if x.get('id') == 'in'+str(i))
            assert (item['ai_summary'], item['ai_intent'], item['ai_draft_id']) == ('summary', 'question', 'draft'+str(i))
            assert not any(x.get('id') == 'draft'+str(i) for x in board['needs_you'])
            assert not any(x['state'] == 'draft' for x in board['recent'])
            assert 'reply_waiting' in lifecycle.flags(conn, conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone())
            status, result = api.handle(conn, 'POST', '/api/messages/in'+str(i)+'/resolve', {}, {'as': action})
            assert status == 200 and result['kind'] == {'yes':'YES', 'decline':'DECLINE', 'new_time':'NEW_TIME', 'call':'CALL', 'done':'HANDLED'}[action]
            assert conn.execute('SELECT state FROM messages WHERE id=?', ('draft'+str(i),)).fetchone()[0] == 'discarded'
            patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
            assert patient['state'] == {'yes':'confirmed', 'decline':'declined'}.get(action, 'offered')
            assert patient['call_list'] == (1 if action == 'call' else 0)
            assert 'reply_waiting' not in lifecycle.flags(conn, patient)
            event = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='reply_resolved'", (pid,)).fetchone()
            assert json.loads(event[0]) == {'id':'in'+str(i), 'as':action}
            assert api.handle(conn, 'POST', '/api/messages/in'+str(i)+'/resolve', {}, {'as':action})[0] == 400
            assert api.handle(conn, 'POST', '/api/messages/draft'+str(i)+'/resolve', {}, {'as':'done'})[0] == 400
        assert api.handle(conn, 'POST', '/api/messages/in1/resolve', {}, {'as':[]})[0] == 400
        with patch('replies.read_reply', side_effect=AssertionError('AI called')):
            messaging.autopilot(conn, dt.datetime(2026, 11, 11, 15))
        assert conn.execute("SELECT state FROM messages WHERE patient_id=1 AND kind='confirmation'").fetchone()[0] == 'draft'
        assert conn.execute("SELECT state FROM messages WHERE patient_id=2 AND kind='thanks_decline'").fetchone()[0] == 'draft'
        assert not conn.execute("SELECT 1 FROM messages WHERE patient_id IN (3,4,5) AND kind IN ('confirmation','thanks_decline')").fetchone()
        conn.close()
resolution_tests()
print('resolution checks passed')
