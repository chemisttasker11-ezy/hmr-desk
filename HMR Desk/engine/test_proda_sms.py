"""Synthetic-only PRODA endpoint tests; the fake gateway never sends SMS."""
import datetime as dt
import json
from pathlib import Path
import os
import tempfile
import sys
from unittest.mock import MagicMock, patch

import api
import db
import inbox
import importer
import proda_sms
import settings


# Synthetic registry: exercise local fallback without reading the real user's registry.
registry = MagicMock()
registry.REG_SZ = 1
registry.QueryValueEx.return_value = ('PRODA', registry.REG_SZ)
with patch.dict(sys.modules, {'winreg': registry}), patch.dict(os.environ, {}, clear=True):
    assert proda_sms._trusted_sender() == 'PRODA'
    registry.QueryValueEx.return_value = ('PRODA', 2)
    assert proda_sms._trusted_sender() is None
    registry.QueryValueEx.return_value = (123, registry.REG_SZ)
    assert proda_sms._trusted_sender() is None
    registry.QueryValueEx.return_value = ('bad\nsender', registry.REG_SZ)
    assert proda_sms._trusted_sender() is None
    registry.QueryValueEx.side_effect = FileNotFoundError()
    assert proda_sms._trusted_sender() is None
    registry.QueryValueEx.side_effect = PermissionError()
    assert proda_sms._trusted_sender() is None
    registry.QueryValueEx.side_effect = None
    registry.QueryValueEx.return_value = ('PRODA', registry.REG_SZ)
    with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': 'OTHER'}):
        assert proda_sms._trusted_sender() == 'OTHER'
    with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': ''}):
        assert proda_sms._trusted_sender() is None
    with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': 'bad\nsender'}):
        assert proda_sms._trusted_sender() is None
with patch.dict(sys.modules, {'winreg': None}), patch.dict(os.environ, {}, clear=True):
    assert proda_sms._trusted_sender() is None


class FakeGateway:
    def __init__(self):
        self.items = []
        self.calls = []
        self.error = False

    def get_inbox_page(self, since, limit, offset):
        self.calls.append((since, limit, offset))
        if self.error:
            raise RuntimeError('private SMS 123456')
        return self.items, len(self.items)

    def send_message(self, *args):
        raise AssertionError('must never send')


with tempfile.TemporaryDirectory() as tmp:
    with patch.dict(os.environ, {'HMR_DB': os.path.join(tmp, 'test.db'), 'HMR_PRODA_VERIFIED_SENDER': 'TRUSTED-SENDER'}), patch.object(db, 'BASE', tmp), patch.object(db, 'DATA_DIR', tmp):
        conn = db.connect()
        gateway = FakeGateway()
        now = [dt.datetime(2026, 11, 15, 1, 0, 0, tzinfo=dt.timezone.utc)]
        proda_sms._attempts.clear()
        proda_sms._used.clear()
        with patch.object(proda_sms, '_now', lambda: now[0]), patch.object(proda_sms.outbox, 'make_client', lambda: gateway):
            def call(action, body):
                return api.handle(conn, 'POST', '/api/auth/proda/' + action, {}, body)[1]
            def advance(seconds=3):
                now[0] += dt.timedelta(seconds=seconds)
            def start():
                result = call('start', {'origin': proda_sms.ORIGIN})
                assert result['status'] == 'started'
                return result['attempt_id']
            def message(id='one', sender='TRUSTED-SENDER', text='Your verification code is 123456', at=None):
                return {'id': id, 'type': 'SMS', 'sender': sender, 'contentPreview': text,
                        'createdAt': (at or now[0]).isoformat()}
            def poll(id): return call('poll', {'attempt_id': id})

            assert call('start', {}) == {'status': 'disabled'}
            settings.update(conn, {'proda_auto_sms_login': True})
            conn.commit()
            with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': ''}):
                assert call('start', {'origin': proda_sms.ORIGIN}) == {'status': 'unavailable'}
            assert call('start', {'origin': proda_sms.ORIGIN + '/'}) == {'status': 'unavailable'}
            assert call('start', {'since': '2000-01-01'}) == {'status': 'unavailable'}
            assert call('start', {'origin': proda_sms.ORIGIN, 'sender': 'OTHER'}) == {'status': 'unavailable'}
            assert api.handle(conn, 'POST', '/api/settings', {}, {'proda_verified_sender': 'OTHER'})[0] == 400
            first = start()
            with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': 'OTHER'}):
                assert poll(first) == {'status': 'unavailable'}
                assert not gateway.calls
            gateway.items = [message(at=now[0] - dt.timedelta(seconds=1)), message(id='future', at=now[0] + dt.timedelta(seconds=10))]
            assert poll(first) == {'status': 'waiting'}
            assert gateway.calls[-1][0] == '2026-11-15T01:00:00Z'
            gateway.items = [message()]
            assert poll(first) == {'status': 'waiting'} and len(gateway.calls) == 1
            advance()
            gateway.items = [message(sender='OTHER', text='Your verification code is 123456')]
            assert poll(first) == {'status': 'waiting'}
            advance()
            gateway.items = [message(sender='PRODA', text='PRODA login code 123456')]
            assert poll(first) == {'status': 'waiting'}
            advance()
            gateway.items = [message(sender='OTHER', text='PRODA login code 12345')]
            assert poll(first) == {'status': 'waiting'}
            advance()
            gateway.items = [message(text='PRODA login code 12345')]
            assert poll(first) == {'status': 'ambiguous'}
            advance()
            gateway.items = [message(), message(id='two', text='PRODA security code 234567')]
            assert poll(first) == {'status': 'ambiguous'}
            second = start()
            advance()
            gateway.items = [message(sender='OTHER', text='PRODA login code 123456')]
            assert poll(first) == {'status': 'waiting'}
            advance()
            gateway.items = [message(text='PRODA login code 123456')]
            assert poll(first) == {'status': 'code', 'code': '123456'}
            assert poll(second) == {'status': 'ambiguous'}
            assert call('finish', {'attempt_id': first, 'outcome': 'submitted'}) == {'status': 'finished'}
            assert poll(first) == {'status': 'expired'}
            third = start()
            assert call('finish', {'attempt_id': third, 'outcome': 'cancelled'}) == {'status': 'finished'}
            assert poll(third) == {'status': 'expired'}
            fourth = start()
            gateway.error = True
            assert poll(fourth) == {'status': 'unavailable'}
            advance(301)
            assert poll(fourth) == {'status': 'expired'}
            conn.execute("INSERT INTO patients(key,name,phone,state) VALUES (?,'Example','0400123456','offered')", (db.patient_key('Example'),))
            assert inbox.ingest(conn, 'trusted-blocked', 'TRUSTED-SENDER', 'Your verification code 123456', now[0].isoformat(), 'test') is None
            assert inbox.ingest(conn, 'blocked', '0400123456', 'PRODA verification code 123456', now[0].isoformat(), 'test') is None
            assert conn.execute("SELECT 1 FROM messages WHERE id='blocked'").fetchone() is None
            assert not proda_sms.is_proda_code('0400123456', 'My appointment is at 123456')
            # Unknown numeric senders may match a patient; neither ingestion path may retain a code.
            with patch.dict(os.environ, {'HMR_PRODA_VERIFIED_SENDER': ''}):
                for index, text in enumerate(('Your verification code is 123456', 'Your one-time passcode is 123456',
                                              'Your authentication PIN is 123456', 'Your OTP is 123456')):
                    assert proda_sms.is_proda_code('0400123456', text)
                    assert inbox.ingest(conn, f'private-{index}', '0400123456', text, now[0].isoformat(), 'test') is None
                base = Path(tmp) / 'import-fixture'
                sorting = base / 'TO SORT'
                sorting.mkdir(parents=True)
                (base / 'Appointment_Plan_1.json').write_text(json.dumps({'patients': []}), encoding='utf-8')
                (sorting / 'sms_replies_log.json').write_text(json.dumps([
                    {'name': 'Example', 'phone': '0400123456', 'inbox_id': 'import-private',
                     'text': 'Your one-time passcode is 123456', 'received': now[0].isoformat()},
                    {'name': 'Example', 'phone': '0400123456', 'inbox_id': 'import-normal',
                     'text': 'My appointment is at 123456', 'received': now[0].isoformat()},
                ]), encoding='utf-8')
                importer.run(conn, base)
                assert conn.execute("SELECT 1 FROM messages WHERE id='import-private'").fetchone() is None
                assert conn.execute("SELECT patient_id FROM messages WHERE id='import-normal'").fetchone()[0] == conn.execute("SELECT id FROM patients WHERE key=?", (db.patient_key('Example'),)).fetchone()[0]
                conn.execute("DELETE FROM messages WHERE id='import-normal'")
            conn.execute("DELETE FROM patients WHERE key=?", (db.patient_key('Example'),))
            assert all('123456' not in str(tuple(row)) for table in ('meta', 'messages', 'events', 'patients') for row in conn.execute('SELECT * FROM ' + table))
        conn.close()
