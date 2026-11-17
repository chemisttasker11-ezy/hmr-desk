"""Read new patient SMS replies from the phone gateway and log them against the offers sent.
usage: python check_replies.py            (prints one line per new reply, or "No new replies")
Never sends anything. Replies are logged in TO SORT\\sms_replies_log.json and on the matching offer entry."""
import csv, datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TO_SORT = os.path.join(os.path.dirname(HERE), 'TO SORT')
STATE = os.path.join(os.environ['LOCALAPPDATA'], 'HMR-SMS-Bridge', 'reply_check_state.json')
LOG = os.path.join(TO_SORT, 'sms_replies_log.json')
FIRST_RUN_SINCE = '2026-11-09T03:00:00Z'  # start of the 09/11 batch


def bridge(*args):
    return subprocess.run([sys.executable, os.path.join(HERE, 'patient_bridge.py'), *args],
                          capture_output=True, text=True, encoding='utf-8', timeout=120, cwd=HERE)


def classify(text):
    t = text.strip().lower()
    if re.search(r'\b\d{1,2}([:.]\d\d)?\s*(am|pm)\b|suit|instead|another|better|reschedul', t):
        return 'OTHER'  # a "yes" that asks for a different time still needs the user
    if re.search(r'happy to|would like|keen|meet you|see you|not sure|\?', t):
        return 'OTHER'  # hesitant or warm replies ("I'm happy to meet you but...") need the user, never an auto-answer
    # decline first: "Yes, not to go ahead" is a decline
    if re.search(r"\b(decline|no thanks|no thank you|not interested|don.?t need (it|this|the|a)|no need|not (to )?go ahead|don.?t want (it|this|the|a|to (do|have|go)))\b", t):
        return 'DECLINE'
    if re.match(r'^(hi\W+)?(yes|yep|yeah|ok(ay)?|confirm(ed)?|sounds good|that.?s fine|perfect)\b', t):
        return 'YES'
    return 'OTHER'


def reply_text(shown):
    """The message is everything after the PREVIEW ONLY line; it can span several lines."""
    lines = shown.replace('\r', '').split('\n')
    start = next((i + 1 for i, l in enumerate(lines) if l.startswith('PREVIEW ONLY')), len(lines))
    return ' '.join(l.strip() for l in lines[start:] if l.strip())


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


STATUS = {'YES': 'Confirmed by SMS reply', 'DECLINE': 'Declined by SMS reply', 'OTHER': 'Reply received - clarification needed'}


def update_dashboard(new):
    """Write replies into the newest Appointment_Plan_*.json, then re-render the dashboard and day maps."""
    base = os.path.dirname(HERE)
    plans = glob.glob(os.path.join(base, 'Appointment_Plan_[0-9]*.json'))
    if not plans:
        return
    plan = max(plans, key=os.path.getmtime)
    doc = load(plan, {})
    for rec in new:
        for p in doc.get('patients', []):
            if p.get('Name') == rec['name']:
                # a follow-up "thanks" keeps an earlier decline or confirmation
                kind = rec['kind'] if (rec['kind'] != 'YES' or p.get('Date')) else 'OTHER'  # a "yes" with no offered slot is not a booking
                if not (kind == 'OTHER' and p.get('Status', '').startswith(('Declined', 'Confirmed', 'Hold'))):
                    p['Status'] = STATUS[kind]
                p['Reply'] = f"{rec['received'][:16].replace('T', ' ')}: {rec['text']}"
                if rec['kind'] == 'DECLINE':  # GPs are not messaged; the register answers them if they ask
                    with open(os.path.join(base, 'Declined-Exp', 'Declines register.csv'), 'a', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f).writerow([rec['name'], re.sub(r'^Dr\.?\s+', '', str(p.get('GP', ''))), rec['received'][:10], 'SMS', rec['text'], 'Added by reply check'])
    doc['last_checked_brisbane'] = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
    with open(plan, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    for script in (os.path.join(base, 'render_appointment_calendar.py'), os.path.join(base, 'scripts', 'dashboard', 'build_day_maps.py')):
        subprocess.run([sys.executable, script, plan], capture_output=True, timeout=120, cwd=base)


def newest_plan():
    plans = glob.glob(os.path.join(os.path.dirname(HERE), 'Appointment_Plan_[0-9]*.json'))
    return load(max(plans, key=os.path.getmtime), {}) if plans else {}


def auto_reply(new, state):
    """Inside the window the user approved (state['auto_reply_until']), answer clear YES / DECLINE replies.
    Anything else, or a YES that also says no/not/can't, is left for the user."""
    until = state.get('auto_reply_until')
    if not until or datetime.datetime.now() > datetime.datetime.fromisoformat(until):
        return
    plan = {p['Name']: p for p in newest_plan().get('patients', []) if p.get('Date')}
    done = set(state.setdefault('auto_replied', []))
    for rec in new:
        kind, p = rec['kind'], plan.get(rec['name'])
        if kind == 'YES' and re.search(r"\b(not|no|can.?t|cannot|unable|busy|won.?t)\b", rec['text'].lower()):
            kind = 'OTHER'
        if kind == 'DECLINE' and not re.search(r"\b(decline|not interested|no thanks|no thank you|not to go ahead)\b", rec['text'].lower()):
            kind = 'OTHER'  # only an explicit decline gets the automatic thank-you; anything softer goes to the user
        if kind == 'YES' and p and str(p.get('Suburb', '')).startswith('2'):
            kind = 'OTHER'  # NSW postcode: plan times are QLD, so the user confirms these by hand in NSW time
        if kind not in ('YES', 'DECLINE') or rec['contact_id'] in done or (kind == 'YES' and not p):
            continue
        first = rec['name'].split()[0]
        gp = re.sub(r'^Dr\.?\s+', '', str((p or {}).get('GP', ''))).strip().split()[-1:] or ['your GP']
        sig = '\n\nRegards,\nConsultant Pharmacist'
        if kind == 'YES':
            dt = datetime.date.fromisoformat(p['Date']); h, m = map(int, p['Time'].split(':'))
            when = f"{dt:%A} {dt.day} {dt:%B} at {(h - 1) % 12 + 1}:{m:02d} {'am' if h < 12 else 'pm'}"
            text = f"Thank you, {first}. Your Home Medicines Review is confirmed for {when} at your home. See you then." + sig
        else:
            who = f'Dr {gp[0]}' if gp != ['your GP'] else 'your GP'
            text = f"Thank you for letting me know, {first}. No problem at all, and I'll let {who} know." + sig
        tf = os.path.join(os.path.dirname(STATE), 'auto_reply.txt')
        with open(tf, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        d = re.search(r'\bd-[0-9a-f]+-\d+\b', bridge('draft', '--contact', rec['contact_id'], '--text-file', tf).stdout)
        s = re.search(r'Gateway State:\s*(\w+)', bridge('send', '--id', d.group()).stdout) if d else None
        rec['auto_reply'] = f"{'confirmation' if kind == 'YES' else 'decline thanks'} {s.group(1) if s else 'NOT SENT'}"
        if s:
            done.add(rec['contact_id'])
    state['auto_replied'] = sorted(done)


def main():
    state = load(STATE, {'since': FIRST_RUN_SINCE, 'seen': []})
    started = datetime.datetime.now(datetime.timezone.utc)
    r = bridge('poll-inbox', '--since', state['since'])
    if r.returncode or 'Inbox Poll Results' not in r.stdout:
        print('GATEWAY NOT REACHABLE:', (r.stdout + r.stderr).strip().splitlines()[-1][:200])
        return  # last check time is not advanced, so nothing is skipped
    offers = {}  # contact id -> (file, entry); later files win, so the latest offer is used
    for path in sorted(glob.glob(os.path.join(TO_SORT, 'sms_send_queue_*.json'))) + sorted(glob.glob(os.path.join(TO_SORT, 'sms_offers_*.json'))):  # offers after invitations, so the offer wins
        for e in load(path, []):
            if e.get('contact_id'):
                offers[e['contact_id']] = (path, e)
    log = load(LOG, [])
    new = []
    for inbox_id, contact, when in re.findall(r'Inbox ID: (\w+) \| From: \S+ \(Contact: ([\w-]+)\) \| Time: (\S+)', r.stdout):
        if inbox_id in state['seen']:
            continue
        text = reply_text(bridge('show-inbox', '--id', inbox_id).stdout)
        path, entry = offers.get(contact, (None, {}))
        rec = dict(received=when, name=entry.get('name', contact), contact_id=contact, text=text, kind=classify(text),
                   offer=f"{os.path.basename(path)}: {entry.get('time', 'invitation')}" if path else None, inbox_id=inbox_id)
        log.append(rec); new.append(rec); state['seen'].append(inbox_id)
        if path:  # note the reply on the offer itself
            data = load(path, [])
            for e in data:
                if e.get('contact_id') == contact:
                    e.setdefault('replies', []).append(f"{when} [{rec['kind']}] {text}")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
    auto_reply(new, state)
    with open(LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    # overlap 10 minutes so a late-indexed message is not missed; duplicates are skipped by inbox id
    state['since'] = (started - datetime.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    update_dashboard(new)
    for rec in new:
        print(f"{rec['received'][:16].replace('T', ' ')} | {rec['name']} | {rec['kind']} | {rec['offer']} | {rec['text']}"
              + (f" | AUTO-REPLIED: {rec['auto_reply']}" if rec.get('auto_reply') else ''))
    if not new:
        print('No new replies')


if __name__ == '__main__':
    main()
