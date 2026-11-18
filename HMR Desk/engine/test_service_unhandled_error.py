"""An unexpected engine error must come back as a response, not a dropped connection.

Before this, any exception other than ValueError/TypeError escaped the request handler: the server
closed the socket without replying and the desktop app showed only "fetch failed". A locked database,
a KeyError or a library error all looked like a vanished engine.
"""
import http.client
import json
import logging
import sqlite3

import pytest

import api
import service
from test_service_empty_post import _server


def _get(port, path):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    conn.request('GET', path, headers={'X-HMR-Token': 'synthetic-token'})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data)


@pytest.mark.parametrize('error', [sqlite3.OperationalError('database is locked'), KeyError('secret-patient-field'), OSError('disk')])
def test_unexpected_error_returns_a_500_with_the_error_type_and_logs_it(tmp_path, monkeypatch, caplog, error):
    server, worker = _server(tmp_path, monkeypatch)
    def boom(*args, **kwargs): raise error
    monkeypatch.setattr(api, 'handle', boom)
    try:
        with caplog.at_level(logging.ERROR):
            status, payload = _get(server.server_port, '/api/patients/1/timeline')
        assert status == 500
        assert payload == {'error': 'The engine hit an internal error (%s). It was logged; reload and try again.' % type(error).__name__}
        assert 'GET /api/patients/:id failed (%s)' % type(error).__name__ in caplog.text
        assert 'secret-patient-field' not in caplog.text and 'secret-patient-field' not in json.dumps(payload)
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_the_next_request_still_works_after_an_error(tmp_path, monkeypatch):
    server, worker = _server(tmp_path, monkeypatch)
    real = api.handle
    calls = []
    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1: raise sqlite3.OperationalError('database is locked')
        return real(*args, **kwargs)
    monkeypatch.setattr(api, 'handle', flaky)
    try:
        assert _get(server.server_port, '/api/settings')[0] == 500
        assert _get(server.server_port, '/api/settings')[0] == 200
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_logged_route_shape_masks_identifiers_and_drops_the_query():
    assert service.route_shape('/api/patients/12/timeline') == '/api/patients/:id'
    assert service.route_shape('/api/days/2026-11-18/plan') == '/api/days/:id'
    assert service.route_shape('/api/messages/Jane Smith/approve') == '/api/messages/:id'
    assert service.route_shape('/api/settings') == '/api/settings'
