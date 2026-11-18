"""Pre-sign-off part of test_api.py (everything before the first signed_off call).

The rest of that script calls signed_off, which needs an approved report pair; it stays excluded from the runner
(see test_legacy_scripts.py) and is not counted as passing."""
"""Offline API checks using synthetic patients and a temporary database."""
import csv
import datetime as dt
import functools
import http.server
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

import api
import db
import service
import jobs
import steps
from openpyxl import load_workbook

with tempfile.TemporaryDirectory() as tmp:
    os.environ['HMR_DB'] = os.path.join(tmp, 'test.db')
    db.BASE = tmp
    db.DATA_DIR = tmp
    conn = db.connect()
    conn.execute("INSERT INTO tasks(id,step,state,created) VALUES ('dead','intake_dry','running','now')")
    conn.commit()
    jobs.ensure_worker(recover=True)
    assert jobs.get('dead')['state'] == 'failed' and jobs.get('dead')['output'] == 'interrupted'
    os.makedirs(os.path.join(tmp, 'Scheduled', 'Alex Example', 'Pathology'))
    conn.execute("INSERT INTO patients (key,name,state,folder,dob,sex) VALUES ('alex example','Alex Example','offered',?,'1943-06-25','F')", (os.path.join('Scheduled','Alex Example'),))
    conn.commit()
    def call(method, path, body=None, query=None):
        return api.handle(conn, method, path, query or {}, body)
    def act(name, **fields):
        return call('POST', '/api/patients/1/action', {'action': name, **fields})
    today = dt.date.today()
    for age, expected in [(59, None), (60, 'referral expires'), (90, 'referral expires'), (91, 'referral expired')]:
        referral = (today - dt.timedelta(days=age)).isoformat()
        conn.execute('UPDATE patients SET referral_date=? WHERE id=1', (referral,)); conn.commit()
        alerts = [a for a in call('GET', '/api/today')[1]['alerts'] if a['type'].startswith('referral')]
        assert (alerts[0]['type'] if alerts else None) == expected
        if alerts: assert alerts[0]['days_left'] == 90 - age
        expiry = (today + dt.timedelta(days=90-age)).isoformat()
        assert call('GET', '/api/patients/1')[1]['referral_expiry'] == expiry
        assert call('GET', '/api/patients')[1]['patients'][0]['referral_expiry'] == expiry
    conn.execute("INSERT INTO meta(key,value) VALUES ('referral_valid_days','120')")
    assert api.referral_expiry(conn, '2026-01-01') == dt.date(2026, 5, 1)
    conn.execute("DELETE FROM meta WHERE key='referral_valid_days'")
    conn.execute('UPDATE patients SET referral_date=NULL WHERE id=1'); conn.commit()
    assert len(call('GET','/api/patients',query={'q':'Example'})[1]['patients']) == 1
    assert not call('GET','/api/patients',query={'state':'new'})[1]['patients']
    assert call('GET','/api/patients/1')[1]['files'] == {'folder': [], 'pathology': []}
    assert act('claimed', date='2026-01-01')[0] == 400
    assert act('move', date='2026-12-01', time='09:00', end='10:00') == (400, {'error': 'move needs a booked visit'})
    assert act('book_phone', date='2026-12-01', time='08:00', end='09:00')[0] == 400
    assert act('book_phone', date='bad', time='09:00', end='10:00')[0] == 400
    assert act('book_phone', date='2026-12-01', time='09:00', end='10:00')[0] == 200
    assert act('move', date='2026-12-02', time='10:00', end='11:00')[0] == 200
    queue = call('GET','/api/pathology/queue')[1]['patients']
    assert len(queue) == 1 and queue[0]['last'] == 'Example' and queue[0]['dob'] == '25-Jun-1943' and queue[0]['medicare'] is None
    assert call('POST','/api/pathology/result', {'id':1,'status':'saved','saved':['x.pdf'],'irn':'1','medicare10':''})[0] == 200
    assert not call('GET','/api/pathology/queue')[1]['patients']
    assert act('update', fields={'phone':'0400000000'})[0] == 200
    assert act('update', fields={'state':'claimed'})[0] == 400
    assert act('note', text='hello')[0] == 200
    assert call('GET','/api/patients/1')[1]['note'] == 'hello'
    assert act('visited', date='2026-01-01')[0] == 200

    conn.close()  # the full script closes it at its end; Windows cannot delete the temp folder while the database file is open

print('api pre-sign-off checks passed')
