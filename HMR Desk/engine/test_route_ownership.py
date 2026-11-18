"""Responsibility boundaries for the local API (modelled on a domain-ownership test:
the boundary is enforced by a test that parses the source, not by a convention)."""
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

import api
import db

HERE = Path(__file__).resolve().parent
# api.py may only shrink. When code moves out, lower this number in the same change.
API_LINE_CEILING = 1199


def _tree(name):
    return ast.parse((HERE / name).read_text(encoding='utf-8'), filename=name)


def _route_literals(tree):
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')}


def test_api_module_does_not_grow():
    lines = len((HERE / 'api.py').read_text(encoding='utf-8').splitlines())
    assert lines <= API_LINE_CEILING, f'api.py has {lines} lines; extract to a route module instead'


def test_route_modules_do_not_import_the_facade():
    for name in ('routes_system.py',):
        for node in ast.walk(_tree(name)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert 'api' not in [m.split('.')[0] for m in modules], f'{name} imports api: that would be a cycle'


def test_each_route_has_one_owner():
    owned = _route_literals(_tree('routes_system.py'))
    assert {'/api/settings', '/api/backups/create', '/api/storage/status', '/api/records/status', '/api/medicines/search'} <= owned
    assert not (owned & _route_literals(_tree('api.py'))), 'a route is handled by both api.py and routes_system.py'


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 't.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    return db.connect()


# (method, path, body) -> literal (status, payload) recorded from the engine BEFORE the extraction.
CHARACTERIZATION = [
    ('POST', '/api/agents/delete', [], 400, {'error': 'invalid body'}),
    ('POST', '/api/agents/test', [], 400, {'error': 'invalid body'}),
    ('POST', '/api/templates/register', {}, 400, {'error': 'Invalid template registration request'}),
    ('POST', '/api/medicine-reference/install', {}, 400, {'error': 'Invalid medicine reference request'}),
    ('POST', '/api/medicines/suggest', {}, 400, {'error': 'Invalid suggestion request'}),
    ('POST', '/api/records/retire', {}, 400, {'error': 'Confirmation required'}),
    ('POST', '/api/records/export', {}, 400, {'error': 'invalid export input'}),
    ('POST', '/api/backups/create', {}, 400, {'error': 'invalid backup input'}),
    ('POST', '/api/backups/preview', {}, 400, {'error': 'invalid backup preview'}),
    ('POST', '/api/backups/validate-isolated', {}, 400, {'error': 'Invalid isolated recovery validation'}),
    ('POST', '/api/backups/restore', {}, 400, {'error': 'invalid restore input'}),
    ('POST', '/api/settings', {'no_such_setting': 'x'}, 400, {'error': 'unknown setting: no_such_setting'}),
    ('GET', '/api/nothing', None, 404, {'error': 'not found'}),
    ('PUT', '/api/settings', {}, 404, {'error': 'not found'}),
]


@pytest.mark.parametrize('method,path,body,status,payload', CHARACTERIZATION)
def test_system_routes_keep_their_responses(conn, method, path, body, status, payload):
    assert api.handle(conn, method, path, {}, body) == (status, payload)


def test_system_routes_keep_their_success_shapes(conn):
    s, r = api.handle(conn, 'GET', '/api/settings', {}, None); assert s == 200 and set(r) == {'settings'}
    s, r = api.handle(conn, 'GET', '/api/storage/status', {}, None); assert s == 200 and isinstance(r, dict)
    s, r = api.handle(conn, 'GET', '/api/records/status', {}, None); assert s == 200 and isinstance(r, dict)
    s, r = api.handle(conn, 'GET', '/api/medicines/search', {'q': ['x']}, None); assert s == 200
    s, r = api.handle(conn, 'GET', '/api/agents', {}, None); assert s == 200
