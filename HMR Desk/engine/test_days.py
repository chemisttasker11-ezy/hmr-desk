"""Offline day calendar checks with a temporary database."""
import os
import tempfile
from urllib.parse import parse_qs, urlparse
import api
import db

with tempfile.TemporaryDirectory() as tmp:
    db.BASE = tmp
    conn = db.connect(os.path.join(tmp, 'days.db'))
    data = [
        ('a', 'Alex', 'confirmed', 'Confirmed', '09:00', '09:40', 'couple', '2486 Banora Point', '2486'),
        ('b', 'Bea', 'pathology_ready', 'Clarification needed', '09:00', '09:40', 'couple', 'Banora Point', '2486'),
        ('c', 'Cal', 'offered', 'Offer sent', '10:00', '10:20', None, 'Banora Point', '2486'),
        ('d', 'Dee', 'visited', 'Confirmed', '11:00', '11:20', None, 'Mystery', '4216'),
        ('e', 'Eve', 'hold', 'Hold', '12:00', '12:20', None, 'Arundel', '4214'),
    ]
    for key, name, state, status, start, end, group, area, postcode in data:
        conn.execute('INSERT INTO patients (key,name,state,status_text,visit_date,visit_time,visit_end,visit_group,suburb,postcode) VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (key, name, state, status, '2026-11-12', start, end, group, area, postcode))
    def call(path, query=None):
        return api.handle(conn, 'GET', path, query or {}, None)
    status, listing = call('/api/days', {'from': ['2026-11-01'], 'to': ['2026-11-30']})
    assert status == 200 and len(listing) == 1
    assert {k: listing[0][k] for k in ('total', 'confirmed', 'offered', 'changed', 'first', 'last')} == {
        'total': 4, 'confirmed': 3, 'offered': 1, 'changed': 1, 'first': '09:00', 'last': '11:20'}
    status, day = call('/api/days/2026-11-12')
    assert status == 200 and day['summary']['nsw_count'] == 3
    assert len(day['stops']) == 3 and day['stops'][0]['names'] == ['Alex', 'Bea']
    assert day['stops'][0]['patient_ids'] == [1, 2] and day['stops'][0]['status'] == 'changed'
    assert day['stops'][0]['nsw'] and day['stops'][0]['nsw_time'] == '10:00'
    assert day['stops'][0]['ll'] != day['stops'][1]['ll']
    assert day['stops'][2]['ll'] is None and day['unknown_suburbs'] == ['Mystery']
    assert call('/api/days', {'from': '2026-01-01', 'to': '2026-03-03'})[0] == 200
    assert call('/api/days', {'from': '2026-01-01', 'to': '2026-03-04'})[0] == 400
    assert call('/api/days/invalid')[0] == 400
    def post(path, body):
        return api.handle(conn, 'POST', path, {}, body)
    plan_path = '/api/days/2026-11-12/plan'
    default_plan = {'date': '2026-11-12', 'start_time': '08:30', 'start_place': '',
                    'end_place': '',
                    'defaults': {'start_time': True, 'start_place': True, 'end_place': True}}
    assert call(plan_path) == (200, default_plan)
    assert day['plan'] == default_plan
    listed = {item['key']: item for item in call('/api/settings')[1]['settings']}
    assert listed['home_address']['label'] == 'Home address / start location'
    assert listed['day_start_time']['type'] == 'time' and listed['end_address']['value'] == ''
    assert post('/api/settings', {'home_address': 'Home', 'end_address': 'Office', 'day_start_time': '07:15'})[0] == 200
    status, default = call(plan_path)
    assert (default['start_time'], default['start_place'], default['end_place']) == ('07:15', 'Home', 'Office')
    route = call('/api/days/2026-11-12/route')[1]
    assert route['start'] == {'place': 'Home', 'time': '07:15'} and route['end'] == {'place': 'Office', 'time': None}
    query = parse_qs(urlparse(route['urls'][0]).query)
    assert query['origin'] == ['Home'] and query['destination'] == ['Office']
    overrides = {'start_time': '09:30', 'start_place': 'Clinic', 'end_place': 'Hotel'}
    status, saved = post(plan_path, overrides)
    assert status == 200 and all(saved[k] == v for k, v in overrides.items())
    assert saved['defaults'] == dict.fromkeys(overrides, False)
    assert call('/api/days/2026-11-12')[1]['plan'] == saved
    route = call('/api/days/2026-11-12/route')[1]
    query = parse_qs(urlparse(route['urls'][0]).query)
    assert query['origin'] == ['Clinic'] and query['destination'] == ['Hotel']
    assert route['start']['time'] == '09:30' and route['end']['place'] == 'Hotel'
    assert post(plan_path, {'end_place': ''})[1]['end_place'] == 'Office'
    for bad in ({'start_time': '24:00'}, {'start_time': '9:30'}, {'start_place': 'x' * 201},
                {'end_place': None}, {'extra': ''}, []):
        assert post(plan_path, bad)[0] == 400
    assert post('/api/days/2026-02-30/plan', {})[0] == 400
    assert call('/api/days/invalid/plan')[0] == 400
    assert post('/api/settings', {'day_start_time': '08:60'})[0] == 400
    conn.close()
print('day calendar checks passed')
