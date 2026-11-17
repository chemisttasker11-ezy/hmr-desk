"""Patient lifecycle and attention board."""
import datetime as dt
import json
import sqlite3
from pathlib import Path
import db
import messaging
import records
import settings
import steps

BOOKED = ('confirmed', 'pathology_ready', 'sheet_ready')



def auto_visit(conn, today=None, dry_run=False):
    import api
    today = today or dt.date.today()
    patients = conn.execute("SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL AND state IN ('confirmed','pathology_ready','sheet_ready') AND visit_date < ? ORDER BY visit_date,id", (str(today),)).fetchall()
    result = []
    for p in patients:
        notes = False
        try:
            data = records.get_json(conn, p['id'], 'interview.json') or {}
            notes = bool(data.get('notes', '').strip())
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        result.append({'id': p['id'], 'name': p['name'], 'date': p['visit_date'], 'notes': notes})
    if result and not dry_run:
        db.backup(conn)
        for p, item in zip(patients, result):
            api.action(conn, p, {'action': 'visited', 'date': item['date'], 'auto': True, 'notes': item['notes']})
    return result


def stage(conn, p, today=None):
    import api
    state = p['state']
    mapping = {'new': ('intake', 'new referral'), 'pooled': ('booking', 'to offer'),
               'offered': ('booking', 'offered'), 'visited': ('report', 'to write'),
               'report_drafted': ('report', 'drafted'), 'signed_off': ('report', 'signed'),
               'sent': ('claim', 'to claim'), 'hold': ('hold', ''), 'declined': ('declined', ''),
               'expired': ('expired', '')}
    if p['archived_at']:
        value = ('archived', '')
    elif state == 'hold' and p['hold_from']:
        value = ('hold', 'from ' + p['hold_from'])
    elif state in BOOKED:
        value = ('ready', 'ready') if steps.done('pathology', conn, p) and steps.done('interview_sheet', conn, p) else ('booking', 'confirmed')
    elif state == 'claimed':
        follow = api.patient_followups(conn, p['id'], today)
        if follow and follow['next_action']:
            action = follow['next_action']
            if action.endswith('_document'): step = action.replace('_document', '').replace('followup', 'follow-up ') + ' documentation incomplete'
            elif action.endswith('_claimed'): step = action.replace('_', ' ').replace('followup', 'follow-up ').replace('claimed', 'to claim')
            elif follow['next_due'] and follow['next_due'] > str(today or dt.date.today()): step = action.replace('followup', 'follow-up ') + ' waiting until ' + follow['next_due']
            else: step = action.replace('followup', 'follow-up ') + ' due'
            value = ('followup', step)
        else:
            value = ('done', 'claimed')
    else:
        value = mapping[state]
    return {'stage': value[0], 'step': value[1]}



def folder_check(p):
    expected = {'visited': 'Visited', 'report_drafted': 'Visited', 'signed_off': 'Visited',
                'sent': 'To CLAIM', 'claimed': 'Completed & Claimed',
                'declined': 'Declined-Exp', 'expired': 'Declined-Exp'}.get(p['state'], 'Scheduled')
    base = Path(db.BASE).resolve()
    actual = None
    try:
        path = (base / (p['folder'] or '')).resolve()
        if path != base and path.is_relative_to(base) and path.is_dir():
            actual = path.relative_to(base).parts[0]
    except (OSError, ValueError):
        pass
    return {'actual': actual, 'expected': expected, 'ok': actual is None or actual == expected}

def flags(conn, p, today=None, now=None):
    import api
    today = today or dt.date.today()
    now = now or dt.datetime.now()
    result = []
    if p['archived_at']:
        result.append('archived')
    elif conn:
        suggested = stage(conn, p, today)['stage'] == 'done'
        if p['state'] in ('declined', 'expired'):
            event = conn.execute("SELECT ts FROM events WHERE patient_id=? AND type='state' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
            try:
                suggested = bool(event and dt.datetime.fromisoformat(event['ts']) < now - dt.timedelta(days=30))
            except (ValueError, TypeError):
                suggested = False
        if suggested: result.append('archive_suggested')
    if p['call_list']: result.append('needs_call')
    if conn and p['state'] in db._PRE:
        expiry = api.referral_expiry(conn, p['referral_date'])
        if expiry:
            days = (expiry - today).days
            if days <= settings.get(conn, 'referral_warn_days'):
                result.append('referral_expired' if days < 0 else 'referral_expiring')
    if p['state'] in BOOKED and p['visit_date'] and p['visit_date'] < str(today): result.append('visit_passed')
    if p['state'] == 'offered' and p['visit_date'] and p['visit_time']:
        try:
            if dt.datetime.fromisoformat(p['visit_date'] + 'T' + p['visit_time']) < now: result.append('offer_passed')
        except ValueError: pass
    if conn and messaging.waiting_replies(conn, p['id']): result.append('reply_waiting')
    check = folder_check(p)
    if check['actual'] is None: result.append('no_folder')
    elif not check['ok']: result.append('folder_mismatch')
    return sorted(result)


def next_step(conn, p):
    import api
    if conn:
        found = flags(conn, p)
        for flag, label in [('reply_waiting', 'read reply'), ('offer_passed', 'offer a new time'), ('visit_passed', 'record the visit')]:
            # an old reply must not hide the report or claim step once the visit is done
            if flag in found and (flag != 'reply_waiting' or p['state'] in db._PRE): return label
    return api._next_step(p, conn)


def attention(conn, today=None, now=None):
    import api
    today = today or dt.date.today()
    now = now or dt.datetime.now()
    titles = [('today_visits', "Today's visits"), ('visits_to_check', 'Visits to check'),
              ('replies_waiting', 'Replies waiting'), ('offers_passed', 'Offers past their date'),
              ('prep', 'Prepare for the next 7 days'), ('reports', 'Reports'), ('claims', 'Claims due'),
              ('followups', 'Follow-ups due'), ('referrals', 'Referrals expiring'), ('stuck', 'Stuck')]
    groups = {key: {'key': key, 'title': title, 'items': []} for key, title in titles}
    def add(key, p, action, detail='', **fields):
        groups[key]['items'].append({'patient_id': p['id'] if p else None, 'name': p['name'] if p else '', 'detail': detail, 'action': action, **fields})
    patients = list(conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL ORDER BY name'))
    by_id = {p['id']: p for p in patients}
    for p in patients:
        f = flags(conn, p, today, now)
        date = p['visit_date'] or ''
        if p['state'] in BOOKED and date == str(today):
            add('today_visits', p, 'open_interview', time=p['visit_time'] or '', suburb=p['suburb'] or '', pathology_done=steps.done('pathology', conn, p), sheet_done=steps.done('interview_sheet', conn, p))
        if p['state'] == 'visited':
            event = conn.execute("SELECT ts,detail FROM events WHERE patient_id=? AND type='visited' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone()
            if event:
                detail = json.loads(event['detail'] or '{}')
                if detail.get('auto') is True:
                    add('visits_to_check', p, 'not_visited', visit_date=detail.get('date', date))
        if 'offer_passed' in f: add('offers_passed', p, 'offer', visit_date=date, visit_time=p['visit_time'])
        if p['state'] in BOOKED and str(today) <= date <= str(today + dt.timedelta(days=7)):
            for step in ('pathology', 'interview_sheet'):
                if not steps.done(step, conn, p):
                    event = conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='pathology_result' ORDER BY id DESC LIMIT 1", (p['id'],)).fetchone() if step == 'pathology' else None
                    note = {'note': 'access code needed'} if event and json.loads(event['detail'] or '{}').get('status') == 'access code needed' else {}
                    add('prep', p, step, visit_date=date, **note)
        if p['state'] in ('visited', 'report_drafted', 'signed_off'): add('reports', p, 'open_report', next_step(conn, p))
        if p['state'] == 'sent': add('claims', p, 'claim')
        follow = api.patient_followups(conn, p['id'], today)
        if follow:
            for alert in follow['alerts']:
                if alert.startswith('follow-up '):
                    number = '1' if '1' in alert else '2'
                    add('followups', p, 'followup' + number + ('_claimed' if 'to claim' in alert else ''), alert, window_end=follow['window_end'])
        if p['state'] != 'hold' and ('referral_expired' in f or 'referral_expiring' in f):
            expiry = api.referral_expiry(conn, p['referral_date'])
            add('referrals', p, 'expired' if 'referral_expired' in f else 'offer', expiry=str(expiry), days_left=(expiry-today).days)
    groups['today_visits']['items'].sort(key=lambda x: x['time'])
    for m in messaging.waiting_replies(conn):
        if m['patient_id'] in by_id: add('replies_waiting', by_id[m['patient_id']], 'open_messages', reply=m['body'], message_id=m['id'])
    for m in conn.execute("SELECT * FROM messages WHERE direction='out' AND state='draft' ORDER BY created_at DESC"):
        if m['patient_id'] in by_id: add('replies_waiting', by_id[m['patient_id']], 'open_messages', draft_id=m['id'], kind=m['kind'])
    cutoff = (now - dt.timedelta(days=7)).isoformat(timespec='seconds')
    for task in conn.execute("""SELECT t.* FROM tasks t WHERE t.state='failed' AND datetime(COALESCE(t.finished,t.created)) >= datetime(?)
        AND NOT EXISTS (SELECT 1 FROM tasks d WHERE d.patient_id=t.patient_id AND d.step=t.step AND d.state='done'
        AND datetime(COALESCE(d.finished,d.created)) > datetime(COALESCE(t.finished,t.created)))""", (cutoff,)):
        if task['patient_id'] in by_id: add('stuck', by_id[task['patient_id']], 'retry', task_id=task['id'], step=task['step'], **({'manual': True} if task['step'] in ('interview_assist', 'report_draft', 'report_assist') else {}))
    for m in conn.execute("SELECT * FROM messages WHERE direction='out' AND state='Failed' AND datetime(COALESCE(sent_at,created_at)) >= datetime(?)", (cutoff,)):
        if m['patient_id'] in by_id: add('stuck', by_id[m['patient_id']], 'open_messages', message_id=m['id'])
    if api.meta(conn, 'gateway_online', '') == 'false': add('stuck', None, 'check_phone', 'Phone gateway offline')
    return {'generated_at': now.isoformat(timespec='seconds'), 'groups': list(groups.values())}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', required=True)
    parser.parse_args()
    from pathlib import Path
    conn = db.open_encrypted(db.db_path(), readonly=True)
    conn.row_factory = sqlite3.Row
    try:
        visits = auto_visit(conn, dry_run=True)
        print('Count:', len(visits))
        for item in visits: print(item['date'])
    finally:
        conn.close()
