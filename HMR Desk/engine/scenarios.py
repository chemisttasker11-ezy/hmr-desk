"""Test-phone messaging scenarios, persisted so real runs can be checked later."""
import datetime as dt
import json
import secrets
import csv
import os

import db
import inbox
import messaging
import outbox

REPLIES = {'yes': ['YES'], 'decline': ['DECLINE'],
           'new_time': ['Could you come Tuesday at 2pm instead?'],
           'question': ['Who is this please?'], 'silence': [],
           'cancel_after_confirm': ['YES', 'Sorry I need to cancel']}


def patient(conn):
    number = outbox.config().get('test_number')
    if len(inbox.digits(number)) != 9:
        raise ValueError('Configure a valid test number first')
    if any(inbox.digits(p['phone']) == inbox.digits(number) for p in conn.execute('SELECT phone FROM patients WHERE is_test=0 AND phone IS NOT NULL')):
        raise ValueError('Test number belongs to a real patient')
    conn.execute("UPDATE messages SET state='discarded' WHERE state='queued' AND patient_id IN (SELECT id FROM patients WHERE is_test=1)")
    conn.execute('UPDATE patients SET phone=NULL WHERE is_test=1 AND phone IS NOT NULL')
    key = 'test-' + dt.datetime.now().strftime('%Y%m%d%H%M%S%f') + '-' + secrets.token_hex(3)
    cur = conn.execute("INSERT INTO patients(key,name,phone,address,suburb,postcode,gp,is_test,status_text,updated_at) VALUES (?,?,?,?,?,?,?,1,'TEST - new',?)", (key, 'Tess Tester', number, 'Runaway Bay', 'Runaway Bay', '4216', 'Dr Test Doctor', db.now()))
    conn.commit()
    return dict(conn.execute('SELECT * FROM patients WHERE id=?', (cur.lastrowid,)).fetchone())


def start(conn, data, runner=None):
    if not isinstance(data, dict) or set(data) != {'scenario', 'mode'} or data['scenario'] not in REPLIES or data['mode'] not in ('real', 'simulated'):
        raise ValueError('Invalid scenario or mode')
    mode = conn.execute("SELECT value FROM meta WHERE key='outbox_mode'").fetchone()
    if mode and mode[0] != 'test':
        raise ValueError('Scenarios require test outbox mode')
    p = patient(conn)
    now = dt.datetime.now().replace(microsecond=0)
    conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('autopilot_since',?)", ((now - dt.timedelta(seconds=1)).isoformat(),))
    offer = messaging.draft(conn, p, {'kind': 'offer', 'date': str(now.date() + dt.timedelta(days=1)), 'time': '10:30'})
    # simulated = the patient's reply is simulated; outgoing SMS still go to the tester phone (test mode allows only it)
    messaging.approve(conn, conn.execute('SELECT * FROM messages WHERE id=?', (offer['id'],)).fetchone(), {})
    run = secrets.token_hex(12)
    conn.execute('INSERT INTO meta(key,value) VALUES (?,?)', ('scenario:' + run, json.dumps({'patient_id': p['id'], 'scenario': data['scenario'], 'mode': data['mode']})))
    conn.commit()
    if data['mode'] == 'real':
        return {'run_id': run, 'patient_id': p['id'], 'status': 'waiting for your reply'}
    conn.execute("UPDATE messages SET state='Sent',sent_at=?,source='simulated' WHERE id=?", (now.isoformat(), offer['id']))
    conn.commit()
    for i, text in enumerate(REPLIES[data['scenario']]):
        at = (now + dt.timedelta(seconds=i + 1)).replace(tzinfo=dt.timezone(dt.timedelta(hours=10)))
        inbox.ingest(conn, 'sim-' + secrets.token_hex(12), p['phone'], text, at.isoformat(), 'simulated')
        messaging.autopilot(conn, at, runner, p['id'])
    if data['scenario'] == 'silence':
        messaging.autopilot(conn, now + dt.timedelta(hours=25), runner, p['id'], simulated=True)
        # Simulate gateway delivery so the second escalation exercises the normal sent-message rule.
        conn.execute("UPDATE messages SET state='Sent',sent_at=created_at,source='simulated' WHERE patient_id=? AND kind='follow_up' AND state='queued'", (p['id'],))
        conn.commit()
        messaging.autopilot(conn, now + dt.timedelta(hours=49), runner, p['id'], simulated=True)
    return report(conn, run)


def report(conn, run):
    row = conn.execute('SELECT value FROM meta WHERE key=?', ('scenario:' + run,)).fetchone()
    if not row: return None
    info = json.loads(row[0]); pid = info['patient_id']; scenario = info['scenario']
    p = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
    messages = [dict(m) for m in conn.execute('SELECT * FROM messages WHERE patient_id=? ORDER BY rowid', (pid,))]
    incoming = [m for m in messages if m['direction'] == 'in']
    def outgoing(kind, states): return any(m['direction'] == 'out' and m['kind'] == kind and m['state'] in states for m in messages)
    steps = []
    def check(label, ok, detail): steps.append({'step': label, 'ok': bool(ok), 'detail': detail})
    check('offer queued', outgoing('offer', ('queued', 'submitting', 'unknown', 'Pending', 'Sent', 'Processed', 'Delivered')), 'Offer queued or sent')
    if scenario == 'yes':
        check('confirmed', p['state'] == 'confirmed', p['status_text'])
        check('confirmation queued', outgoing('confirmation', ('queued','submitting','Pending','Sent','Processed','Delivered')), 'Confirmation queued or sent')
    elif scenario == 'decline':
        check('declined', p['state'] == 'declined', p['status_text'])
        check('thanks queued', outgoing('thanks_decline', ('queued','submitting','Pending','Sent','Processed','Delivered')), 'Decline thanks queued or sent')
        path = os.path.join(db.BASE, 'Declined-Exp', 'Declines register.csv')
        marked = False
        if os.path.exists(path):
            with open(path, encoding='utf-8-sig', newline='') as f:
                marked = any(r.get('Notes') == 'TEST ' + p['key'] and r.get('Patient') == p['name'] and 'TEST' in (r.get('Their words') or '') and any(m['body'] in r['Their words'] for m in incoming) for r in csv.DictReader(f))
        check('register marked TEST', marked, 'Decline register contains a TEST reason')
    elif scenario in ('new_time', 'question'):
        needs = messaging.board(conn, include_test=True)['needs_you']
        check('reply needs review', any(m.get('patient_id') == pid and any(i.get('id') == m.get('id') for i in incoming) for m in needs) or any(m['kind'] != 'OTHER' for m in incoming), 'Reply is awaiting review or has been resolved')
    elif scenario == 'silence':
        check('follow-up', outgoing('follow_up', ('queued','submitting','Pending','Sent','Processed','Delivered')), 'Follow-up queued or sent')
        check('call list', p['call_list'], 'Patient on call list')
    else:
        check('confirmation queued', outgoing('confirmation', ('queued','submitting','Pending','Sent','Processed','Delivered')), 'Confirmation queued or sent')
        check('cancellation flagged', p['state'] == 'confirmed' and 'may be a cancellation' in (p['status_text'] or ''), p['status_text'])
    passed = all(s['ok'] for s in steps)
    waiting = info['mode'] == 'real' and not passed and (not incoming or scenario == 'cancel_after_confirm' and len(incoming) < 2 or scenario == 'silence')
    return {'run_id': run, 'scenario': scenario, 'patient_id': pid, 'steps': steps, 'messages': messages, 'passed': passed, 'status': 'waiting for your reply' if waiting else 'passed' if passed else 'failed'}
