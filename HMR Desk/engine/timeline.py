"""Patient activity and milestones assembled from the audit trail and records."""
import datetime as dt
import json
import api
import steps

def build(conn, patient):
    pid = patient['id']; entries = []
    events = list(conn.execute('SELECT * FROM events WHERE patient_id=? ORDER BY id', (pid,)))
    messages = list(conn.execute('SELECT * FROM messages WHERE patient_id=?', (pid,)))
    visits = list(conn.execute('SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date,id', (pid,)))
    local_zone = dt.timezone(dt.timedelta(hours=10))
    def local_time(value):
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=local_zone) if parsed.tzinfo is None else parsed.astimezone(local_zone)
        except (ValueError, TypeError, AttributeError):
            return None
    def add(at, label, detail, kind, date_only=False):
        value = local_time(at[:10] + 'T12:00' if date_only else at)
        if value:
            at_text = value.strftime('%a %d %b %Y') if date_only else value.strftime('%a %d %b %Y, ') + str(value.hour % 12 or 12) + value.strftime(':%M ') + ('am' if value.hour < 12 else 'pm')
            entries.append({'at': value.isoformat(timespec='minutes')[:16], 'at_text': at_text, 'label': label, 'detail': detail, 'kind': kind, '_sort': value})
    def field_name(name):
        return {'dob': 'DOB', 'medicare': 'Medicare', 'ihi': 'IHI', 'irn': 'IRN', 'gp': 'GP'}.get(name, name.replace('_', ' '))
    states = {'new': 'New', 'pooled': 'Pooled', 'offered': 'Offered', 'confirmed': 'Confirmed', 'pathology_ready': 'Pathology ready', 'sheet_ready': 'Interview sheet ready', 'visited': 'Visited', 'report_drafted': 'Report drafted', 'signed_off': 'Signed off', 'sent': 'Report sent', 'claimed': 'Claimed', 'hold': 'On hold', 'declined': 'Declined', 'expired': 'Referral expired'}
    for m in messages:
        label = 'Reply: "' + (' '.join((m['body'] or '').split())[:60] + ('...' if len(' '.join((m['body'] or '').split())) > 60 else '')) + '"' + (f" ({m['kind']})" if m['kind'] else '') if m['direction'] == 'in' else (m['kind'] or 'Message').replace('_', ' ').capitalize() + (' sent' if m['state'].lower() in ('sent', 'delivered') else '') + ' (' + m['state'].capitalize() + ')'
        add(m['sent_at'] or m['created_at'], label, m['body'], 'message')
    event_dates = {}
    confirmations = []
    dated = ('visited', 'report_sent', 'claimed', 'followup_done', 'followup_claimed', 'claim_now')
    action_minutes = {e['ts'][:16] for e in events if e['type'] in dated}
    labels = {'visited':'Visited', 'report_sent':'Report sent', 'claimed':'Claimed', 'claim_now':'Visited outside the app - ready to claim', 'book_phone':'Confirmed by phone', 'decline_phone':'Declined by phone', 'hold':'Put on hold', 'expired':'Referral expired', 'interview_saved':'Interview saved', 'interview_pack':'Interview pack made', 'message_queued':'Message queued', 'message_drafted':'Message drafted', 'message_discarded':'Message discarded', 'reply_received':'Reply received', 'autopilot_move_failed':'Autopilot: move failed', 'autopilot_call_list':'Autopilot: added to call list', 'consent_signed':'Consent signed', 'visited':'Visited', 'report_sent':'Report sent', 'claimed':'Claimed', 'move_declined':'Moved to Declined folder'}
    for e in events:
        try: d = json.loads(e['detail'] or '{}')
        except (ValueError, TypeError): d = {}
        if not isinstance(d, dict): d = {}
        typ = e['type']; event_dates.setdefault(typ, []).append(d.get('date') or e['ts'][:10])
        if typ == 'message_state': continue
        label = labels.get(typ, typ); detail = ''
        if typ == 'state':
            if (d.get('to') in ('confirmed', 'pathology_ready', 'sheet_ready') and d.get('from') in ('new', 'pooled', 'offered', 'hold', None)) or 'Confirmed by SMS reply' in (d.get('text') or ''): confirmations.append(e['ts'])
            if d.get('to') in ('visited', 'sent', 'claimed') and e['ts'][:16] in action_minutes: continue  # the action entry below says it, with the chosen date
            label = states.get(d.get('to'), 'Confirmed' if 'Confirmed by SMS reply' in (d.get('text') or '') else str(d.get('to') or 'state'))
            if d.get('text'): label += ' - ' + d['text']
        elif typ == 'referral_fields':
            label = 'Details filled from referral: ' + ', '.join(field_name(k) for k in d)
        elif typ == 'import_change':
            changed = [k for k, v in d.items() if not (isinstance(v, list) and len(v) == 2 and (v[0] == v[1] or (not v[0] and not v[1])))]
            if not changed: continue
            label = 'Register updated: ' + ', '.join(field_name(k) for k in changed[:4]) + (f' and {len(changed) - 4} more' if len(changed) > 4 else '')
        elif typ in ('decline_phone', 'hold'):
            detail = d.get('reason' if typ == 'decline_phone' else 'note') or ''
            if detail: label += ' - ' + detail
        elif typ == 'call':
            label = 'Called - ' + d.get('outcome', 'other').replace('_', ' '); detail = d.get('note', '')
        elif typ == 'pathology_result':
            saved = d.get('saved', []); status = d.get('status', '')
            if saved: label = f'Pathology: {len(saved)} reports saved'
            elif status.lower() == 'no report to read': label = 'Pathology: no reports in My Health Record'
            elif 'access' in status.lower() or 'code' in status.lower(): label = 'Pathology: access code needed'
            else: label = f'Pathology: {len(saved)} reports saved'
            detail = status
        elif typ in ('followup_done', 'followup_claimed'):
            label = 'Follow-up ' + str(d.get('kind', 'followup?')[-1]) + (' done' if typ == 'followup_done' else ' claimed')
        elif typ == 'autopilot':
            msg = next((m for m in messages if m['id'] == d.get('id')), None)
            label = 'Autopilot: ' + str(d.get('kind', '')).replace('_', ' ') + (' held (test mode)' if msg and msg['source'] == 'autopilot_test_hold' else ' ' + str(d.get('mode', '')))
        if typ in dated and d.get('date'):
            add(d['date'], label, 'recorded ' + (local_time(e['ts']).strftime('%d/%m/%Y %H:%M') if local_time(e['ts']) else ''), 'event', date_only=True)
            continue
        add(e['ts'], label, detail, 'event')
    for v in visits:
        if v['source'] == 'app': continue  # app actions already have their own dated entry
        prefix = 'Follow-up ' + v['kind'][-1] if v['kind'] != 'hmr' else ''
        for field, label in [('visit_date', prefix + ' done' if prefix else 'Visited'), ('report_sent','Report sent'), ('claimed', prefix + ' claimed' if prefix else 'Claimed')]:
            if v[field]: add(v[field], label, v['note'] or '', 'visit', date_only=True)
    def day(value):
        try: return local_time(value).date().isoformat() if local_time(value) else api.anydate(value).isoformat() if value else None
        except (ValueError, TypeError): return None
    def latest(values): return max((day(x) for x in values if day(x)), default=None)
    def earliest(values): return min((day(x) for x in values if day(x)), default=None)
    outgoing = [m for m in messages if m['direction'] == 'out' and m['state'].lower() in ('sent','delivered')]
    incoming = [m for m in messages if m['direction'] == 'in']
    follow = api.patient_followups(conn, pid)
    first = follow['followup1'] if follow else None
    due2 = str(dt.date.fromisoformat(first) + dt.timedelta(days=int(api.meta(conn, 'followup_first_after_days', 30)))) if first else None
    expiry = api.referral_expiry(conn, patient['referral_date'])
    milestones = dict(referral_date=day(patient['referral_date']), referral_expiry=expiry.isoformat() if expiry else None,
        first_contact=earliest([m['sent_at'] or m['created_at'] for m in outgoing] + event_dates.get('call', [])),
        last_message=latest([m['sent_at'] or m['created_at'] for m in outgoing]), last_reply=latest([m['created_at'] for m in incoming]),
        confirmed=earliest(event_dates.get('book_phone', []) + confirmations + [m['created_at'] for m in incoming if m['kind'] == 'YES']),
        scheduled_visit=(patient['visit_date'] + ('T' + patient['visit_time'] if patient['visit_time'] else '')) if patient['visit_date'] else None,
        declined=latest(event_dates.get('decline_phone', []) + [e['ts'] for e in events if e['type'] == 'state' and 'Declined by SMS reply' in (e['detail'] or '')]),
        visit=steps.event_date(conn, patient, 'visited'),
        report_sent=steps.event_date(conn, patient, 'report_sent'),
        claimed=steps.event_date(conn, patient, 'claimed'), call_attempts=len(event_dates.get('call', [])),
        followup1_due=follow['first_due'] if follow else None, followup2_due=due2)
    if milestones['visit'] and (not milestones['confirmed'] or milestones['confirmed'] > milestones['visit']):
        milestones['confirmed'] = 'unknown'  # visited, so it was confirmed, but the date is not recorded
    for number in (1, 2):
        rows = [v for v in visits if v['kind'] == f'followup{number}']
        milestones[f'followup{number}_done'] = latest([v['visit_date'] for v in rows])
        milestones[f'followup{number}_claimed'] = latest([v['claimed'] for v in rows])
    entries.sort(key=lambda entry: entry['_sort'], reverse=True)
    for entry in entries: del entry['_sort']
    return {'milestones': milestones, 'entries': entries}
