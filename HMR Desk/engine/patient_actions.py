"""Patient actions: the booking, visit, report and claim state machine (moved verbatim from api.py).

action() is the entry point; _action() holds the transitions. Does not import api.
"""
import datetime as dt
import json
import os
import re

import db
import inbox
import jobs
import records
import settings
import steps
from followup_schedule import meta, patient_followups


def folder(p):
    return os.path.abspath(os.path.join(db.BASE, p['folder'])) if p['folder'] else None


def move_patient_item(conn, p, destination, moved_items):
    source = folder(p)
    if not source:
        raise ValueError('patient folder missing')
    target_dir = os.path.join(db.BASE, 'Declined-Exp', destination)
    target = os.path.join(target_dir, os.path.basename(source))
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        return False
    if os.path.lexists(target):
        raise ValueError('target already exists')
    if not os.path.exists(source):
        raise ValueError('patient folder source missing: ' + source)
    try:
        os.makedirs(target_dir, exist_ok=True)
        os.rename(source, target)
    except OSError as exc:
        raise ValueError('patient folder move failed: ' + str(exc)) from exc
    try:
        conn.execute('UPDATE patients SET folder=?,updated_at=? WHERE id=?',
                     (os.path.relpath(target, db.BASE), db.now(), p['id']))
    except Exception:
        os.rename(target, source)
        raise
    moved_items.append((source, target))
    return True


def files(path):
    def names(p):
        return sorted(x for x in os.listdir(p) if os.path.isfile(os.path.join(p, x))) if p and os.path.isdir(p) else []
    return {'folder': names(path), 'pathology': names(os.path.join(path, 'Pathology') if path else None)}


def date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid date')
    return dt.date.fromisoformat(value)


def anydate(value):
    """Stored referral dates and DOBs are DD/MM/YYYY (sometimes with a trailing note); newer ones may be ISO."""
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', value or '')
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else date((value or '')[:10])


def referral_expiry(conn, value):
    try:
        days = int(meta(conn, 'referral_valid_days', 90))
        if days <= 0: days = 90
        return anydate(value) + dt.timedelta(days=days)
    except (ValueError, TypeError, OverflowError):
        return None


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('invalid time')
    return dt.time.fromisoformat(value)



def undo_event(conn, p):
    event = conn.execute("SELECT * FROM events WHERE patient_id=? AND type='state' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
    if not event or event['source'] != 'app': return None
    try:
        age = dt.datetime.now() - dt.datetime.fromisoformat(event['ts'])
        detail = json.loads(event['detail'] or '{}')
        if (dt.timedelta(0) <= age < dt.timedelta(hours=24) and detail.get('to') == p['state']
                and detail.get('to') in ('visited', 'report_drafted', 'signed_off', 'sent', 'claimed')
                and detail.get('from') in db.STATES and detail['from'] != detail['to']):
            return detail
    except (ValueError, TypeError, AttributeError):
        pass
    return None

def action(conn, p, body):
    moved_items = []
    try:
        return _action(conn, p, body, moved_items)
    except Exception:
        conn.rollback()
        for source, target in reversed(moved_items):
            os.rename(target, source)
        raise


def _action(conn, p, body, moved_items):
    pid, name = p['id'], body.get('action')
    moved = False
    transitions = {'book_phone': 'confirmed', 'move': 'confirmed', 'decline_phone': 'declined', 'hold': 'hold',
                   'visited': 'visited', 'report_drafted': 'report_drafted', 'signed_off': 'signed_off',
                   'report_sent': 'sent', 'claimed': 'claimed', 'expired': 'expired'}
    if name in ('book_phone', 'move'):
        if name == 'move' and p['state'] not in ('confirmed', 'pathology_ready', 'sheet_ready'):
            raise ValueError('move needs a booked visit')
        date(body.get('date'))
        start, end = clock(body.get('time')), clock(body.get('end'))
        if start <= dt.time(8):
            raise ValueError('start must be after 08:00')
        if end <= start:
            raise ValueError('end must be after start')
    if name in ('visited', 'report_sent', 'claimed', 'followup_done', 'followup_claimed'):
        date(body.get('date'))
    if name in ('followup_done', 'followup_claimed') and body.get('kind') not in ('followup1', 'followup2'): raise ValueError('invalid follow-up kind')
    if name in transitions:
        target = p['state'] if name == 'move' and p['state'] in ('confirmed', 'pathology_ready', 'sheet_ready') else transitions[name]
        if name in ('decline_phone', 'hold', 'expired') and not isinstance(body.get('reason' if name == 'decline_phone' else 'note', ''), str):
            raise ValueError('reason or note must be a string')
        if name in ('decline_phone', 'expired'):
            if not db.can_move(p['state'], target):
                raise ValueError(f"{p['state']} -> {target} is not allowed")
            moved = move_patient_item(conn, p, 'Declined' if name == 'decline_phone' else 'Expired', moved_items)
        dated = {'visited': 'Visited', 'report_sent': 'Report sent', 'claimed': 'Claimed'}
        status = dated[name] + ' ' + dt.date.fromisoformat(body['date']).strftime('%d/%m/%Y') if name in dated else None
        if name == 'visited' and body.get('auto') is True: status += ' (auto)'
        authorisation = None
        if name == 'signed_off':
            import report_auth
            authorisation = report_auth.check_approval(conn, p, body)
        if name == 'report_sent':
            import report_auth
            report_auth.check_sent(conn, p)
        if name == 'signed_off' and p['state'] == 'visited' and steps.built(conn, p):
            db.set_state(conn, pid, 'report_drafted', source='app')
        db.set_state(conn, pid, target, status, source='app', force=name == 'book_phone' and p['state'] in ('new', 'pooled'))
        if name == 'visited':  # the list shows the real visit date, not the booked one
            conn.execute('UPDATE patients SET visit_date=?,updated_at=? WHERE id=?', (body['date'], db.now(), pid))
        if name in ('book_phone', 'move'):
            conn.execute('UPDATE patients SET visit_date=?,visit_time=?,visit_end=?,updated_at=? WHERE id=?',
                         (body['date'], body['time'], body['end'], db.now(), pid))
        if name == 'decline_phone':
            inbox.append_decline(p, dt.date.today(), 'Phone', body.get('reason', ''))
        if name in ('decline_phone', 'expired'):
            conn.execute('UPDATE patients SET offered_date=COALESCE(visit_date,offered_date),visit_date=NULL,visit_time=NULL,visit_end=NULL,visit_group=NULL WHERE id=?', (pid,))
        if name == 'expired' and 'note' in body:
            conn.execute('UPDATE patients SET note=?,updated_at=? WHERE id=?', (body['note'], db.now(), pid))
        if name == 'hold':
            conn.execute("UPDATE patients SET note=?,hold_from=CASE WHEN ? != 'hold' THEN ? ELSE hold_from END,updated_at=? WHERE id=?", (body.get('note', ''), p['state'], p['state'], db.now(), pid))
        if name in ('visited', 'report_sent', 'claimed'):
            row = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind='hmr' AND source='app' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
            if name == 'visited' and p['state'] != 'visited': row = None
            if not row:
                rowid = conn.execute("INSERT INTO visits(patient_id,kind,folder,source) VALUES (?,'hmr',?,'app')", (pid,p['folder'])).lastrowid
            else: rowid = row['id']
            field = {'visited':'visit_date','report_sent':'report_sent','claimed':'claimed'}[name]
            conn.execute('UPDATE visits SET '+field+'=? WHERE id=?', (body['date'],rowid))
        detail = {k: v for k, v in body.items() if k != 'action'}
        if authorisation is not None:
            detail = authorisation
        if name == 'visited': detail['prior_booking'] = {k: p[k] for k in ('visit_date','visit_time','visit_end','visit_group')}
        db.log(conn, pid, name, detail, 'app')
    elif name == 'pathology_outcome':
        if p['state'] not in (*steps.PRE, 'visited', 'report_drafted', 'signed_off'): raise ValueError('invalid patient state')
        outcome, note = body.get('outcome'), body.get('note', '')
        statuses = {'none': 'no report to read', 'access_code': 'access code needed', 'saved_by_hand': 'saved by hand'}
        if outcome not in statuses or not isinstance(note, str): raise ValueError('invalid pathology outcome')
        if outcome == 'saved_by_hand': conn.execute('UPDATE patients SET has_pathology=1,updated_at=? WHERE id=?', (db.now(), pid))
        db.log(conn, pid, 'pathology_result', {'status': statuses[outcome], 'note': note}, 'app')
        conn.execute("UPDATE tasks SET state=?,output=?,finished=? WHERE patient_id=? AND step='pathology' AND state IN ('queued','waiting')", ('cancelled' if outcome == 'access_code' else 'done', statuses[outcome], db.now(), pid))
    elif name == 'interactions_manual':
        if p['state'] not in ('visited', 'report_drafted', 'signed_off'): raise ValueError('invalid patient state')
        text = body.get('text')
        if not isinstance(text, str) or not 1 <= len(text) <= 20000 or not text.strip(): raise ValueError('invalid text')
        folder = jobs.patient_folder(p)
        today = dt.date.today()
        stem = 'MIMS interactions (manual) ' + today.isoformat()
        n = 1
        while records.exists(conn, pid, stem + (f' ({n})' if n > 1 else '') + '.txt'): n += 1
        rec_name = stem + (f' ({n})' if n > 1 else '') + '.txt'
        records.put(conn, pid, rec_name, ('Checked by hand by ' + settings.get(conn, 'pharmacist_name') + ' on ' + today.strftime('%d/%m/%Y') + '\n' + text).encode('utf-8'))
        db.log(conn, pid, name, {'file': rec_name}, 'app')
        conn.execute("UPDATE tasks SET state='done',output=?,finished=? WHERE patient_id=? AND step='interactions' AND state IN ('queued','waiting')", (rec_name, db.now(), pid))
    elif name in ('archive', 'unarchive'):
        if name == 'archive' and p['state'] not in ('claimed', 'declined', 'expired'):
            raise ValueError('Cannot archive this patient')
        if name == 'archive' and p['state'] == 'claimed' and patient_followups(conn, pid) and patient_followups(conn, pid)['next_action']:
            raise ValueError('Cannot archive while follow-up obligations are open')
        conn.execute('UPDATE patients SET archived_at=?,updated_at=? WHERE id=?', (db.now() if name == 'archive' else None, db.now(), pid))
        db.log(conn, pid, name, {}, 'app')
    elif name == 'resume':
        if p['state'] != 'hold': raise ValueError('Patient is not on hold')
        db.set_state(conn, pid, p['hold_from'] or 'pooled', source='app', force=True)
        conn.execute('UPDATE patients SET hold_from=NULL WHERE id=?', (pid,))
    elif name == 'undo_stage':
        event = undo_event(conn, p)
        if not event: raise ValueError('Nothing to undo')
        db.set_state(conn, pid, event['from'], source='app', force=True)
        field = {'visited': 'visit_date', 'sent': 'report_sent', 'claimed': 'claimed'}.get(event['to'])
        if field:
            conn.execute('UPDATE visits SET ' + field + "=NULL WHERE id=(SELECT id FROM visits WHERE patient_id=? AND source='app' ORDER BY id DESC LIMIT 1)", (pid,))
        if event['to'] == 'visited':
            prior = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='visited' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
            booking = json.loads(prior['detail'] or '{}').get('prior_booking', {}) if prior else {}
            if booking:
                conn.execute('UPDATE patients SET visit_date=?,visit_time=?,visit_end=?,visit_group=? WHERE id=?', (booking.get('visit_date'),booking.get('visit_time'),booking.get('visit_end'),booking.get('visit_group'),pid))
        db.log(conn, pid, 'undo_stage', event, 'app')
    elif name == 'not_visited':
        event = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='visited' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if p['state'] != 'visited' or not event or json.loads(event['detail'] or '{}').get('auto') is not True:
            raise ValueError('latest visit is not an automatic visit')
        visit_date = p['visit_date']
        db.set_state(conn, pid, 'pooled', 'Visit did not happen ' + date(visit_date).strftime('%d/%m/%Y'), source='app', force=True)
        conn.execute('UPDATE patients SET offered_date=visit_date,visit_date=NULL,visit_time=NULL,visit_end=NULL,updated_at=? WHERE id=?', (db.now(), pid))
        conn.execute("UPDATE visits SET visit_date=NULL,report_sent=NULL,claimed=NULL,note='auto-recorded, did not happen' WHERE id=(SELECT id FROM visits WHERE patient_id=? AND kind='hmr' AND source='app' ORDER BY id DESC LIMIT 1)", (pid,))
        db.log(conn, pid, name, {'date': visit_date}, 'app')
    elif name == 'move_declined':
        if p['state'] != 'declined':
            raise ValueError('patient is not declined')
        moved = move_patient_item(conn, p, 'Declined', moved_items)
        if moved: db.log(conn, pid, 'move_declined', {}, 'app')
    elif name == 'claim_now':
        visit, sent = date(body.get('visit_date')), date(body.get('report_sent'))
        if p['state'] in ('sent', 'claimed') or not visit <= sent <= dt.date.today():
            raise ValueError('invalid state or dates')
        db.log(conn, pid, 'visited', {'date': body['visit_date']}, 'app')
        db.log(conn, pid, 'report_sent', {'date': body['report_sent']}, 'app')
        conn.execute("INSERT INTO visits(patient_id,kind,visit_date,report_sent,folder,source) VALUES (?,'hmr',?,?,?,'app')",
                     (pid, body['visit_date'], body['report_sent'], p['folder']))
        db.set_state(conn, pid, 'sent', 'Visited outside the app', source='app', force=True)
    elif name == 'followup_done':
        existing = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind=? AND visit_date >= COALESCE((SELECT MAX(visit_date) FROM visits WHERE patient_id=? AND kind='hmr'), '') ORDER BY id DESC LIMIT 1", (pid,body['kind'],pid)).fetchone()
        if existing: return {'ok': True}
        conn.execute("INSERT INTO visits(patient_id,kind,visit_date,folder,source) VALUES (?,?,?,?,'app')", (pid,body['kind'],body['date'],p['folder']))
        db.log(conn, pid, name, {'kind':body['kind'],'date':body['date']}, 'app')
    elif name == 'followup_claimed':
        row = conn.execute("SELECT id FROM visits WHERE patient_id=? AND kind=? AND visit_date IS NOT NULL ORDER BY visit_date DESC,id DESC LIMIT 1", (pid, body['kind'])).fetchone()
        if not row: raise ValueError('follow-up is not done')
        import followup
        gaps = followup.readiness(conn, p, int(body['kind'][-1]), conn.execute('SELECT visit_date FROM visits WHERE id=?', (row['id'],)).fetchone()[0])
        if gaps: raise ValueError('Follow-up cannot be marked claimed until documented: ' + '; '.join(gaps))
        conn.execute('UPDATE visits SET claimed=? WHERE id=?', (body['date'], row['id']))
        db.log(conn, pid, name, {'kind': body['kind'], 'date': body['date']}, 'app')
    elif name == 'call':
        if body.get('outcome') not in ('no_answer', 'left_message', 'spoke', 'booked', 'declined', 'other') or not isinstance(body.get('note', ''), str): raise ValueError('invalid call')
        db.log(conn, pid, name, {'outcome': body['outcome'], 'note': body.get('note', '')}, 'app')
    elif name == 'note':
        if not isinstance(body.get('text'), str):
            raise ValueError('text must be a string')
        conn.execute('UPDATE patients SET note=?,updated_at=? WHERE id=?', (body['text'], db.now(), pid))
        db.log(conn, pid, 'note', {'text': body['text']}, 'app')
    elif name == 'update':
        fields = body.get('fields')
        allowed = {'phone', 'address', 'suburb', 'postcode', 'medicare', 'irn', 'ihi', 'dob', 'sex',
                   'gp', 'clinic', 'gp_provider', 'clinic_address', 'clinic_phone', 'referral_date'}
        if not isinstance(fields, dict) or not fields or not fields.keys() <= allowed or any(v is not None and not isinstance(v, str) for v in fields.values()):
            raise ValueError('invalid fields')
        if 'referral_date' in fields and fields['referral_date']:
            try:
                if __import__('datetime').date.fromisoformat(fields['referral_date']).isoformat() != fields['referral_date']:
                    raise ValueError('invalid referral date')
            except ValueError:
                raise ValueError('Referral date must be YYYY-MM-DD')
        conn.execute('UPDATE patients SET ' + ','.join(k+'=?' for k in fields) + ',updated_at=? WHERE id=?', [*fields.values(), db.now(), pid])
        db.log(conn, pid, 'update', fields, 'app')
    else:
        raise ValueError('unknown action')
    conn.commit()
    return {'ok': True, 'moved': moved} if name in ('decline_phone', 'move_declined', 'expired', 'claim_now') else {'ok': True}
