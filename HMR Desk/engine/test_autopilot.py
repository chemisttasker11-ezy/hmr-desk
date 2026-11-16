import datetime as dt
import json
import os
import tempfile
from unittest.mock import patch
import db, messaging, outbox, settings

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    conn = db.connect(os.path.join(tmp, 'db.sqlite'))
    # Owner preference: messages are drafted for approval; nothing sends itself until a kind is switched to auto.
    assert all(settings.get(conn, 'auto_' + k) == 'ask' for k in ('confirmation', 'thanks_decline', 'follow_up', 'reminder'))
    settings.update(conn, {'ai_reply_reading': 'off', 'auto_confirmation': 'auto', 'auto_thanks_decline': 'auto', 'auto_follow_up': 'auto', 'auto_reminder': 'auto'})
    outbox.config = lambda: {'test_number': '0412345678'}
    now = dt.datetime(2026, 11, 11, 15)
    def patient(key, state, phone='0412345678', postcode='4216', visit='2026-11-15', folder=None):
        conn.execute('INSERT INTO patients(key,name,phone,address,postcode,gp,state,visit_date,visit_time,folder) VALUES (?,?,?,?,?,?,?,?,?,?)', (key, 'Jane '+key, phone, '1 Main St', postcode, 'Dr Samir Ibrahim', state, visit, '10:30', folder))
        return conn.execute('SELECT * FROM patients WHERE key=?', (key,)).fetchone()
    def msg(p, id_, direction, kind, at):
        conn.execute('INSERT INTO messages(id,patient_id,direction,body,kind,state,created_at) VALUES (?,?,?,?,?,?,?)', (id_, p['id'], direction, id_, kind, 'received' if direction == 'in' else 'Sent', at))
    def messages(p, kind):
        return conn.execute("SELECT * FROM messages WHERE patient_id=? AND direction='out' AND kind=?", (p['id'], kind)).fetchall()
    a = patient('yes', 'confirmed'); msg(a, 'yes', 'in', 'YES', '2026-11-11T03:00:00+00:00')
    os.mkdir(os.path.join(tmp, 'referral'))
    b = patient('decline', 'declined', visit=None, folder='referral'); msg(b, 'no', 'in', 'DECLINE', '2026-11-11T03:00:00+00:00')
    c = patient('offer', 'offered'); msg(c, 'offer', 'out', 'offer', '2026-11-10T14:00:00+10:00')
    q = patient('qld', 'confirmed', visit='2026-11-12')
    n = patient('nsw', 'confirmed', postcode='2486', visit='2026-11-12')
    held = patient('held', 'confirmed', '0412345679'); msg(held, 'heldyes', 'in', 'YES', '2026-11-11T03:00:00+00:00')
    old = patient('old', 'offered'); msg(old, 'history-offer', 'out', 'offer', '2026-10-01T14:00:00+10:00')
    conn.execute("INSERT INTO meta (key,value) VALUES ('autopilot_since','2026-11-01T00:00:00+10:00')")
    conn.commit()
    messaging.autopilot(conn, now); messaging.autopilot(conn, now)
    assert len(messages(a, 'confirmation')) == 1 and messages(a, 'confirmation')[0]['state'] == 'queued'
    assert len(messages(b, 'thanks_decline')) == 1 and os.path.isdir(os.path.join(tmp, 'referral'))
    suggestion = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='folder_suggestion'", (b['id'],)).fetchall()
    assert len(suggestion) == 1 and json.loads(suggestion[0][0]) == {'to': 'Declined-Exp\\Declined'}
    assert len(messages(c, 'follow_up')) == 1
    assert not messages(q, 'reminder') and len(messages(n, 'reminder')) == 1
    assert messages(held, 'confirmation')[0]['state'] == 'draft'
    assert any(x.get('hold_reason') == 'held - test mode' for x in messaging.board(conn)['needs_you'])
    try: messaging.approve(conn, messages(held, 'confirmation')[0], {})
    except ValueError as e: assert str(e) == 'Outbox is in test mode: only the test number can be sent'
    else: assert False
    try: outbox.queue(conn, '0412345679', 'test', 'test')
    except ValueError as e: assert 'test mode' in str(e)
    else: assert False
    conn.execute("UPDATE messages SET state='Sent',sent_at=? WHERE id=?", ((now - dt.timedelta(hours=25)).isoformat(), messages(c, 'follow_up')[0]['id']))
    messaging.autopilot(conn, now + dt.timedelta(hours=1)); messaging.autopilot(conn, now + dt.timedelta(hours=1))
    assert conn.execute('SELECT call_list FROM patients WHERE id=?', (c['id'],)).fetchone()[0] == 1
    assert len(messages(c, 'follow_up')) == 1 and len(messages(q, 'reminder')) == 1
    assert any(x['kind'] == 'call_list' and x['patient_id'] == c['id'] for x in messaging.board(conn)['needs_you'])
    assert 'Dr Samir Ibrahim' in messaging.render(conn, c, 'offer') and 'let Dr Ibrahim know' in messaging.render(conn, c, 'offer')
    settings.update(conn, {'auto_confirmation': 'ask', 'auto_reminder': 'off'})
    ask = patient('ask', 'confirmed'); msg(ask, 'askyes', 'in', 'YES', '2026-11-11T03:00:00+00:00')
    off = patient('off', 'confirmed', visit='2026-11-12')
    messaging.autopilot(conn, now + dt.timedelta(hours=1)); messaging.autopilot(conn, now + dt.timedelta(hours=1))
    assert len(messages(ask, 'confirmation')) == 1 and messages(ask, 'confirmation')[0]['state'] == 'draft'
    assert not messages(off, 'reminder')
    settings.update(conn, {'autopilot_paused': True, 'auto_confirmation': 'auto'})
    paused = patient('paused', 'confirmed'); msg(paused, 'pauseyes', 'in', 'YES', '2026-11-11T03:00:00+00:00')
    messaging.autopilot(conn, now); assert not messages(paused, 'confirmation')
    settings.update(conn, {'autopilot_paused': False, 'auto_confirmation': 'off'})
    messaging.autopilot(conn, now); assert not messages(paused, 'confirmation')
    # Held messages remain drafts after live mode is selected.
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('outbox_mode','live')")
    messaging.autopilot(conn, now)
    assert messages(held, 'confirmation')[0]['state'] == 'draft'
    # A reply after an offer stops follow-up, including a call-list escalation.
    reply = patient('reply', 'offered'); msg(reply, 'oldoffer', 'out', 'offer', '2026-11-09T12:00:00+10:00')
    msg(reply, 'replyin', 'in', 'OTHER', '2026-11-10T12:00:00+10:00')
    messaging.autopilot(conn, now)
    assert not messages(reply, 'follow_up')
    # A new change restarts the follow-up clock even if an older offer was answered.
    changed = patient('changed', 'offered')
    msg(changed, 'change-old', 'out', 'offer', '2026-11-09T12:00:00+10:00')
    msg(changed, 'change-reply', 'in', 'OTHER', '2026-11-10T12:00:00+10:00')
    msg(changed, 'change-new', 'out', 'change', '2026-11-11T14:00:00+10:00')
    messaging.autopilot(conn, now)
    assert not messages(changed, 'follow_up')
    messaging.autopilot(conn, now + dt.timedelta(hours=25))
    assert len(messages(changed, 'follow_up')) == 1
    # A soft request replaces the old proposal but never gets a follow-up.
    soft = patient('soft', 'offered')
    msg(soft, 'soft-old', 'out', 'offer', '2026-11-09T12:00:00+10:00')
    msg(soft, 'soft-new', 'out', 'change_request', '2026-11-10T12:00:00+10:00')
    assert next(x for x in messaging.board(conn)['waiting'] if x['patient_id'] == soft['id'])['id'] == 'soft-new'
    messaging.autopilot(conn, now + dt.timedelta(days=3))
    assert not messages(soft, 'follow_up') and not conn.execute('SELECT call_list FROM patients WHERE id=?', (soft['id'],)).fetchone()[0]
    # A failed move is recorded without preventing another patient's message.
    broken = patient('broken', 'declined', visit=None, folder='missing'); msg(broken, 'brokenreply', 'in', 'DECLINE', '2026-11-11T03:00:00+00:00')
    settings.update(conn, {'auto_confirmation': 'auto'})
    with patch('messaging.logging.exception'):
        messaging.autopilot(conn, now)
    assert conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='folder_suggestion'", (broken['id'],)).fetchone()
    assert len(messages(broken, 'thanks_decline')) == 1 and len(messages(paused, 'confirmation')) == 1
    events = [json.loads(r[0]) for r in conn.execute("SELECT detail FROM events WHERE type='autopilot'")]
    assert len(events) == len({e['id'] for e in events})
    assert all(conn.execute('SELECT 1 FROM messages WHERE id=? AND kind=?', (e['id'], e['kind'])).fetchone() for e in events)
    assert all(set(e) == {'kind','id','mode'} for e in events)
    assert not messages(old, 'follow_up') and not conn.execute('SELECT call_list FROM patients WHERE id=?', (old['id'],)).fetchone()[0]  # history before autopilot_since is ignored
    conn.close()
print('autopilot checks passed')
