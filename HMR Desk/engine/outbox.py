"""Durable SMS outbox. A missing status is the only reason to retry."""
import datetime
import os
import secrets
import sys
from urllib.parse import urlparse

import db

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'Android_SMS_Integration')))
from sms_bridge import (BridgeError, BridgeHTTPError, BridgeNetworkError, BridgeStorage,
                        SMSGateClient, get_active_state_dir, normalize_phone_number, verify_tailscale_peer)


def config():
    return BridgeStorage(get_active_state_dir()).load_config()


def make_client():
    store = BridgeStorage(get_active_state_dir())
    cfg = store.load_config()
    ok, reason = verify_tailscale_peer(urlparse(cfg['gateway_url']).hostname)
    if not ok:
        raise BridgeNetworkError('Tailscale peer unavailable')
    username, password = store.load_credentials()
    return SMSGateClient(cfg['gateway_url'], username, password)


def allowed_in_mode(conn, recipient):
    mode = conn.execute("SELECT value FROM meta WHERE key='outbox_mode'").fetchone()
    if mode and mode[0] != 'test':
        return mode[0] == 'live'
    try:
        return normalize_phone_number(recipient) == normalize_phone_number(config()['test_number'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def queue(conn, recipient, body, kind, patient_id=None, draft_id=None, commit=True):
    if not allowed_in_mode(conn, recipient):
        raise ValueError('Outbox is in test mode: only the test number can be sent')
    recipient = normalize_phone_number(recipient)
    if conn.execute("""SELECT 1 FROM messages WHERE direction='out' AND recipient=? AND body=?
       AND (state IN ('queued','submitting','unknown') OR datetime(sent_at)>=datetime('now','-1 day'))
       AND (? IS NULL OR patient_id=? OR NOT EXISTS (SELECT 1 FROM patients WHERE id=? AND is_test=1))""", (recipient, body, patient_id, patient_id, patient_id)).fetchone():
        raise ValueError('Duplicate message')
    id_ = draft_id or 'h' + secrets.token_hex(6)
    if draft_id:
        changed = conn.execute("UPDATE messages SET body=?,recipient=?,state='queued' WHERE id=? AND patient_id=? AND direction='out' AND state='draft'", (body, recipient, id_, patient_id)).rowcount
        if not changed: raise ValueError('message is not a draft')
    else:
        conn.execute("INSERT INTO messages (id,patient_id,direction,body,kind,state,recipient,created_at,source) VALUES (?,?,'out',?,?,'queued',?,?,'engine')", (id_, patient_id, body, kind, recipient, db.now()))
    db.log(conn, patient_id, 'message_queued', {'id': id_, 'kind': kind})
    if commit: conn.commit()
    return id_


def update(conn, row, state, detail=None):
    if state != row['state']:
        changed = conn.execute("UPDATE messages SET state=? WHERE id=? AND state=? AND state NOT IN ('Delivered','Failed')", (state, row['id'], row['state'])).rowcount
        if changed:
            db.log(conn, row['patient_id'], 'message_state', {'id': row['id'], 'state': state, 'code': detail})
        conn.commit()


def process(conn, client, config, now=None):
    changes = []
    def send(row):
        changed = conn.execute("UPDATE messages SET state='submitting' WHERE id=? AND state=?", (row['id'], row['state'])).rowcount
        conn.commit()
        if not changed:
            return
        try:
            result = client.send_message(row['id'], row['body'], row['recipient'], config['sim_number'])
            state = result.get('state') or result.get('status')
            if not state:
                raise BridgeError('Missing gateway state')
            conn.execute('UPDATE messages SET sent_at=? WHERE id=?', (db.now(), row['id']))
            update(conn, dict(row, state='submitting'), state)
        except BridgeNetworkError:
            state = 'unknown'
            update(conn, dict(row, state='submitting'), state)
        except BridgeHTTPError as e:
            state = 'Failed'
            update(conn, dict(row, state='submitting'), state, e.code)
        except BridgeError:
            state = 'unknown'
            update(conn, dict(row, state='submitting'), state)
        changes.append((row['id'], state))

    def eligible(row):
        if row['patient_id'] and row['patient_state'] in ('declined', 'expired'):
            return False
        window = conn.execute("SELECT value FROM meta WHERE key='sending_window'").fetchone()
        if (not window or window[0] != 'off') and not db.in_sending_window(row['postcode'], now):
            return False
        mode = conn.execute("SELECT value FROM meta WHERE key='outbox_mode'").fetchone()
        if not mode or mode[0] == 'test':
            try:
                return normalize_phone_number(row['recipient']) == normalize_phone_number(config['test_number'])
            except (ValueError, KeyError):
                return False
        return mode[0] == 'live'

    rows = conn.execute("""SELECT m.*,p.postcode,p.state AS patient_state FROM messages m LEFT JOIN patients p ON p.id=m.patient_id
          WHERE m.direction='out' AND m.state IN ('submitting','unknown','queued','Pending','Sent','Processed') ORDER BY m.created_at,m.rowid""").fetchall()
    for row in rows:
        if row['state'] not in ('submitting', 'unknown') or row['source'] != 'engine':
            continue
        try:
            result = client.get_message_status(row['id'])
            state = result.get('state') or result.get('status')
            if state:
                update(conn, row, state)
                changes.append((row['id'], state))
        except BridgeHTTPError as e:
            if e.code == 404 and eligible(row):
                send(row)
        except BridgeError:
            pass
    for row in rows:
        if row['state'] == 'queued' and row['source'] == 'engine' and eligible(row):
            send(row)
    for row in rows:
        if row['state'] in ('Pending', 'Sent', 'Processed'):
            try:
                result = client.get_message_status(row['id'])
                state = result.get('state') or result.get('status')
                if state:
                    update(conn, row, state)
                    changes.append((row['id'], state))
            except BridgeError:
                pass
    return changes
