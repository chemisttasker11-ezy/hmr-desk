"""Offline engine checks; the gateway is always a fake."""
import datetime
import io
import json
import os
import tempfile
from types import SimpleNamespace

import db
import inbox
import outbox
import service


class Fake:
    def __init__(self, status=None, error=None):
        self.status, self.error, self.sent = status, error, []

    def get_message_status(self, id_):
        if isinstance(self.status, Exception):
            raise self.status
        return {'state': self.status}

    def send_message(self, id_, text, recipient, sim):
        self.sent.append(id_)
        if self.error:
            raise self.error
        return {'state': 'Pending'}


with tempfile.TemporaryDirectory() as tmp:
    os.environ['HMR_DB'] = os.path.join(tmp, 'test.db')
    db.BASE = tmp
    conn = db.connect()
    cfg = {'test_number': '+61412345678', 'sim_number': 1}
    inbox.outbox.config = lambda: cfg
    when = datetime.datetime(2026, 11, 11, 12)
    conn.execute("INSERT INTO patients (key,name,phone,postcode,state,visit_date) VALUES ('a','A','0412345678','4216','offered','2026-11-12')")
    id_ = outbox.queue(conn, '0412345678', 'one', 'offer', 1)
    try:
        outbox.queue(conn, '0412345678', 'one', 'offer', 1)
        assert False
    except ValueError:
        pass
    conn.execute("UPDATE messages SET state='unknown' WHERE id=?", (id_,))
    conn.commit()
    fake = Fake(outbox.BridgeHTTPError(404))
    outbox.process(conn, fake, cfg, when)
    assert fake.sent == [id_]
    conn.execute("UPDATE messages SET state='unknown' WHERE id=?", (id_,))
    conn.commit()
    fake = Fake('Delivered')
    outbox.process(conn, fake, cfg, when)
    assert not fake.sent and conn.execute('SELECT state FROM messages WHERE id=?', (id_,)).fetchone()[0] == 'Delivered'
    second = outbox.queue(conn, '0412345678', 'two', 'test', 1)
    outbox.process(conn, Fake(error=outbox.BridgeNetworkError('offline')), cfg, when)
    assert conn.execute('SELECT state FROM messages WHERE id=?', (second,)).fetchone()[0] == 'unknown'
    conn.execute("UPDATE patients SET postcode='2486' WHERE id=1")
    third = outbox.queue(conn, '0412345678', 'three', 'test', 1)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('outbox_mode','live')")
    other = outbox.queue(conn, '0412345679', 'four', 'test')
    conn.execute("UPDATE meta SET value='test' WHERE key='outbox_mode'")
    fake = Fake('Delivered')
    outbox.process(conn, fake, cfg, datetime.datetime(2026, 11, 11, 19, 30))
    assert third not in fake.sent and other not in fake.sent
    assert inbox.ingest(conn, 'in1', '0412345678', 'yes', '2026-11-11T00:00:00Z', 'test')
    assert conn.execute('SELECT state FROM patients WHERE id=1').fetchone()[0] == 'confirmed'
    assert not inbox.ingest(conn, 'in1', '0412345678', 'yes', '2026-11-11T00:00:00Z', 'test')
    assert not inbox.ingest(conn, 'in2', '0412345678', 'yes', '2026-11-11T00:01:00Z', 'test')
    assert inbox.ingest(conn, 'in3', '0412345678', 'no thanks', '2026-11-11T00:03:00Z', 'test')
    assert conn.execute('SELECT state FROM patients WHERE id=1').fetchone()[0] == 'confirmed'
    assert not inbox.ingest(conn, 'stranger', '0411111111', 'yes', '2026-11-11T00:00:00Z', 'test')
    conn.execute("UPDATE patients SET state='offered' WHERE id=1")
    assert inbox.ingest(conn, 'in4', '0412345678', 'perhaps', '2026-11-11T00:04:00Z', 'test')
    assert conn.execute('SELECT status_text FROM patients WHERE id=1').fetchone()[0] == 'Reply received - clarification needed'
    assert inbox.ingest(conn, 'in5', '0412345678', 'no thanks', '2026-11-11T00:06:00Z', 'test')
    patient = conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
    assert patient['state'] == 'declined' and not patient['visit_date'] and patient['offered_date'] == '2026-11-12'
    assert inbox.handle_webhook(conn, {'event': 'sms:delivered', 'payload': {'messageId': third}}) == 'updated'
    assert conn.execute('SELECT state FROM messages WHERE id=?', (third,)).fetchone()[0] == 'Delivered'
    payload = json.dumps({'event': 'sms:delivered', 'payload': {'messageId': other}}).encode()
    def webhook(path):
        handler = object.__new__(service.HookHandler)
        handler.path = path
        handler.server = SimpleNamespace(token='secret')
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        codes = []
        handler.send_response = lambda code: codes.append(code)
        handler.send_error = lambda code: codes.append(code)
        handler.end_headers = lambda: None
        handler.do_POST()
        return codes
    assert webhook('/hook/wrong') == [404]
    assert webhook('/hook/secret') == [200]
    assert conn.execute('SELECT state FROM messages WHERE id=?', (other,)).fetchone()[0] == 'Delivered'
    # the sending window is a switch: off lets an NSW patient's message go at 19:30 Queensland time
    conn.execute("INSERT INTO patients (key,name,phone,postcode,state) VALUES ('n','N','0412345678','2486','offered')")
    nsw = outbox.queue(conn, '0412345678', 'window test', 'test', conn.execute("SELECT id FROM patients WHERE key='n'").fetchone()[0])
    fake = Fake('Delivered'); outbox.process(conn, fake, cfg, datetime.datetime(2026, 11, 11, 19, 30))
    assert nsw not in fake.sent
    conn.execute("INSERT INTO meta VALUES ('sending_window','off')"); conn.commit()
    fake = Fake('Delivered'); outbox.process(conn, fake, cfg, datetime.datetime(2026, 11, 11, 19, 30))
    assert nsw in fake.sent
    conn.execute("DELETE FROM meta WHERE key='sending_window'"); conn.execute("DELETE FROM patients WHERE key='n'"); conn.commit()
    # imported history is never (re)sent, even when its status is unknown and the phone has no record of it
    conn.execute("INSERT INTO messages (id,patient_id,direction,body,kind,state,recipient,created_at,source) VALUES ('d-old',NULL,'out','old','offer','unknown','+61412345678','2026-11-09','sms_offers_x.json')")
    conn.execute("INSERT INTO messages (id,patient_id,direction,body,kind,state,recipient,created_at,source) VALUES ('d-old2',NULL,'out','old2','offer','queued','+61412345678','2026-11-09','sms_offers_x.json')")
    conn.commit()
    fake = Fake(outbox.BridgeHTTPError(404))
    outbox.process(conn, fake, cfg, when)
    assert 'd-old' not in fake.sent and 'd-old2' not in fake.sent
    # a "decline" from a patient with a confirmed visit is flagged, not acted on
    conn.execute("INSERT INTO patients (key,name,phone,postcode,state,visit_date) VALUES ('b','B','0422222222','4216','sheet_ready','2026-11-12')")
    assert inbox.ingest(conn, 'in6', '0422222222', 'decline', '2026-11-11T01:00:00Z', 'test')
    b = conn.execute("SELECT * FROM patients WHERE key='b'").fetchone()
    assert b['state'] == 'sheet_ready' and b['visit_date'] and b['status_text'].startswith('Confirmed')
    # two patients on one number: the reply is kept but never acted on automatically
    conn.execute("INSERT INTO patients (key,name,phone,postcode,state,visit_date) VALUES ('c','C','0433333333','4216','offered','2026-11-12')")
    conn.execute("INSERT INTO patients (key,name,phone,postcode,state,visit_date) VALUES ('d','D','0433 333 333','4216','offered','2026-11-12')")
    row = inbox.ingest(conn, 'in7', '+61433333333', 'yes', '2026-11-11T02:00:00Z', 'test')
    assert row and row['kind'] == 'OTHER'
    assert [r[0] for r in conn.execute("SELECT state FROM patients WHERE key IN ('c','d')")] == ['offered', 'offered']
    # the same reply seen again with different line breaks / time zone notation is one reply
    conn.execute("INSERT INTO messages (id,patient_id,direction,body,kind,state,created_at,source) VALUES ('legacy1',1,'in','Thats ok See you at 12.00','OTHER','received','2026-11-11T11:03:00.000+10:00','sms_replies_log.json')")
    assert not inbox.ingest(conn, 'gw-77', '0412345678', 'Thats ok\nSee you at 12.00 ', '2026-11-11T01:03:26Z', 'poll')
    conn.close()
print('engine self-check ok')
