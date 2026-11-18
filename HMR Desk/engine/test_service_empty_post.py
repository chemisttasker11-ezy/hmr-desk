"""Local API service must accept legitimate empty-body POSTs and keep size/auth safeguards."""
import http.client
import http.server
import json
import threading

import db
import service


def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'userdata' / 'test.db'))
    conn = db.connect()
    with conn:
        service.set_meta(conn, 'api_token', 'synthetic-token')
        conn.execute("INSERT INTO patients(key,name,state,folder) VALUES (?,?,?,?)",
                     ('synthetic', 'Synthetic Patient', 'visited', 'synthetic'))
    conn.close()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), service.QuietStatic)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _post(port, path, token='synthetic-token', body=None, content_type='application/json', raw_length=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'X-HMR-Token': token}
    if content_type is not None:
        headers['Content-Type'] = content_type
    if raw_length is not None:
        headers['Content-Length'] = str(raw_length)
    conn.request('POST', path, body=body, headers=headers)
    response = conn.getresponse()
    payload = json.loads(response.read())
    conn.close()
    return response.status, payload


def test_empty_body_post_reaches_the_route(tmp_path, monkeypatch):
    server, worker = _server(tmp_path, monkeypatch)
    try:
        # The desktop report Refresh posts exactly this: JSON content type, no body.
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh')
        assert payload.get('error') != 'invalid length', payload
        # The route itself ran: this patient has no report spec yet.
        assert (status, payload) == (400, {'error': 'report spec does not exist'})
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_body_size_cap_and_content_type_and_auth_survive(tmp_path, monkeypatch):
    server, worker = _server(tmp_path, monkeypatch)
    try:
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh',
                                body=b' ' * 65537)
        assert (status, payload) == (400, {'error': 'invalid length'})
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh',
                                body=b'{}', content_type='text/plain')
        assert (status, payload) == (400, {'error': 'Content-Type must be application/json'})
        # Authentication still precedes any body handling, including empty bodies.
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh', token='wrong')
        assert status == 403
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh',
                                token='wrong', body=b'{}')
        assert status == 403
        # A JSON-object body still parses normally.
        status, payload = _post(server.server_port, '/api/patients/1/report/refresh', body=b'{}')
        assert payload.get('error') != 'invalid length', payload
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)
