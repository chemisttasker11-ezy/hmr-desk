"""Calendar and day-planning routes: appointments, period summary, day plans and routes, attention list, today.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import datetime as dt
import re

import db
import jobs
import settings
import steps
from followup_schedule import patient_followups
from patient_actions import clock, date, referral_expiry


def handle(conn, method, path, query, body):
    if method == 'GET' and path in ('/api/summary', '/api/appointments'):
        def range_date(name):
            value = query.get(name)
            if isinstance(value, list):
                if len(value) != 1: raise ValueError('invalid date')
                value = value[0]
            return date(value)
        start, end = range_date('from'), range_date('to')
        if end < start or (path == '/api/summary' and (end - start).days >= 93): raise ValueError('invalid date range')
        if path == '/api/summary':
            import days
            return 200, days.period_summary(conn, str(start), str(end))
        return 200, {'appointments': [dict(row) for row in conn.execute('SELECT * FROM appointments WHERE date BETWEEN ? AND ? ORDER BY date,start,id', (str(start), str(end)))]}
    if method == 'POST' and path == '/api/appointments' and isinstance(body, dict):
        date(body.get('date'))
        start, end = clock(body.get('start')), clock(body.get('end'))
        if end <= start: raise ValueError('end must be after start')
        title = body.get('title')
        if not isinstance(title, str) or not title.strip(): raise ValueError('title required')
        place, note = body.get('place', ''), body.get('note', '')
        if not isinstance(place, str) or not isinstance(note, str): raise ValueError('invalid place or note')
        values = (body['date'], body['start'], body['end'], title.strip(), place.strip(), note)
        if 'id' in body:
            if type(body['id']) is not int or body['id'] <= 0: raise ValueError('invalid id')
            result = conn.execute('UPDATE appointments SET date=?,start=?,end=?,title=?,place=?,note=? WHERE id=?', (*values, body['id']))
            if not result.rowcount: return 404, {'error': 'appointment not found'}
            ident = body['id']
        else:
            ident = conn.execute('INSERT INTO appointments(date,start,end,title,place,note,created_at) VALUES (?,?,?,?,?,?,?)', (*values, db.now())).lastrowid
        conn.commit()
        return 200, dict(conn.execute('SELECT * FROM appointments WHERE id=?', (ident,)).fetchone())
    match = re.fullmatch(r'/api/appointments/(\d+)/delete', path)
    if method == 'POST' and match:
        result = conn.execute('DELETE FROM appointments WHERE id=?', (int(match[1]),))
        conn.commit()
        return (200, {'ok': True}) if result.rowcount else (404, {'error': 'appointment not found'})
    match = re.fullmatch(r'/api/days/([^/]+)/plan', path)
    if match and method in ('GET', 'POST'):
        import days
        day = date(match[1]).isoformat()
        if method == 'GET': return 200, days.plan(conn, day)
        result = days.save_plan(conn, day, body); conn.commit(); return 200, result
    match = re.fullmatch(r'/api/days/([^/]+)/route', path)
    if method == 'GET' and match:
        import days
        day = date(match[1]).isoformat()
        include = query.get('include', 'confirmed')
        if isinstance(include, list):
            if len(include) != 1: raise ValueError('invalid include')
            include = include[0]
        if include not in ('confirmed', 'all'): raise ValueError('invalid include')
        return 200, days.route(conn, day, include)
    if method == 'GET' and path == '/api/days':
        import days
        def parameter(name):
            value = query.get(name)
            if isinstance(value, list):
                if len(value) != 1: raise ValueError('invalid date')
                value = value[0]
            return date(value)
        start, end = parameter('from'), parameter('to')
        if end < start or (end - start).days >= 62: raise ValueError('invalid date range')
        return 200, days.listing(conn, start.isoformat(), end.isoformat())
    if method == 'GET' and path.startswith('/api/days/'):
        import days
        day = date(path[len('/api/days/'):]).isoformat()
        return 200, days.detail(conn, day)
    if method == 'GET' and path == '/api/attention':
        import lifecycle
        return 200, lifecycle.attention(conn)
    if method == 'GET' and path == '/api/today':
        today = dt.date.today()
        visits = [dict(p) for p in conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL AND visit_date IN (?,?) ORDER BY visit_date,visit_time', (str(today), str(today+dt.timedelta(days=1))))]
        alerts = []
        for p in conn.execute('SELECT * FROM patients WHERE is_test=0 AND archived_at IS NULL'):
            follow = patient_followups(conn, p['id'])
            if follow:
                for kind in follow['alerts']:
                    alerts.append({'id': p['id'], 'name': p['name'], 'type': kind, 'date': follow['window_end'] if kind.startswith('follow-up') else follow['new_hmr'], 'window_end': follow['window_end'] if kind.startswith('follow-up') else None})
            if p['state'] in ('confirmed','pathology_ready','sheet_ready'):
                for field, label in [('has_pathology','missing pathology'), ('has_sheet','missing interview sheet')]:
                    if not p[field] and (field != 'has_pathology' or not steps.done('pathology', conn, p)): alerts.append({'id': p['id'], 'name': p['name'], 'type': label})
            if p['referral_date'] and p['state'] in db._PRE:
                expiry = referral_expiry(conn, p['referral_date'])
                if expiry:
                    remaining = (expiry-today).days
                    if remaining <= settings.get(conn, 'referral_warn_days'):
                        alerts.append({'id': p['id'], 'name': p['name'], 'type': 'referral expired' if remaining < 0 else 'referral expires', 'date': str(expiry), 'days_left': remaining})
        return 200, {'visits': visits, 'alerts': alerts}
    return None
