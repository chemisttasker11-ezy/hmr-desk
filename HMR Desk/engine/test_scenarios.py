import datetime as dt
import json
import os
import tempfile
from unittest.mock import patch
import api, db, inbox, messaging, outbox, scenarios, settings

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    conn = db.connect(os.path.join(tmp, 'db.sqlite'))
    # The product has no default pharmacist name or phone (messages refuse to render without them), so the fixture sets both.
    settings.update(conn, {'pharmacist_name': 'Consultant Pharmacist', 'pharmacist_phone': '0400000000'})
    # Autopilot now defaults to 'ask' (drafts for approval, nothing auto-sends; commit db0a5bb). These scenarios assert the
    # automatic path, so the fixture opts in explicitly; every send here goes to the test number or a fake client.
    settings.update(conn, {'auto_confirmation': 'auto', 'auto_thanks_decline': 'auto', 'auto_follow_up': 'auto'})
    outbox.config = lambda: {'test_number': '0412345678', 'sim_number': 1}
    def fake_claude(prompt):
        intent = 'new_time' if 'Tuesday at 2pm' in prompt else 'question'
        return json.dumps({'intent': intent, 'proposed': None, 'summary': 'Needs review', 'confidence': 0.9, 'suggested_reply': 'Thank you, I will check.'})
    sent = []
    class FakeClient:
        def send_message(self, *args):
            sent.append(args[0])
            return {'state': 'Sent'}
        def get_message_status(self, *args): return {'state': 'Delivered'}
    with patch('replies.run_claude', side_effect=fake_claude):
        for name in scenarios.REPLIES:
            status, result = api.handle(conn, 'POST', '/api/test/scenario', {}, {'scenario': name, 'mode': 'simulated'})
            assert status == 200 and result['passed'], (name, result)
        assert conn.execute('SELECT count(*) FROM patients WHERE is_test=1 AND phone IS NOT NULL').fetchone()[0] == 1
        assert api.handle(conn, 'GET', '/api/status', {}, None)[1]['patients'] == {}
        assert api.handle(conn, 'GET', '/api/status', {}, None)[1]['messages'] == {}
        assert not api.handle(conn, 'GET', '/api/today', {}, None)[1]['visits']
        assert not api.handle(conn, 'GET', '/api/days', {'from': str(dt.date.today()), 'to': str(dt.date.today()+dt.timedelta(days=2))}, None)[1]
        assert len(api.handle(conn, 'GET', '/api/patients', {}, None)[1]['patients']) == 0  # test patients stay out of the list
        assert all('TEST' in (r['status_text'] or '') for r in conn.execute('SELECT status_text FROM patients'))
        status, run = api.handle(conn, 'POST', '/api/test/scenario', {}, {'scenario': 'yes', 'mode': 'real'})
        assert status == 200
        assert api.handle(conn, 'GET', '/api/test/scenario/' + run['run_id'], {}, None)[1]['status'] == 'waiting for your reply'
        outbox.process(conn, FakeClient(), outbox.config(), dt.datetime.now().replace(hour=10))
        assert sent and all(conn.execute('SELECT source FROM messages WHERE id=?', (id_,)).fetchone()[0] == 'engine' for id_ in sent)
        inbox.ingest(conn, 'real-reply', '0412345678', 'YES', dt.datetime.now(dt.timezone.utc).isoformat(), 'webhook')
        messaging.autopilot(conn, runner=fake_claude, patient_id=run['patient_id'])
        assert api.handle(conn, 'GET', '/api/test/scenario/' + run['run_id'], {}, None)[1]['passed']
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('outbox_mode','live')")
        assert api.handle(conn, 'POST', '/api/test/scenario', {}, {'scenario': 'yes', 'mode': 'simulated'})[0] == 400
    conn.close()
print('scenario checks passed')
