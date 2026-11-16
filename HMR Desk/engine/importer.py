"""Import the existing HMR files into the desk database."""
import datetime
import argparse
import csv
from contextlib import closing
import json
import os
from pathlib import Path
import re
import tempfile

import db
import inbox

FIELDS = {'Name': 'name', 'Suburb': 'suburb', 'Address': 'address', 'Phone': 'phone',
          'GP': 'gp', 'Referral date': 'referral_date', 'Status': 'status_text',
          'Date': 'visit_date', 'Time': 'visit_time', 'End': 'visit_end', 'Group': 'visit_group',
          'Conversation note': 'note', 'Reply': 'reply', 'Offered date': 'offered_date'}
FAMILY = {'confirmed', 'pathology_ready', 'sheet_ready'}
POST = {'visited', 'report_drafted', 'signed_off', 'sent', 'claimed'}


def read(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f)


def newest(paths):
    return max(paths, key=lambda p: p.stat().st_mtime, default=None)


def state(text):
    s = (text or '').lower().strip()
    for prefix, result in [('confirmed', 'confirmed'), ('offer sent', 'offered'), ('suggested', 'pooled'),
                           ('reply received', 'offered'), ('hold', 'hold'), ('declined', 'declined'),
                           ('likely declined', 'declined'), ('completed', 'visited')]:
        if s.startswith(prefix):
            return result
    return 'expired' if 'expired' in s or 'excluded' in s else 'new'


def postcode(suburb, address):
    m = re.match(r'^(\d{4})\b', suburb or '')
    nums = re.findall(r'(?<!\d)\d{4}(?!\d)', address or '')
    return m.group(1) if m else (nums[-1] if nums else None)


def app_referral_folder(conn, row, base):
    if not row['folder']: return None
    path = (base / row['folder']).resolve()
    if not path.is_relative_to(base) or not path.is_dir(): return None
    if path.relative_to(base).parts[0] not in ('TO SORT', 'Scheduled', 'Visited', 'Declined-Exp', 'Completed & Claimed', 'To CLAIM'): return None
    for event in conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='referral_received' AND source='intake'", (row['id'],)):
        try:
            detail = json.loads(event['detail'] or '{}')
            created = Path(detail.get('folder', ''))
            if (len(created.parts) == 2 and created.parts[0] == 'TO SORT' and
                re.fullmatch(r'Referral-[0-9a-f]{32}', created.name) and created.name == path.name and
                re.fullmatch(r'[0-9a-f]{64}', detail.get('sha256', ''))): return path
        except (AttributeError, TypeError, ValueError):
            continue
    return None


def run(conn, base=db.BASE, source='importer'):
    base = Path(base).resolve()
    sorting = base / 'TO SORT'
    plan = newest(base.glob('Appointment_Plan_[0-9]*.json'))
    if not plan:
        raise FileNotFoundError('No appointment plan found in ' + str(base))
    data = read(plan)
    meta = {k: v for k, v in data.items() if k != 'patients'}
    for k, v in [('plan_meta', json.dumps(meta, ensure_ascii=False)), ('plan_file', str(plan))]:
        conn.execute('INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE value IS NOT excluded.value', (k, v))
    checks, seen, planned, desired = [], set(), set(), {}

    def patient(name):
        key = db.patient_key(name)
        if not key:
            return None
        conn.execute('INSERT OR IGNORE INTO patients(key,name) VALUES (?,?)', (key, name))
        return conn.execute('SELECT * FROM patients WHERE key=?', (key,)).fetchone()

    def update(row, values, audit=False):
        changes = {k: [row[k], v] for k, v in values.items() if row[k] != v}
        if changes:
            conn.execute('UPDATE patients SET ' + ', '.join(k+'=?' for k in changes) + ', updated_at=? WHERE id=?',
                         [v[1] for v in changes.values()] + [db.now(), row['id']])
            if audit:
                db.log(conn, row['id'], 'import_change', changes, source)
        return conn.execute('SELECT * FROM patients WHERE id=?', (row['id'],)).fetchone()

    for i, item in enumerate(data['patients']):
        row = patient(item.get('Name'))
        if row is None:
            continue
        if row['key'] in seen:
            checks.append('Two plan names map to one key: ' + item['Name'])
        seen.add(row['key']); planned.add(row['id'])
        values = {v: item.get(k) for k, v in FIELDS.items()}
        app_folder = app_referral_folder(conn, row, base)
        if app_folder:
            for field in ('address', 'suburb', 'phone', 'gp', 'referral_date'):
                if not values.get(field): values.pop(field, None)
        events = list(conn.execute("SELECT type,detail,source FROM events WHERE patient_id=? AND type IN ('state','book_phone','move','not_visited','undo_stage','note','hold','reply_received','import_change') ORDER BY id DESC", (row['id'],)))
        lifecycle = next((e for e in events if e['type'] in ('book_phone','move','not_visited','undo_stage') or (e['type'] == 'state' and json.loads(e['detail'] or '{}').get('from') != json.loads(e['detail'] or '{}').get('to'))), None)
        owned = False
        if lifecycle and lifecycle['source'] == 'app':
            detail = json.loads(lifecycle['detail'] or '{}')
            owned = lifecycle['type'] != 'state' or (detail.get('to') == row['state'] and detail.get('from') != detail.get('to'))
        protected = []
        if owned or row['state'] in POST and state(item.get('Status')) not in POST:
            protected.extend(('status_text', 'visit_date', 'visit_time', 'visit_end', 'visit_group', 'offered_date'))
        for field, actions in (('note', ('note', 'hold')), ('reply', ('reply_received',))):
            for event in events:
                if event['type'] == 'import_change':
                    if field in json.loads(event['detail'] or '{}'): break
                elif event['type'] in actions:
                    if event['source'] not in ('importer', 'sms_replies_log.json'): protected.append(field)
                    break
        conflicts = [field for field in protected if values.get(field) != row[field]]
        if conflicts: checks.append('App-owned plan conflict for ' + row['name'] + ': ' + ', '.join(conflicts))
        for field in protected: values.pop(field, None)
        code = postcode(item.get('Suburb'), item.get('Address'))
        values.update(plan_order=i)
        if code or not app_folder: values['postcode'] = code
        row = update(row, values, audit=True)
        desired[row['id']] = row['state'] if owned else state(item.get('Status'))
    for row in conn.execute('SELECT * FROM patients WHERE plan_order IS NOT NULL AND is_test=0').fetchall():
        if row['id'] not in planned:
            update(row, {'plan_order': None}, audit=True)

    referrals = set()
    intake = newest(sorting.glob('intake_report_*.json'))
    corrections = read(sorting / 'intake_corrections.json') if (sorting / 'intake_corrections.json').exists() else {}
    if intake:
        for entry in read(intake):
            if entry.get('kind') != 'referral':
                continue
            fields = {**entry.get('fields', {}), **corrections.get(entry.get('file'), {})}
            row = patient(fields.get('name'))
            if row is None:
                continue
            referrals.add(row['id'])
            if app_referral_folder(conn, row, base):
                continue
            values = {k: fields[k] for k in ('dob', 'sex', 'medicare', 'irn', 'ihi', 'clinic') if fields.get(k) is not None}
            if row['id'] not in planned:
                values.update({k: fields[k] for k in ('address', 'suburb', 'phone', 'gp', 'referral_date') if fields.get(k) is not None})
                values['postcode'] = postcode(values.get('suburb'), values.get('address'))
            update(row, values)

    register = set()
    csvfile = base / 'Declined-Exp' / 'Declines register.csv'
    if csvfile.exists():
        with csvfile.open(encoding='utf-8-sig', newline='') as f:
            for item in csv.DictReader(f):
                if (item.get('Their words') or '').startswith('TEST - '): continue
                key = db.patient_key(item.get('Patient'))
                existing = conn.execute('SELECT * FROM patients WHERE key=?', (key,)).fetchone()
                row = existing or patient(item.get('Patient'))
                if row is None:
                    continue
                register.add(row['id'])
                if not existing:
                    update(row, {'gp': item.get('GP'), 'status_text': 'Declined (register)'})
                    desired[row['id']] = 'declined'

    numbers = {}
    for file in sorted(sorting.glob('sms_*.json')):
        if file.name == 'sms_replies_log.json':
            continue
        entries = read(file)
        if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) and 'contact_id' in e for e in entries):
            continue
        for i, e in enumerate(entries):
            row = patient(e.get('name'))
            if row is None:
                continue
            if e.get('contact_id') is not None:
                row = update(row, {'contact_id': str(e['contact_id'])})
            number = e.get('number')
            if number:
                numbers.setdefault(row['id'], set()).add(str(number))
            word = (e.get('status') or '').split()
            status = next((x for x in ('Delivered', 'Sent', 'Pending', 'Failed') if word and word[0].lower() == x.lower()), 'unknown')
            kind = 'invitation' if file.name.startswith('sms_send_queue_') else 'offer' if file.name.startswith('sms_offers_') else e.get('kind') if file.name.startswith('sms_replies_sent_') else None
            # these rows belong to the old log files, so a later status there (Pending -> Delivered) is taken over
            conn.execute('INSERT INTO messages(id,patient_id,direction,body,kind,state,recipient,created_at,sent_at,source) VALUES (?,?,?,?,?,?,?,?,?,?) '
                         "ON CONFLICT(id) DO UPDATE SET state=excluded.state WHERE messages.source=excluded.source AND messages.state IS NOT excluded.state AND messages.state NOT IN ('Delivered','Failed')",
                         (e.get('draft_id') or f'legacy-{file.stem}-{i}', row['id'], 'out', e.get('sms') or '', kind, status, number, e.get('sent_at') or '', e.get('sent_at'), file.name))

    replies = sorting / 'sms_replies_log.json'
    if replies.exists():
        for e in read(replies):
            if inbox.proda_sms.is_proda_code(str(e.get('sender') or e.get('phone') or ''), e.get('text') or ''): continue
            row = conn.execute('SELECT * FROM patients WHERE key=?', (db.patient_key(e.get('name')),)).fetchone()
            if row is None and e.get('contact_id') is not None:
                row = conn.execute('SELECT * FROM patients WHERE contact_id=? AND is_test=0', (str(e['contact_id']),)).fetchone()
            if row is None:
                checks.append('Reply patient unmatched: ' + str(e.get('name') or e.get('inbox_id')))
            received = e.get('received') or ''
            try:  # skip a reply the phone check already stored under another id
                when = datetime.datetime.fromisoformat(received.replace('Z', '+00:00'))
                when = when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)
                if row and inbox.already_have(conn, row['id'], e.get('text') or '', when): continue
            except ValueError:
                pass
            offer = conn.execute("SELECT id FROM messages WHERE patient_id=? AND direction='out' AND kind IN ('offer','change','change_request','invitation') AND sent_at IS NOT NULL AND sent_at < ? ORDER BY sent_at DESC LIMIT 1", (row['id'] if row else None, received)).fetchone()
            conn.execute('INSERT OR IGNORE INTO messages(id,patient_id,direction,body,kind,state,created_at,offer_ref,source) VALUES (?,?,?,?,?,?,?,?,?)',
                         (e.get('inbox_id'), row['id'] if row else None, 'in', e.get('text') or '', e.get('kind'), 'received', received, offer['id'] if offer else None, replies.name))

    folders = {}
    for rootname in ('Scheduled', 'on Excel', 'Visited', 'Declined-Exp'):
        root = base / rootname
        if not root.exists():
            continue
        entries = root.iterdir() if rootname in ('Scheduled', 'on Excel') else root.rglob('*')
        for path in entries:
            if path.name.startswith(('_', '~')) or (rootname == 'Scheduled' and not path.is_dir()) or (rootname == 'on Excel' and not path.is_file()):
                continue
            name = re.sub(r'^(XX|ZZ)\s*', '', path.name.split('_')[0], flags=re.I)
            if rootname == 'on Excel' and '_' not in path.name:
                name = Path(name).stem
            key = db.patient_key(name)
            if key and key not in folders:
                folders[key] = path
    for row in conn.execute('SELECT * FROM patients WHERE is_test=0').fetchall():
        app_folder = app_referral_folder(conn, row, base)
        path = folders.get(row['key']) or app_folder
        scheduled = bool(path and path.is_relative_to(base / 'Scheduled'))
        pathology = bool(path and path.is_dir() and (path / 'Pathology').is_dir() and any(p.is_file() and p.suffix.lower() == '.pdf' for p in (path / 'Pathology').rglob('*')))
        sheet = bool(path and path.is_dir() and (scheduled or path == app_folder) and any(p.is_file() for p in path.glob('HMR Interview*.docx')))
        row = update(row, {'folder': str(path.relative_to(base)) if path else None, 'has_pathology': int(pathology or row['has_pathology']), 'has_sheet': int(sheet)})
        target = desired.get(row['id'], row['state'])
        if row['state'] in POST and target not in POST:  # the plan's free-text status must never undo a recorded visit
            target = row['state']
        if target == 'confirmed':
            target = 'sheet_ready' if sheet else 'pathology_ready' if pathology else target
        db.set_state(conn, row['id'], target, source=source, force=True)
        name = row['name']
        if target in FAMILY and not scheduled and not (path and path == app_folder): checks.append('Confirmed without Scheduled folder: ' + name)
        if scheduled and target not in FAMILY: checks.append('Scheduled folder but not confirmed: ' + name)
        if row['id'] in planned and not path and target not in ('declined', 'expired'): checks.append('On plan without referral file in any folder: ' + name)
        if target == 'offered' and not conn.execute("SELECT 1 FROM messages WHERE patient_id=? AND direction='out' LIMIT 1", (row['id'],)).fetchone(): checks.append('Offered without outgoing message: ' + name)
        if row['id'] in planned and state(row['status_text']) == 'declined' and row['id'] not in register: checks.append('Plan declined but missing from register: ' + name)
        if row['id'] in register and target != 'declined': checks.append('In register but not declined: ' + name)
        digits = lambda x: re.sub(r'\D', '', str(x or ''))
        if row['id'] in planned and digits(row['phone']) and any(digits(n) != digits(row['phone']) for n in numbers.get(row['id'], ())): checks.append('Plan phone differs from SMS number: ' + name)
    conn.commit()
    states = dict(conn.execute('SELECT state, count(*) FROM patients WHERE is_test=0 GROUP BY state ORDER BY state'))
    messages = {f'{r[0]} {r[1]}': r[2] for r in conn.execute('SELECT m.direction,m.state,count(*) FROM messages m LEFT JOIN patients p ON p.id=m.patient_id WHERE COALESCE(p.is_test,0)=0 GROUP BY m.direction,m.state ORDER BY m.direction,m.state')}
    return {'states': states, 'messages': messages, 'checks': checks}


def format_report(report):
    return '\n'.join(['States: ' + ', '.join(f'{k}={v}' for k, v in report['states'].items()),
                      'Messages: ' + ', '.join(f'{k}={v}' for k, v in report['messages'].items()),
                      'Check these:'] + ['- ' + x for x in report['checks']])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--dry', action='store_true'); args = parser.parse_args()
    if args.dry:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            conn = db.connect(str(Path(tmp) / 'dry.db'))
            if Path(db.db_path()).exists():
                with closing(db.open_encrypted(db.db_path(), readonly=True)) as original:
                    original.backup(conn)
            print(format_report(run(conn))); conn.close()
    else:
        conn = db.connect(); print(format_report(run(conn))); conn.close()
