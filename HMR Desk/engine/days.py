"""Calendar summaries and approximate suburb-level map stops."""
import datetime as dt
import re

import db
from places import C, HOME, coordinates
from urllib.parse import urlencode
import settings

STATES = ('offered', 'confirmed', 'pathology_ready', 'sheet_ready', 'visited')
CONFIRMED = STATES[1:]


def category(p):
    text = (p['status_text'] or '').lower()
    if 'declin' in text or p['state'] == 'declined':
        return 'declined'
    if any(word in text for word in ('requested', 'change', 'clarif', 'address needed', 'not sent')):
        return 'changed'
    if p['state'] in CONFIRMED:
        return 'confirmed'
    if p['state'] == 'offered':
        return 'offered'
    return 'other'


def suburb(value):
    return re.sub(r'^\d{4}\s*', '', value or '').strip()


def nsw(p):
    code = str(p['postcode'] or '').strip()
    if not code:
        match = re.match(r'^\s*(\d{4})\b', p['suburb'] or '')
        code = match.group(1) if match else ''
    return bool(re.fullmatch(r'\d{4}', code) and (1000 <= int(code) <= 2599 or 2619 <= int(code) <= 2899 or 2921 <= int(code) <= 2999))


def rows(conn, start, end):
    return list(conn.execute("SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL AND visit_date BETWEEN ? AND ? AND state IN ('offered','confirmed','pathology_ready','sheet_ready','visited') ORDER BY visit_date, visit_time IS NULL, visit_time, id", (start, end)))


def summary(patients):
    times = [p['visit_time'] for p in patients if p['visit_time']]
    ends = [p['visit_end'] or p['visit_time'] for p in patients if p['visit_end'] or p['visit_time']]
    return {'total': len(patients), 'confirmed': sum(p['state'] in CONFIRMED for p in patients),
            'offered': sum(p['state'] == 'offered' for p in patients),
            'changed': sum(category(p) == 'changed' for p in patients),
            'first': min(times, default=None), 'last': max(ends, default=None),
            'suburbs': sorted({suburb(p['suburb']) for p in patients if suburb(p['suburb'])}, key=str.casefold),
            'nsw_count': sum(nsw(p) for p in patients)}


def listing(conn, start, end):
    days = {}
    for p in rows(conn, start, end):
        days.setdefault(p['visit_date'], []).append(p)
    result = []
    for day, patients in days.items():
        data = summary(patients)
        del data['nsw_count']
        result.append({'date': day, **data})
    return result


def plan(conn, day):
    row = conn.execute('SELECT * FROM day_plans WHERE date=?', (day,)).fetchone()
    saved = {key: (row[key] or '') if row else '' for key in ('start_time', 'start_place', 'end_place')}
    home = settings.get(conn, 'home_address').strip()
    defaults = {'start_time': settings.get(conn, 'day_start_time'), 'start_place': home,
                'end_place': settings.get(conn, 'end_address').strip() or home}
    return {'date': day, **{key: saved[key] or defaults[key] for key in saved},
            'defaults': {key: not bool(value) for key, value in saved.items()}}


def save_plan(conn, day, values):
    fields = ('start_time', 'start_place', 'end_place')
    if not isinstance(values, dict) or not set(values) <= set(fields):
        raise ValueError('invalid plan')
    row = conn.execute('SELECT * FROM day_plans WHERE date=?', (day,)).fetchone()
    saved = {key: (row[key] or '') if row else '' for key in fields}
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError('invalid ' + key)
        value = value.strip()
        if key == 'start_time' and value and not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
            raise ValueError('invalid start_time')
        saved[key] = value
    conn.execute('INSERT OR REPLACE INTO day_plans(date,start_time,start_place,end_place,updated_at) VALUES (?,?,?,?,?)',
                 (day, saved['start_time'], saved['start_place'], saved['end_place'], db.now()))
    return plan(conn, day)


def detail(conn, day):
    patients = rows(conn, day, day)
    groups = {}
    for p in patients:
        key = ('group', p['visit_group']) if p['visit_group'] else ('patient', p['id'])
        groups.setdefault(key, []).append(p)
    stops, seen, unknown = [], {}, set()
    for group in groups.values():
        p = group[0]
        area = suburb(p['suburb'])
        key = area.casefold()
        ll = None
        if key in C:
            k = seen.get(key, 0)
            seen[key] = k + 1
            lat, lon = C[key]
            ll = [lat + 0.0035 * ((k % 4) - 1.5), lon + 0.0045 * ((k // 4) - 0.5)]
        elif area:
            unknown.add(area)
        def joined(field):
            return '; '.join(dict.fromkeys(str(person[field]) for person in group if person[field]))
        categories = [category(person) for person in group]
        status = next((c for c in ('declined', 'changed', 'offered', 'other', 'confirmed') if c in categories), 'other')
        local_time = None
        if any(nsw(person) for person in group) and p['visit_time']:
            try:
                local = dt.datetime.fromisoformat(day + 'T' + p['visit_time']) + dt.timedelta(hours=db.utc_offset_hours('2000', dt.date.fromisoformat(day)) - 10)
                local_time = local.strftime('%H:%M')
            except ValueError:
                pass
        stops.append({'time': p['visit_time'], 'end': max((person['visit_end'] for person in group if person['visit_end']), default=None),
                      'names': [person['name'] for person in group], 'patient_ids': [person['id'] for person in group],
                      'status': status, 'status_text': joined('status_text'), 'suburb': area, 'address': joined('address'),
                      'phone': joined('phone'), 'gp': joined('gp'), 'referral_date': joined('referral_date'),
                      'note': joined('note'), 'nsw': any(nsw(person) for person in group), 'nsw_time': local_time, 'll': ll})
    for a in conn.execute('SELECT * FROM appointments WHERE date=? ORDER BY start,id', (day,)):
        stops.append({'id': a['id'], 'time': a['start'], 'end': a['end'], 'status': 'meeting',
                      'title': a['title'], 'place': a['place'], 'note': a['note'], 'll': coordinates(a['place'])})
    stops.sort(key=lambda s: (s['time'] is None, s['time'] or ''))
    return {'date': day, 'summary': summary(patients), 'home': HOME, 'plan': plan(conn, day), 'stops': stops,
            'unknown_suburbs': sorted(unknown, key=str.casefold)}


def period_summary(conn, start, end):
    keys = ('total', 'confirmed', 'waiting', 'declined', 'hold', 'not_sent')
    by_day = {}
    for p in conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL AND (visit_date BETWEEN ? AND ? OR offered_date BETWEEN ? AND ?)', (start, end, start, end)):
        held = p['state'] in ('hold', 'declined')
        day = (p['offered_date'] or p['visit_date']) if held else (p['visit_date'] or p['offered_date'])
        if not day or not start <= day <= end or (not held and p['visit_date'] and not p['visit_time']):
            continue
        counts = by_day.setdefault(day, dict.fromkeys(keys, 0))
        text = (p['status_text'] or '').lower()
        if 'not sent' in text:
            counts['not_sent'] += 1
            continue
        counts['total'] += 1
        if p['state'] == 'declined' or text.startswith('declined'):
            key = 'declined'
        elif p['state'] == 'hold' or not p['visit_date']:
            key = 'hold'
        elif p['state'] in CONFIRMED or text.startswith('confirmed'):
            key = 'confirmed'
        else:
            key = 'waiting'
        counts[key] += 1
    return {'days': [{'date': day, **counts} for day, counts in sorted(by_day.items())],
            'totals': {key: sum(row[key] for row in by_day.values()) for key in keys}}


def route(conn, day, include):
    stops, skipped = [], []
    for p in rows(conn, day, day):
        if p['state'] not in CONFIRMED and (include != 'all' or p['state'] != 'offered'):
            continue
        address = (p['address'] or '').strip()
        area = suburb(p['suburb'])
        if address and area and area.casefold() not in address.casefold():
            address += ', ' + area
        if address and p['postcode'] and str(p['postcode']) not in address:
            address += ' ' + str(p['postcode'])
        item = {'time': p['visit_time'], 'name': p['name'], 'patient_id': p['id'], 'address': address}
        if not address:
            skipped.append({**item, 'reason': 'missing address'})
        else:
            stops.append(item)
    for a in conn.execute('SELECT * FROM appointments WHERE date=? ORDER BY start,id', (day,)):
        item = {'time': a['start'], 'title': a['title'], 'appointment_id': a['id'], 'address': (a['place'] or '').strip()}
        if item['address']:
            stops.append(item)
        else:
            skipped.append({**item, 'reason': 'missing place'})
    stops.sort(key=lambda s: (s['time'] is None, s['time'] or ''))
    skipped.sort(key=lambda s: (s['time'] is None, s['time'] or ''))
    day_plan = plan(conn, day)
    start, end = day_plan['start_place'], day_plan['end_place']
    if not start or not end:
        raise ValueError('start and end places are required for a route')
    points = [start] + [s['address'] for s in stops] + [end]
    urls = []
    for i in range(0, len(points) - 1, 10):
        part = points[i:i + 11]
        params = {'api': 1, 'origin': part[0], 'destination': part[-1]}
        if len(part) > 2:
            params['waypoints'] = '|'.join(part[1:-1])
        params['travelmode'] = 'driving'
        urls.append('https://www.google.com/maps/dir/?' + urlencode(params))
    return {'urls': urls, 'stops': stops, 'skipped': skipped,
            'start': {'place': start, 'time': day_plan['start_time']}, 'end': {'place': end, 'time': None}}
