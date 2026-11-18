"""SMS drafts and the communication board. Times supplied to the engine are Queensland time."""
import datetime as dt
import secrets
import logging
import os
import json
import re
import threading
from pathlib import Path

import db
import outbox
import settings
import inbox
import replies

KINDS = ('offer', 'change', 'change_request', 'follow_up', 'confirmation', 'thanks_decline', 'reminder', 'custom')


def required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} is required')
    return value.strip()


def visit_time(patient, when=None):
    if when is None:
        try:
            when = dt.datetime.fromisoformat(required(patient['visit_date'], 'visit date') + 'T' + required(patient['visit_time'], 'visit time'))
        except (TypeError, ValueError) as exc:
            raise ValueError('valid visit date and time are required') from exc
    if not isinstance(when, dt.datetime) or when.tzinfo is not None:
        raise ValueError('visit time must be a naive Queensland datetime')
    postcode = required(patient['postcode'], 'postcode')
    local = when + dt.timedelta(hours=db.utc_offset_hours(postcode, when) - 10)
    if local.time() <= dt.time(8):
        raise ValueError('start must be after 08:00 in patient local time')
    return local


def clinic(conn, patient):
    if patient['clinic'] and patient['clinic'].strip(): return patient['clinic'].strip()
    gp = re.sub(r'^dr\.?\s+', '', ' '.join((patient['gp'] or '').lower().split()))
    clinics = json.loads(Path(__file__).with_name('clinics.json').read_text(encoding='utf-8'))
    found = clinics.get(gp, '')
    if found:
        conn.execute("UPDATE patients SET clinic=? WHERE id=? AND (clinic IS NULL OR trim(clinic)='')", (found, patient['id']))
        return conn.execute('SELECT clinic FROM patients WHERE id=?', (patient['id'],)).fetchone()['clinic']
    return ''


def render(conn, patient, kind, when=None):
    if kind not in KINDS or kind == 'custom': raise ValueError('invalid message kind')
    name = required(patient['name'], 'patient name')
    pharmacist = required(settings.get(conn, 'pharmacist_name'), 'pharmacist name')
    phone = required(settings.get(conn, 'pharmacist_phone'), 'pharmacist phone')
    credential = required(settings.get(conn, 'pharmacist_credential'), 'pharmacist credential')
    short = f'Kind regards,\n{pharmacist}, {credential.removeprefix("Credentialed ")}\n{phone}'
    gp = None
    if kind in ('offer', 'follow_up', 'thanks_decline'):
        gp_full = required(patient['gp'], 'GP').strip()
        if gp_full.lower().startswith(('dr ', 'dr. ')): gp_full = gp_full.split(' ', 1)[1].strip()
        gp = gp_full.split()[-1]
        if gp.rstrip('.').lower() == 'dr': raise ValueError('GP family name is required')
    if kind != 'thanks_decline':
        local = visit_time(patient, when if kind in ('offer', 'change', 'change_request', 'follow_up') else None)
        day = f'{local:%A} {local.day} {local:%B}'
        time = f'{local.hour % 12 or 12}:{local:%M} {"am" if local.hour < 12 else "pm"}'
    if kind == 'offer':
        address = required(patient['address'], 'address')
        practice = clinic(conn, patient)
        at_clinic = f' at {practice}' if practice else ''
        return (f'Dear {name},\n\nAs part of your health assessment plan, Dr {gp_full}{at_clinic} has referred you for a Home Medicines Review. I will visit you at home to go through your medicines with you, and then send a report to Dr {gp}. The review is covered by Medicare, so there is no cost to you. It takes about 20 to 30 minutes.\n\n'
                f'Your appointment is on {day} at {time}, at {address}.\n\n'
                f'Please reply YES to confirm. If the time does not suit you, reply with a better day or time. If you would prefer not to go ahead, reply DECLINE and I will let Dr {gp} know.\n\nKind regards,\n{pharmacist}\n{credential}\n{phone}')
    if kind in ('change', 'change_request'):
        old = visit_time(patient)
        old_time = f'{old.hour % 12 or 12}:{old:%M} {"am" if old.hour < 12 else "pm"}'
        old_day = f'{old:%A} {old.day} {old:%B}'
        first = re.sub(r'^(mr|mrs|ms|miss|dr)\.?\s+', '', name, flags=re.I).split()[0]
    if kind == 'change_request':
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=10))).replace(tzinfo=None)
        today = (now + dt.timedelta(hours=db.utc_offset_hours(patient['postcode'], now) - 10)).date()
        prefix = 'tomorrow, ' if local.date() == today + dt.timedelta(days=1) else ''
        instead = old_time if old.date() == local.date() else f'{old_time} on {old_day}'
        better = old_time if old.date() == local.date() else 'the original time'
        return (f'Hi {first}, would {time} {"tomorrow, " if prefix else "on "}{day}{"," if prefix else ""} suit you instead of {instead}? '
                f'It would help with my schedule, but no worries at all if {better} is better for you.\n\nKind regards,\n{pharmacist}, {phone}')
    if kind == 'change':
        return (f"Hi {first}, unfortunately I have to change our appointment on {old_day} at {old_time} due to unforeseen circumstances, and I'm sorry for the inconvenience. "
                f'Would {time} on {day} suit you instead? If so, just reply YES. If not, let me know a day or time that works better for you.\n\nKind regards,\n{pharmacist}\n{credential}\n{phone}')
    if kind == 'follow_up':
        return f'Dear {name}, I am following up my message about the Home Medicines Review that Dr {gp} referred you for. Your appointment is on {day} at {time}.\n\n{short}'
    if kind == 'confirmation':
        return f'Dear {name}, thank you. Your Home Medicines Review is confirmed for {day} at {time} at your home. I will send you a reminder the day before. Please have all your medicines nearby, including vitamins, creams, puffers and eye drops.\n\n{short}'
    if kind == 'thanks_decline':
        return f'Dear {name}, thank you for letting me know. I will let Dr {gp} know. If you change your mind, you are welcome to reply to this message.\n\nKind regards,\n{pharmacist}'
    return f'Dear {name}, this is a reminder of your Home Medicines Review tomorrow, {day}, at {time}. Please have your medicines nearby. If anything has changed, please let me know.\n\nKind regards,\n{pharmacist}\n{phone}'


def expired_warning(conn, patient, today=None):
    import api
    expiry = api.referral_expiry(conn, patient['referral_date'])
    return 'Referral expired on ' + expiry.strftime('%d/%m/%Y') if expiry and expiry < (today or dt.date.today()) else ''

def draft(conn, patient, data, commit=True):
    if not isinstance(data, dict) or set(data) - {'kind', 'date', 'time', 'body'}: raise ValueError('invalid body')
    kind = data.get('kind')
    if kind not in KINDS: raise ValueError('invalid message kind')
    when = None
    if kind == 'change_request' and (not patient['visit_date'] or not patient['visit_time']): raise ValueError('no current time; use offer instead')
    if kind == 'change_request': visit_time(patient)
    if kind in ('change', 'change_request') or 'date' in data or 'time' in data:
        if kind not in ('offer', 'change', 'change_request', 'follow_up'): raise ValueError('date and time are only for offers, changes and follow-ups')
        try: when = dt.datetime.fromisoformat(required(data.get('date'), 'date') + 'T' + required(data.get('time'), 'time'))
        except ValueError as exc: raise ValueError('valid date and time are required') from exc
    if when and (when.second or when.microsecond): raise ValueError('time must use whole minutes')
    if kind in ('offer', 'change', 'change_request', 'follow_up'):
        visit_time(patient, when)
        if when is None: when = dt.datetime.fromisoformat(patient['visit_date'] + 'T' + patient['visit_time'])
    body = required(data.get('body'), 'body') if kind == 'custom' else required(data['body'], 'body') if 'body' in data else render(conn, patient, kind, when)
    if kind in ('confirmation', 'reminder'):
        visit_time(patient)
        when = dt.datetime.fromisoformat(patient['visit_date'] + 'T' + patient['visit_time'])
    recipient = required(patient['phone'], 'patient phone')
    id_ = 'h' + secrets.token_hex(6)
    conn.execute("INSERT INTO messages(id,patient_id,direction,body,kind,state,recipient,created_at,source,visit_date,visit_time) VALUES (?,?,'out',?,?,'draft',?,?,'engine',?,?)", (id_, patient['id'], body, kind, recipient, db.now(), when.date().isoformat() if when else None, when.time().isoformat(timespec='minutes') if when else None))
    db.log(conn, patient['id'], 'message_drafted', {'id': id_, 'kind': kind})
    if commit: conn.commit()
    result = dict(conn.execute('SELECT * FROM messages WHERE id=?', (id_,)).fetchone())
    warning = expired_warning(conn, patient) if kind in ('offer', 'change', 'change_request', 'follow_up') else ''
    if warning: result['warning'] = warning
    return result


def approve(conn, row, data):
    if not isinstance(data, dict) or set(data) - {'body', 'confirm_expired'} or ('confirm_expired' in data and type(data['confirm_expired']) is not bool): raise ValueError('invalid body')
    if row['state'] != 'draft' or row['direction'] != 'out': raise ValueError('message is not a draft')
    if row['kind'] in ('offer', 'change', 'change_request', 'follow_up'):
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (row['patient_id'],)).fetchone()
        warning = expired_warning(conn, patient)
        if warning and data.get('confirm_expired') is not True: raise ValueError(warning)
    body = required(data['body'], 'body') if 'body' in data else row['body']
    if not outbox.allowed_in_mode(conn, row['recipient']):
        raise ValueError('Outbox is in test mode: only the test number can be sent')
    if row['kind'] == 'change_request':
        p = conn.execute('SELECT * FROM patients WHERE id=?', (row['patient_id'],)).fetchone()
        visit_time(p, dt.datetime.fromisoformat(row['visit_date'] + 'T' + row['visit_time']))
    if row['kind'] in ('offer', 'change'):
        p = conn.execute('SELECT * FROM patients WHERE id=?', (row['patient_id'],)).fetchone()
        visit_time(p, dt.datetime.fromisoformat(row['visit_date'] + 'T' + row['visit_time']))
        if p['state'] == 'new': db.set_state(conn, p['id'], 'pooled', source='app')
        db.set_state(conn, p['id'], 'offered', source='app')
        conn.execute('UPDATE patients SET visit_date=?,visit_time=?,offered_date=?,updated_at=? WHERE id=?', (row['visit_date'], row['visit_time'], row['visit_date'], db.now(), p['id']))
    outbox.queue(conn, row['recipient'], body, row['kind'], row['patient_id'], draft_id=row['id'], commit=False)
    conn.commit()
    return dict(conn.execute('SELECT * FROM messages WHERE id=?', (row['id'],)).fetchone())


def discard(conn, row):
    if row['state'] != 'draft' or row['direction'] != 'out': raise ValueError('message is not a draft')
    conn.execute("UPDATE messages SET state='discarded' WHERE id=? AND state='draft'", (row['id'],))
    db.log(conn, row['patient_id'], 'message_discarded', {'id': row['id']})
    conn.commit()
    return dict(conn.execute('SELECT * FROM messages WHERE id=?', (row['id'],)).fetchone())


# replies are stamped with an offset, sent SMS with plain local time: compare both as local time
_LOCAL = "CASE WHEN {0} LIKE '%+__:__' OR {0} LIKE '%Z' THEN datetime({0},'localtime') ELSE datetime({0}) END"


def waiting_replies(conn, patient_id=None):
    return list(conn.execute(f"""SELECT m.* FROM messages m WHERE m.direction='in' AND m.kind='OTHER'
        AND NOT EXISTS (SELECT 1 FROM patients p WHERE p.id=m.patient_id AND p.archived_at IS NOT NULL)
        AND (? IS NULL OR m.patient_id=?) AND NOT EXISTS (SELECT 1 FROM messages o
        WHERE o.patient_id=m.patient_id AND o.direction='out' AND (o.id=m.ai_draft_id OR o.offer_ref=m.id)
        AND (o.sent_at IS NOT NULL OR o.state IN ('Sent','Delivered','Processed'))
        AND {_LOCAL.format('COALESCE(o.sent_at,o.created_at)')} >= {_LOCAL.format('m.created_at')})
        ORDER BY m.created_at DESC,m.rowid DESC""", (patient_id, patient_id)))


def recent_needs(conn, select, include_test):
    return [dict(r) for r in conn.execute(select + " WHERE p.archived_at IS NULL AND (? OR COALESCE(p.is_test,0)=0) AND (m.state='draft' OR (m.direction='in' AND m.kind='OTHER')) ORDER BY m.created_at DESC,m.rowid DESC", (include_test,))]


def board(conn, include_test=False):
    select = "SELECT m.*,p.name,p.phone FROM messages m LEFT JOIN patients p ON p.id=m.patient_id"
    recent = [dict(r) for r in conn.execute(select + " WHERE p.archived_at IS NULL AND (? OR COALESCE(p.is_test,0)=0) AND m.state != 'draft' ORDER BY m.created_at DESC,m.rowid DESC LIMIT 50", (include_test,))]
    reply_ids = {r['id'] for r in waiting_replies(conn)}
    needs = [r for r in recent_needs(conn, select, include_test) if r['state'] == 'draft' or r['id'] in reply_ids]
    linked = {r['ai_draft_id']: r['id'] for r in conn.execute("SELECT id,ai_draft_id FROM messages WHERE direction='in' AND ai_draft_id IS NOT NULL")}
    for item in needs:
        if item['state'] == 'draft' and item['id'] in linked:
            item['answers_message_id'] = linked[item['id']]
    needs = [item for item in needs if item.get('answers_message_id') not in reply_ids]
    for item in recent + needs:
        if item.get('source') == 'autopilot_test_hold' and item['state'] == 'draft':
            item['hold_reason'] = 'held - test mode'
    for p in conn.execute('SELECT * FROM patients WHERE archived_at IS NULL AND call_list=1 AND (? OR is_test=0)', (include_test,)):
        needs.append({'patient_id': p['id'], 'name': p['name'], 'phone': p['phone'], 'kind': 'call_list', 'body': p['note'], 'created_at': p['updated_at'], 'sent_at': None})
    waiting = []
    for p in conn.execute("SELECT * FROM patients WHERE archived_at IS NULL AND (? OR is_test=0) AND state IN ('offered','confirmed','pathology_ready','sheet_ready')", (include_test,)):
        m = conn.execute("SELECT * FROM messages WHERE patient_id=? AND direction='out' AND kind IN ('offer','change','change_request','invitation') AND state NOT IN ('draft','discarded') ORDER BY created_at DESC,rowid DESC LIMIT 1", (p['id'],)).fetchone()
        if p['state'] != 'offered' and (not m or m['kind'] != 'change_request' or conn.execute("SELECT 1 FROM messages WHERE direction='in' AND offer_ref=? LIMIT 1", (m['id'],)).fetchone()): continue
        item = dict(m) if m else {'kind': 'offer', 'body': None, 'created_at': None, 'sent_at': None}
        item.update(patient_id=p['id'], name=p['name'], phone=p['phone'], visit_date=p['visit_date'], visit_time=p['visit_time'])
        stamp = (m['sent_at'] or m['created_at']) if m else None
        item['seconds_since_offer'] = max(0, int((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stamp.replace('Z', '+00:00')).replace(tzinfo=dt.datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo or dt.timezone.utc)).total_seconds())) if stamp else None
        waiting.append(item)
    upcoming = []
    for p in conn.execute("SELECT * FROM patients WHERE archived_at IS NULL AND state IN ('confirmed','pathology_ready','sheet_ready') AND visit_date >= ? ORDER BY visit_date,visit_time", (dt.datetime.now(dt.timezone(dt.timedelta(hours=10))).date().isoformat(),)):
        m = conn.execute("SELECT * FROM messages WHERE patient_id=? AND kind='reminder' AND direction='out' AND (sent_at IS NOT NULL OR state IN ('Sent','Delivered','Processed')) AND (visit_date IS NULL OR visit_date=?) ORDER BY created_at DESC LIMIT 1", (p['id'], p['visit_date'])).fetchone()
        item = dict(m) if m else {'kind': 'reminder', 'body': None, 'created_at': None, 'sent_at': None}
        item.update(patient_id=p['id'], name=p['name'], phone=p['phone'], visit_date=p['visit_date'], visit_time=p['visit_time'], reminder_sent=bool(m))
        upcoming.append(item)
    mode = conn.execute("SELECT value FROM meta WHERE key='outbox_mode'").fetchone()
    return {'needs_you': needs, 'waiting': waiting, 'upcoming': upcoming, 'recent': recent, 'outbox_mode': mode[0] if mode else 'test'}


_autopilot_lock = threading.Lock()  # the service loop and the "Check now" button must not read the same reply twice


def autopilot(conn, now=None, runner=None, patient_id=None, simulated=False):
    with _autopilot_lock:
        return _autopilot(conn, now, runner, patient_id, simulated)


def check_now(conn):
    """Send queued SMS, fetch new replies from the phone and read them now (the "Check messages now" button)."""
    try:
        client = outbox.make_client()
        outbox.process(conn, client, outbox.config())
        new = inbox.poll(conn, client)
    except (outbox.BridgeError, OSError, KeyError) as exc:
        raise ValueError('Phone not reachable - check Tailscale and the SMS gateway app (' + str(exc) + ')') from None
    autopilot(conn)
    return {'new_replies': len(new), 'checked_at': db.now()}


def _autopilot(conn, now=None, runner=None, patient_id=None, simulated=False):
    """Apply messaging rules; naive clocks and stored naive timestamps are Queensland time."""
    if settings.get(conn, 'autopilot_paused'):
        return
    now = now or dt.datetime.now()
    qld = dt.timezone(dt.timedelta(hours=10))
    if now.tzinfo is None: now = now.replace(tzinfo=qld)
    now = now.astimezone(qld)
    delay = dt.timedelta(hours=settings.get(conn, 'follow_up_after_hours'))
    since = conn.execute("SELECT value FROM meta WHERE key='autopilot_since'").fetchone()
    if not since:  # first run: act only on what happens from now on, never on older history
        conn.execute("INSERT INTO meta (key,value) VALUES ('autopilot_since',?)", (now.isoformat(),)); conn.commit()
        since = (now.isoformat(),)

    def timestamp(value):
        t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (t if t.tzinfo else t.replace(tzinfo=qld)).astimezone(qld)

    def stamp(row):
        return timestamp(row['sent_at'] or row['created_at'])

    def create(patient, kind):
        mode = settings.get(conn, 'auto_' + kind)
        if mode == 'off': return
        held = mode == 'auto' and not outbox.allowed_in_mode(conn, patient['phone'])
        message = draft(conn, patient, {'kind': kind})
        conn.execute('UPDATE messages SET created_at=?,source=? WHERE id=?',
                     (now.isoformat(), 'autopilot_test_hold' if held else 'simulated' if simulated else 'engine', message['id']))
        if mode == 'auto' and not held:
            outbox.queue(conn, message['recipient'], message['body'], kind, patient['id'], draft_id=message['id'], commit=False)
        db.log(conn, patient['id'], 'autopilot', {'kind': kind, 'id': message['id'], 'mode': mode})
        conn.commit()

    mode = settings.get(conn, 'ai_reply_reading')
    if mode != 'off':
        unread = conn.execute("SELECT * FROM messages WHERE direction='in' AND kind='OTHER' AND patient_id IS NOT NULL AND ai_summary IS NULL ORDER BY rowid").fetchall()
        unread = [m for m in unread if (patient_id is None or m['patient_id'] == patient_id) and timestamp(m['created_at']) >= timestamp(since[0])]  # never read replies from before the autopilot started
        for message in unread:
            try:
                result = replies.read_reply(conn, message, runner)
                patient = conn.execute('SELECT * FROM patients WHERE id=?', (message['patient_id'],)).fetchone()
                shared = sum(inbox.digits(p['phone']) == inbox.digits(patient['phone']) for p in conn.execute('SELECT phone FROM patients WHERE phone IS NOT NULL')) > 1
                latest = conn.execute("SELECT id FROM messages WHERE patient_id=? AND direction='in' ORDER BY created_at DESC,rowid DESC LIMIT 1", (patient['id'],)).fetchone()
                automatic = mode == 'auto' and not (result['intent'] == 'decline' and message['offer_ref'] and conn.execute("SELECT 1 FROM messages WHERE id=? AND kind='change_request'", (message['offer_ref'],)).fetchone()) and not (patient['state'] in ('confirmed','pathology_ready','sheet_ready') and result['intent'] == 'decline') and not shared and latest['id'] == message['id'] and result['intent'] in ('yes', 'decline') and result['confidence'] >= 0.85
                conn.execute('UPDATE messages SET ai_intent=?,ai_summary=?,ai_confidence=?,ai_reply=? WHERE id=?', (result['intent'], result['summary'], result['confidence'], result['suggested_reply'], message['id']))
                if automatic:
                    kind = result['intent'].upper()
                    inbox.apply_reply(conn, patient, kind, message['body'], timestamp(message['created_at']), message['source'], message['offer_ref'])
                    conn.execute('UPDATE messages SET kind=? WHERE id=?', (kind, message['id']))
                    conn.commit()
                else:
                    made = draft(conn, patient, {'kind': 'custom', 'body': result['suggested_reply']}, commit=False)
                    conn.execute('UPDATE messages SET ai_draft_id=? WHERE id=?', (made['id'], message['id']))
                    conn.commit()
            except Exception:
                conn.rollback()
                conn.execute("UPDATE messages SET ai_summary='Could not read - check by eye' WHERE id=?", (message['id'],))
                conn.commit()
                logging.exception('Reply reading failed')

    for patient in conn.execute("SELECT * FROM patients WHERE state IN ('declined','offered','confirmed','pathology_ready','sheet_ready') AND (? IS NULL OR id=?)", (patient_id, patient_id)).fetchall():
        try:
            rows = conn.execute('SELECT * FROM messages WHERE patient_id=? ORDER BY rowid', (patient['id'],)).fetchall()
            rows = [r for r in rows if stamp(r) >= timestamp(since[0])]
            incoming = [r for r in rows if r['direction'] == 'in']
            outgoing = [r for r in rows if r['direction'] == 'out']
            latest_reply = max(incoming, key=stamp, default=None)
            if patient['state'] == 'declined' and latest_reply and latest_reply['kind'] == 'DECLINE':
                if not conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='folder_suggestion'", (patient['id'],)).fetchone():
                    db.log(conn, patient['id'], 'folder_suggestion', {'to': 'Declined-Exp\\Declined'})
                    conn.commit()
                if not any(r['kind'] == 'thanks_decline' and stamp(r) >= stamp(latest_reply) for r in outgoing):
                    create(patient, 'thanks_decline')
            elif patient['state'] in ('confirmed', 'pathology_ready', 'sheet_ready'):
                if latest_reply and latest_reply['kind'] == 'YES' and not any(r['kind'] == 'confirmation' and stamp(r) >= stamp(latest_reply) for r in outgoing):
                    create(patient, 'confirmation')
                if not (patient['postcode'] or '').strip():
                    # Reminder timing needs the patient's postcode; without it nothing is drafted and nothing is guessed.
                    if patient['visit_date'] and not conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='autopilot_skipped_no_postcode'", (patient['id'],)).fetchone():
                        db.log(conn, patient['id'], 'autopilot_skipped_no_postcode', {})
                        conn.commit()
                    continue
                local = now.replace(tzinfo=None) + dt.timedelta(hours=db.utc_offset_hours(patient['postcode'], now) - 10)
                if patient['visit_date'] and visit_time(patient).date() == local.date() + dt.timedelta(days=1) and local.hour >= settings.get(conn, 'reminder_from_hour') and db.in_sending_window(patient['postcode'], now.replace(tzinfo=None)):
                    if not any(r['kind'] == 'reminder' and r['visit_date'] == patient['visit_date'] for r in outgoing):
                        create(patient, 'reminder')
            elif patient['state'] == 'offered':
                if settings.get(conn, 'auto_follow_up') == 'off': continue
                offers = [r for r in outgoing if r['kind'] in ('offer', 'change', 'change_request', 'invitation') and r['state'] not in ('draft', 'discarded')]
                offer = max(offers, key=stamp, default=None)
                if not offer or offer['kind'] == 'change_request' or (latest_reply and stamp(latest_reply) >= stamp(offer)) or now - stamp(offer) < delay:
                    continue
                follows = [r for r in outgoing if r['kind'] == 'follow_up' and stamp(r) >= stamp(offer)]
                if not follows:
                    if expired_warning(conn, patient, now.date()):
                        if not conn.execute("SELECT 1 FROM events WHERE patient_id=? AND type='autopilot_skipped_expired'", (patient['id'],)).fetchone():
                            db.log(conn, patient['id'], 'autopilot_skipped_expired', {})
                            conn.commit()
                        continue
                    create(patient, 'follow_up')
                else:
                    follow = max(follows, key=stamp)
                    if (follow['sent_at'] or follow['state'] in ('Sent', 'Delivered', 'Processed')) and now - stamp(follow) >= delay and not patient['call_list']:
                        conn.execute('UPDATE patients SET call_list=1,updated_at=? WHERE id=?', (now.isoformat(), patient['id']))
                        db.log(conn, patient['id'], 'autopilot_call_list', {'follow_up': follow['id']})
                        conn.commit()
        except Exception:
            conn.rollback()
            logging.exception('Autopilot failed for patient %s', patient['id'])
