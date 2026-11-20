"""The local API answers 500 instead of dropping the connection when it fails before replying (synthetic)."""
import http.client
import threading

import db
import service


def serve():
    server = service.http.server.ThreadingHTTPServer(('127.0.0.1', 0), service.QuietStatic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_database_open_failure_gets_a_500_reply_not_a_dropped_connection(monkeypatch):
    def boom(*a, **k):
        raise OSError('database is locked')
    monkeypatch.setattr(db, 'connect', boom)
    server = serve()
    try:
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        conn.request('GET', '/api/patients', headers={'X-HMR-Token': 'x'})
        response = conn.getresponse()
        body = response.read().decode()
        assert response.status == 500
        assert 'OSError' in body and 'locked' not in body  # error type only, never the message
    finally:
        server.shutdown(); server.server_close()


def test_backlog_is_larger_than_the_default():
    assert service.API_BACKLOG >= 32
