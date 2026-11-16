"""Receive patient replies from polling and webhooks."""
import csv
import datetime
import os
import re

import db
import outbox
import proda_sms
import settings
from check_replies import classify as proven_classify  # the older pathway's rules, proven on real replies


YES = {'yes', 'yes please', 'yep', 'yeah', 'ok', 'okay', 'thats fine', 'that is fine',
       'sounds good', 'confirmed', 'confirm', 'see you then', 'that works', 'perfect', 'no problem', 'will do'}
DECLINE = {'decline', 'no thanks', 'no thank you', 'not interested', 'no longer needed',
           'no longer required', 'please cancel', 'no need', 'not to go ahead', 'not go ahead',
           'dont need it', 'dont need this', 'dont want it', 'dont want this',
           'dont want to do', 'dont want to have', 'dont want to go'}


def classify(text, patient_name='', pharmacist_name=''):
    if re.search(r'\?|\d|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
                 r'january|february|march|april|may|june|july|august|september|october|november|december|'
                 r'but|can|could|instead|change|another|later|earlier|call|phone|ring|today|tomorrow|tonight|morning|afternoon|evening|week|next|or)\b', text, re.I):
        return 'OTHER'
    proven = proven_classify(text)  # keep every clear match the older rules already made
    if proven != 'OTHER': return proven
    def clean(value):
        return ' '.join(re.sub(r"[^\w\s]", '', value.lower(), flags=re.UNICODE).replace('_', ' ').split())
    value = clean(text)
    names = set()
    for name in (patient_name, pharmacist_name):
        words = clean(name or '').split()
        if words and words[0] in ('mr', 'mrs', 'ms', 'miss', 'dr'):
            words = words[1:]
        if words:
            names.update((' '.join(words), words[0], words[-1]))
    # Try exact matches first: "no thanks" is a decline, not "no" plus a sign-off.
    while value:
        if value in YES: return 'YES'
        if value in DECLINE: return 'DECLINE'
        suffixes = names | {'thanks', 'thank you'}
        suffix = next((s for s in sorted(suffixes, key=len, reverse=True) if value.endswith(' ' + s)), None)
        if not suffix: break
        value = value[:-len(suffix)].strip()
    return 'OTHER'


def resolve(conn, message, data):
    choices = {'yes': 'YES', 'decline': 'DECLINE', 'new_time': 'NEW_TIME', 'call': 'CALL', 'done': 'HANDLED'}
    if not isinstance(data, dict) or set(data) != {'as'} or not isinstance(data['as'], str) or data['as'] not in choices:
        raise ValueError('invalid resolution')
    if message['direction'] != 'in' or message['kind'] != 'OTHER' or message['patient_id'] is None:
        raise ValueError('message is not an unresolved patient reply')
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (message['patient_id'],)).fetchone()
    if not patient: raise ValueError('patient not found')
    kind = choices[data['as']]
    if kind in ('YES', 'DECLINE'):
        timestamp = datetime.datetime.fromisoformat(message['created_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
        apply_reply(conn, patient, kind, message['body'], timestamp, 'app', message['offer_ref'], manual=True)
    elif kind == 'CALL':
        conn.execute('UPDATE patients SET call_list=1,updated_at=? WHERE id=?', (db.now(), patient['id']))
    conn.execute('UPDATE messages SET kind=? WHERE id=?', (kind, message['id']))
    if message['ai_draft_id']:
        conn.execute("UPDATE messages SET state='discarded' WHERE id=? AND direction='out' AND state='draft'", (message['ai_draft_id'],))
    db.log(conn, patient['id'], 'reply_resolved', {'id': message['id'], 'as': data['as']}, 'app')
    conn.commit()
    return dict(conn.execute('SELECT * FROM messages WHERE id=?', (message['id'],)).fetchone())


def digits(phone):
    return re.sub(r'\D', '', phone or '')[-9:]


def append_decline(patient, date, how, words):
    path = os.path.join(db.BASE, 'Declined-Exp', 'Declines register.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(['Patient', 'GP', 'Declined on', 'How', 'Their words', 'Notes'])
        writer.writerow([patient['name'], patient['gp'], str(date), how, ('TEST - ' + words) if patient['is_test'] else words, ('TEST ' + patient['key']) if patient['is_test'] else 'Added by HMR Desk engine'])


def already_have(conn, pid, text, timestamp):
    """True when this patient's reply is already stored (same text, within 2 minutes), whatever its id or source."""
    same = ' '.join(text.split())  # the old log stored replies on one line; pushed and polled copies differ in whitespace
    for row in conn.execute("SELECT created_at, body FROM messages WHERE direction='in' AND patient_id=?", (pid,)):
        if ' '.join((row[1] or '').split()) != same:
            continue
        try:
            prior = datetime.datetime.fromisoformat(row[0].replace('Z', '+00:00'))
            if prior.tzinfo is None:
                prior = prior.replace(tzinfo=datetime.timezone.utc)
            if abs((timestamp - prior).total_seconds()) <= 120:
                return True
        except ValueError:
            continue
    return False


def ingest(conn, msg_id, phone, text, received_at, source):
    if not msg_id or not phone or not isinstance(text, str) or not received_at or proda_sms.is_proda_code(phone, text):
        return None
    try:
        timestamp = datetime.datetime.fromisoformat(received_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    timestamp = timestamp.astimezone(datetime.timezone.utc)
    if conn.execute('SELECT 1 FROM messages WHERE id=?', (str(msg_id),)).fetchone():
        return None
    number = digits(phone)
    if len(number) != 9:
        return None
    matches = [p for p in conn.execute('SELECT * FROM patients WHERE phone IS NOT NULL') if digits(p['phone']) == number]
    shared = len(matches) > 1  # couples can share a number: keep the reply, never act on it automatically
    if shared:
        matches.sort(key=lambda p: conn.execute("SELECT COALESCE(MAX(created_at),'') FROM messages WHERE patient_id=? AND direction='out'", (p['id'],)).fetchone()[0], reverse=True)
    patient = matches[0] if matches else None
    if not patient:
        try:
            if number != digits(outbox.config().get('test_number')):
                return None
        except (OSError, ValueError, KeyError):
            return None
    pid = patient['id'] if patient else None
    if patient and already_have(conn, pid, text, timestamp):
        return None
    kind = ('OTHER' if shared else classify(text, patient['name'], settings.get(conn, 'pharmacist_name'))) if patient else 'test'
    offer = conn.execute("SELECT id FROM messages WHERE patient_id=? AND direction='out' AND kind IN ('offer','change','change_request','invitation') AND state NOT IN ('draft','discarded','Failed') ORDER BY created_at DESC,rowid DESC LIMIT 1", (pid,)).fetchone() if patient else None
    if patient and offer and kind == 'DECLINE' and conn.execute("SELECT 1 FROM messages WHERE id=? AND kind='change_request'", (offer[0],)).fetchone():
        kind = 'OTHER'
    if patient and patient['state'] in ('confirmed', 'pathology_ready', 'sheet_ready') and (kind == 'DECLINE' or re.search(r'\bcancel(?:led|ling)?\b', text, re.I)):
        kind = 'OTHER'
    conn.execute("INSERT INTO messages (id,patient_id,direction,body,kind,state,offer_ref,created_at,source) VALUES (?,?,'in',?,?,'received',?,?,?)", (str(msg_id), pid, text, kind, offer[0] if offer else None, timestamp.isoformat(), source))
    if patient:
        local = timestamp.astimezone(datetime.timezone(datetime.timedelta(hours=10)))
        reply = f"{local:%Y-%m-%d %H:%M}: {text}"
        conn.execute('UPDATE patients SET reply=?,updated_at=? WHERE id=?', (reply, db.now(), pid))
        db.log(conn, pid, 'reply_received', {'id': str(msg_id), 'kind': kind}, source)
        apply_reply(conn, patient, kind, text, timestamp, source, offer[0] if offer else None)
    conn.commit()
    return conn.execute('SELECT * FROM messages WHERE id=?', (str(msg_id),)).fetchone()


def apply_reply(conn, patient, kind, text, timestamp, source, offer_ref=None, manual=False):
    pid = patient['id']
    local = timestamp.astimezone(datetime.timezone(datetime.timedelta(hours=10)))
    proposal = conn.execute("SELECT * FROM messages WHERE id=? AND patient_id=? AND kind='change_request'", (offer_ref, pid)).fetchone()
    if manual and kind == 'DECLINE':
        db.set_state(conn, pid, 'declined', 'Declined by manual reply resolution', source)
        conn.execute('UPDATE patients SET offered_date=COALESCE(visit_date,offered_date),visit_date=NULL,visit_time=NULL,visit_end=NULL,visit_group=NULL WHERE id=?', (pid,))
        append_decline(patient, local.date(), 'SMS', text)
        return
    if proposal:
        if kind == 'YES' and patient['state'] in ('offered', 'confirmed', 'pathology_ready', 'sheet_ready'):
            conn.execute('UPDATE patients SET visit_date=?,visit_time=?,updated_at=? WHERE id=?', (proposal['visit_date'], proposal['visit_time'], db.now(), pid))
            db.set_state(conn, pid, 'confirmed' if patient['state'] == 'offered' else patient['state'], 'Confirmed by SMS reply', source)
        if kind == 'OTHER' and patient['state'] == 'offered':
            db.set_state(conn, pid, 'offered', 'Reply received - clarification needed', source)
        return
    if patient['state'] in ('confirmed', 'pathology_ready', 'sheet_ready') and re.search(r'\bcancel(?:led|ling)?\b', text, re.I):
        db.set_state(conn, pid, patient['state'], 'Confirmed - reply may be a cancellation, check it', source)
    elif kind == 'YES' and patient['state'] == 'offered' and patient['visit_date']:
        db.set_state(conn, pid, 'confirmed', 'Confirmed by SMS reply', source)
    elif kind == 'DECLINE' and patient['state'] in ('confirmed', 'pathology_ready', 'sheet_ready'):
        # a confirmed visit is never cancelled automatically; the wording keeps it visible on the dashboard
        db.set_state(conn, pid, patient['state'], 'Confirmed - reply may be a cancellation, check it', source)
    elif kind == 'DECLINE' and patient['state'] in ('new', 'pooled', 'offered'):
        db.set_state(conn, pid, 'declined', 'Declined by SMS reply', source)
        conn.execute('UPDATE patients SET offered_date=COALESCE(visit_date,offered_date),visit_date=NULL,visit_time=NULL,visit_end=NULL,visit_group=NULL WHERE id=?', (pid,))
        append_decline(patient, local.date(), 'SMS', text)
    elif kind == 'OTHER' and patient['state'] in ('confirmed', 'pathology_ready', 'sheet_ready') and classify(text, patient['name'], settings.get(conn, 'pharmacist_name')) == 'DECLINE':
        db.set_state(conn, pid, patient['state'], 'Confirmed - reply may be a cancellation, check it', source)
    elif kind == 'OTHER' and patient['state'] == 'offered':
        db.set_state(conn, pid, 'offered', 'Reply received - clarification needed', source)


def poll(conn, client):
    started = datetime.datetime.now(datetime.timezone.utc)
    row = conn.execute("SELECT value FROM meta WHERE key='inbox_since'").fetchone()
    fmt = '%Y-%m-%dT%H:%M:%SZ'  # the gateway expects UTC seconds with a Z suffix
    since = row[0] if row else (started - datetime.timedelta(days=1)).strftime(fmt)
    result, offset, limit = [], 0, 100
    while True:
        items, total = client.get_inbox_page(since, limit=limit, offset=offset)
        for item in items:
            if item.get('type', 'SMS') != 'SMS':
                continue
            row = ingest(conn, str(item.get('id') or ''), item.get('sender'), item.get('contentPreview'), item.get('createdAt'), 'poll')
            if row:
                result.append(row)
        offset += len(items)
        if not items or len(items) < limit or (total is not None and offset >= total):
            break
    since = (started - datetime.timedelta(minutes=10)).strftime(fmt)
    conn.execute("INSERT INTO meta VALUES ('inbox_since',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (since,))
    conn.commit()
    return result


def handle_webhook(conn, payload):
    event = payload.get('event')
    data = payload.get('payload')
    if not isinstance(data, dict):
        return 'ignored'
    if event == 'sms:received':
        return 'received' if ingest(conn, data.get('messageId'), data.get('sender') or data.get('phoneNumber'), data.get('message'), data.get('receivedAt'), 'webhook') else 'ignored'
    states = {'sms:sent': 'Sent', 'sms:delivered': 'Delivered', 'sms:failed': 'Failed'}
    if event in states:
        row = conn.execute("SELECT * FROM messages WHERE id=? AND direction='out'", (data.get('messageId'),)).fetchone()
        if row:
            outbox.update(conn, row, states[event])
            return 'updated'
    return 'ignored'
