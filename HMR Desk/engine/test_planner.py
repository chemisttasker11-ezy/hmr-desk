"""Offline planner checks with synthetic records and isolated files."""
import datetime as dt
import json
import os
import tempfile
from urllib.parse import parse_qs, urlparse

import api
import db
import settings

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    today = dt.date.today()
    day = str(today + dt.timedelta(days=10))
    past = str(today - dt.timedelta(days=1))
    plan = os.path.join(tmp, 'Appointment_Plan_1.json')
    with open(plan, 'w', encoding='utf-8') as f:
        json.dump({'meetings': [[day, '08:30', '09:00', 'Estia Robina'],
                                [day, '08:30', '09:00', 'Estia Robina'],
                                [past, '08:00', '09:00', 'Past']]}, f)
    path = os.path.join(tmp, 'planner.db')
    conn = db.connect(path)
    # Routes need a start place (home_address has no default now), so the fixture sets one; the end place falls back to it.
    HOME = 'Test Home, Robina QLD 4226'
    settings.update(conn, {'home_address': HOME}); conn.commit()
    assert conn.execute('SELECT count(*) FROM appointments').fetchone()[0] == 1
    meeting = conn.execute('SELECT * FROM appointments').fetchone()
    assert meeting['title'] == 'Estia Robina' and meeting['place'] == 'robina'
    conn.execute('DELETE FROM appointments'); conn.commit(); conn.close()
    conn = db.connect(path)
    assert conn.execute('SELECT count(*) FROM appointments').fetchone()[0] == 0
    def call(method, path, body=None, query=None):
        return api.handle(conn, method, path, query or {}, body)
    query = {'from': day, 'to': day}
    body = {'date': day, 'start': '09:00', 'end': '10:00', 'title': 'Meeting', 'place': '1 Road, Robina QLD 4226', 'note': 'note'}
    status, a = call('POST', '/api/appointments', body)
    assert status == 200
    ident = a['id']
    assert call('GET', '/api/appointments', query=query)[1]['appointments'][0]['id'] == ident
    assert call('POST', '/api/appointments', {**body, 'id': ident, 'title': 'Updated'})[1]['title'] == 'Updated'
    for change in ({'date': '2026-02-30'}, {'start': '25:00'}, {'end': '09:00'}, {'title': ' '}):
        assert call('POST', '/api/appointments', {**body, **change})[0] == 400
    stop = call('GET', '/api/days/' + day)[1]['stops'][0]
    assert stop['status'] == 'meeting' and stop['title'] == 'Updated' and stop['ll'] is not None
    assert call('POST', f'/api/appointments/{ident}/delete')[0] == 200
    assert call('POST', f'/api/appointments/{ident}/delete')[0] == 404
    assert not call('GET', '/api/appointments', query=query)[1]['appointments']
    records = [
        ('confirmed', 'Confirmed', day, '10:00', None, '1 Main St', 0),
        ('offered', 'Offer sent', day, '11:00', None, '2 Main St', 0),
        ('declined', 'Declined', None, None, day, None, 0),
        ('hold', 'Hold', None, None, day, None, 0),
        ('pooled', 'NOT SENT', day, '12:00', None, None, 0),
        ('confirmed', 'Confirmed', day, '13:00', None, None, 1),
    ]
    for i, (state, status, date, time, offered, address, test) in enumerate(records):
        conn.execute('INSERT INTO patients(key,name,state,status_text,visit_date,visit_time,offered_date,address,suburb,postcode,is_test) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (str(i), str(i), state, status, date, time, offered, address, 'Robina', '4226', test))
    expected = {'total': 4, 'confirmed': 1, 'waiting': 1, 'declined': 1, 'hold': 1, 'not_sent': 1}
    result = call('GET', '/api/summary', query=query)[1]
    assert result['totals'] == expected and result['days'] == [{'date': day, **expected}]
    assert call('GET', '/api/summary', query={'from': day, 'to': str(today + dt.timedelta(days=103))})[0] == 400
    assert call('GET', '/api/summary', query={'from': day, 'to': str(today + dt.timedelta(days=102))})[0] == 200
    call('POST', '/api/appointments', {**body, 'place': ''})
    call('POST', '/api/appointments', {**body, 'start': '09:30', 'place': 'A & B, Robina'})
    conn.execute("INSERT INTO patients(key,name,state,visit_date,visit_time,address) VALUES ('missing','Missing','confirmed',?,'14:00',NULL)", (day,))
    for i in range(10):
        conn.execute("INSERT INTO patients(key,name,state,visit_date,visit_time,address) VALUES (?,?,'confirmed',?,?,?)", (f'extra{i}', f'extra{i}', day, f'{15+i//6:02}:{i%6}0', f'{i} Test St'))
    conn.commit()
    result = call('GET', '/api/days/' + day + '/route', query={'include': 'all'})[1]
    assert len(result['urls']) == 2 and len(result['skipped']) == 2
    assert [s['time'] for s in result['stops']] == sorted(s['time'] for s in result['stops'])
    first, second = [parse_qs(urlparse(url).query) for url in result['urls']]
    assert first['origin'] == [HOME] and second['destination'] == first['origin']
    assert first['destination'] == second['origin'] and len(first['waypoints'][0].split('|')) == 9
    assert first['waypoints'][0].split('|')[0] == 'A & B, Robina' and '%26' in result['urls'][0]
    confirmed = call('GET', '/api/days/' + day + '/route')[1]
    assert not any(s.get('name') == '1' for s in confirmed['stops'])
    assert call('GET', '/api/days/' + day + '/route', query={'include': 'bad'})[0] == 400
    conn.close()
print('planner checks passed')
