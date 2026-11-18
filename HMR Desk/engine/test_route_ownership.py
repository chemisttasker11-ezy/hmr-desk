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
API_LINE_CEILING = 252


def _tree(name):
    return ast.parse((HERE / name).read_text(encoding='utf-8'), filename=name)


def _route_literals(tree):
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')}


def test_api_module_does_not_grow():
    lines = len((HERE / 'api.py').read_text(encoding='utf-8').splitlines())
    assert lines <= API_LINE_CEILING, f'api.py has {lines} lines; extract to a route module instead'


def test_route_modules_do_not_import_the_facade():
    for name in ('routes_system.py', 'routes_work.py', 'routes_schedule.py', 'routes_pathology.py', 'routes_report.py', 'routes_clinical_records.py', 'routes_messages.py', 'routes_reference.py', 'routes_followup.py', 'routes_medicines.py', 'medicine_review.py', 'external_helpers.py', 'patient_actions.py', 'followup_schedule.py'):
        for node in ast.walk(_tree(name)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert 'api' not in [m.split('.')[0] for m in modules], f'{name} imports api: that would be a cycle'


def test_each_route_has_one_owner():
    owned = _route_literals(_tree('routes_system.py'))
    assert {'/api/settings', '/api/backups/create', '/api/storage/status', '/api/records/status', '/api/medicines/search'} <= owned
    assert not (owned & _route_literals(_tree('api.py'))), 'a route is handled by both api.py and routes_system.py'


def test_each_work_route_has_one_owner():
    owned = _route_literals(_tree('routes_work.py'))
    assert {'/api/jobs', '/api/run', '/api/intake', '/api/referrals/review', '/api/referrals/commit', '/api/intake/correction'} <= owned
    assert not (owned & _route_literals(_tree('api.py'))), 'a route is handled by both api.py and routes_work.py'
    assert not (owned & _route_literals(_tree('routes_system.py'))), 'a route is handled by two route modules'


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
    ('POST', '/api/jobs', {}, 400, {'error': 'unknown job name'}),
    ('POST', '/api/jobs', {'job': 'intake_dry'}, 400, {'error': 'Use New referrals to review PDFs before adding patients'}),
    ('POST', '/api/jobs', {'job': 'report_build', 'pdf': 'x'}, 400, {'error': 'invalid pdf'}),
    ('POST', '/api/jobs', [], 404, {'error': 'not found'}),
    ('GET', '/api/jobs/abc123', None, 404, {'error': 'job not found'}),
    ('GET', '/api/jobs/zzz', None, 404, {'error': 'not found'}),
    ('GET', '/api/jobs', None, 404, {'error': 'not found'}),
    ('POST', '/api/run', {}, 400, {'error': 'invalid steps'}),
    ('POST', '/api/run', [], 404, {'error': 'not found'}),
    ('POST', '/api/run/abc123/cancel', {}, 404, {'error': 'task not found'}),
    ('POST', '/api/run/abc123/result', {'state': 'done'}, 404, {'error': 'task not found'}),
    ('POST', '/api/referrals/review', {}, 400, {'error': 'Choose up to 100 PDF files'}),
    ('POST', '/api/referrals/review', {'paths': []}, 400, {'error': 'Choose up to 100 PDF files'}),
    ('POST', '/api/referrals/commit', {}, 400, {'error': 'Invalid review'}),
    ('POST', '/api/intake/correction', {}, 400, {'error': 'invalid file'}),
    ('POST', '/api/intake/correction', [], 404, {'error': 'not found'}),
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


def test_work_routes_keep_their_success_shapes(conn):
    s, r = api.handle(conn, 'GET', '/api/run', {}, None); assert s == 200 and set(r) == {'steps', 'tasks'}
    s, r = api.handle(conn, 'GET', '/api/intake', {}, None); assert s == 200 and set(r) == {'rows'}


def test_moved_functions_are_defined_once_in_their_owner():
    api_defs = {n.name for n in _tree('api.py').body if isinstance(n, ast.FunctionDef)}
    for module in ('patient_actions.py', 'followup_schedule.py', 'routes_work.py', 'routes_schedule.py', 'routes_pathology.py', 'routes_report.py', 'routes_clinical_records.py', 'routes_messages.py', 'routes_reference.py'):
        owned = {n.name for n in _tree(module).body if isinstance(n, ast.FunctionDef)} - {'handle'}
        assert not (owned & api_defs), f'{module} and api.py both define {sorted(owned & api_defs)}'


def test_schedule_and_pathology_routes_have_one_owner():
    schedule, pathology = _route_literals(_tree('routes_schedule.py')), _route_literals(_tree('routes_pathology.py'))
    assert {'/api/appointments', '/api/summary', '/api/days', '/api/attention', '/api/today'} <= schedule
    assert {'/api/pathology/queue', '/api/pathology/result'} <= pathology
    others = _route_literals(_tree('api.py')) | _route_literals(_tree('routes_system.py')) | _route_literals(_tree('routes_work.py'))
    assert not ((schedule | pathology) & others) and not (schedule & pathology)


def test_schedule_and_pathology_routes_keep_their_literal_behaviour(conn):
    import datetime as dt
    appt = {'date': '2026-11-20', 'start': '09:00', 'end': '10:00', 'title': ' Visit ', 'place': 'X', 'note': 'n'}
    s, r = api.handle(conn, 'POST', '/api/appointments', {}, appt)
    assert s == 200 and (r['id'], r['title'], r['date']) == (1, 'Visit', '2026-11-20')
    assert api.handle(conn, 'POST', '/api/appointments', {}, {**appt, 'end': '08:00'}) == (400, {'error': 'end must be after start'})
    assert api.handle(conn, 'POST', '/api/appointments', {}, {**appt, 'id': 99}) == (404, {'error': 'appointment not found'})
    assert api.handle(conn, 'GET', '/api/appointments', {'from': ['2026-11-30'], 'to': ['2026-11-01']}, None) == (400, {'error': 'invalid date range'})
    s, r = api.handle(conn, 'GET', '/api/appointments', {'from': ['2026-11-01'], 'to': ['2026-11-30']}, None)
    assert s == 200 and [a['title'] for a in r['appointments']] == ['Visit']
    assert api.handle(conn, 'POST', '/api/appointments/1/delete', {}, {}) == (200, {'ok': True})
    assert api.handle(conn, 'POST', '/api/appointments/1/delete', {}, {}) == (404, {'error': 'appointment not found'})
    assert api.handle(conn, 'GET', '/api/days/bad/plan', {}, None) == (400, {'error': 'invalid date'})
    assert api.handle(conn, 'GET', '/api/days', {'from': ['2026-01-01'], 'to': ['2026-12-30']}, None) == (400, {'error': 'invalid date range'})
    assert api.handle(conn, 'GET', '/api/today', {}, None) == (200, {'alerts': [], 'visits': []})
    today = dt.date.today()
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder,visit_date,visit_time,has_pathology,has_sheet) VALUES ('ann','Ann Alpha','confirmed',0,'/x/Ann_Alpha',?, '09:00',0,0)", (str(today),)); conn.commit()
    s, r = api.handle(conn, 'GET', '/api/today', {}, None)
    assert [v['name'] for v in r['visits']] == ['Ann Alpha'] and [a['type'] for a in r['alerts']] == ['missing pathology', 'missing interview sheet']
    s, r = api.handle(conn, 'GET', '/api/pathology/queue', {}, None)
    assert s == 200 and [(x['id'], x['folder'], x['last']) for x in r['patients']] == [(1, 'Ann_Alpha', 'Alpha')]
    assert api.handle(conn, 'POST', '/api/pathology/result', {}, {'id': '1'}) == (400, {'error': 'invalid id'})
    assert api.handle(conn, 'POST', '/api/pathology/result', {}, {'id': 7, 'saved': [], 'status': 'x'}) == (404, {'error': 'patient not found'})
    assert api.handle(conn, 'POST', '/api/pathology/result', {}, {'id': 1, 'saved': ['a'], 'status': 'ok', 'irn': '2'}) == (200, {'ok': True})
    assert api.handle(conn, 'GET', '/api/pathology/queue', {}, None) == (200, {'patients': []})
    assert conn.execute('SELECT state,has_pathology,irn FROM patients WHERE id=1').fetchone()[:] == ('pathology_ready', 1, '2')


def test_report_and_clinical_record_routes_have_one_owner():
    report, records = _route_literals(_tree('routes_report.py')), _route_literals(_tree('routes_clinical_records.py'))
    patterns = lambda tree: {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/patients/(')}
    mine_report, mine_records = patterns(_tree('routes_report.py')), patterns(_tree('routes_clinical_records.py'))
    assert {r"/api/patients/(\d+)/report", r"/api/patients/(\d+)/consent/(preview|sign)", r"/api/patients/(\d+)/report-versions"} <= mine_report
    assert {r"/api/patients/(\d+)/pathology-records", r"/api/patients/(\d+)/reconciliation", r"/api/patients/(\d+)/interview", r"/api/patients/(\d+)/medicine-context"} <= mine_records
    elsewhere = patterns(_tree('api.py')) | patterns(_tree('patient_actions.py')) | patterns(_tree('routes_work.py'))
    assert not ((mine_report | mine_records) & elsewhere) and not (mine_report & mine_records)


def test_report_and_record_routes_keep_their_literal_behaviour(conn, tmp_path):
    folder = tmp_path / 'Ann_Alpha'; folder.mkdir()
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder) VALUES ('ann','Ann Alpha','confirmed',0,?)", (str(folder),)); conn.commit()
    h = api.handle
    assert h(conn, 'GET', '/api/patients/999/report', {}, None) == (404, {'error': 'patient not found'})
    assert h(conn, 'POST', '/api/patients/999/report/refresh', {}, {}) == (404, {'error': 'patient not found'})
    assert h(conn, 'POST', '/api/patients/1/report/refresh', {}, {}) == (400, {'error': 'report spec does not exist'})
    assert h(conn, 'POST', '/api/patients/1/report/demographics', {}, {}) == (400, {'error': 'invalid body'})
    assert h(conn, 'POST', '/api/patients/1/reconciliation', {}, {}) == (400, {'error': 'invalid reconciliation review'})
    assert h(conn, 'POST', '/api/patients/1/interview', {}, {}) == (400, {'error': 'invalid interview fields'})
    assert h(conn, 'POST', '/api/patients/1/consent/preview', {}, {}) == (404, {'error': 'not found'})
    s, r = h(conn, 'GET', '/api/patients/1/reconciliation', {}, None)
    assert s == 200 and (r['flag_count'], r['medicines'], r['reviewed']) == (0, [], False)


def test_message_and_reference_routes_have_one_owner():
    def literals(tree):
        return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')}
    messages, reference = literals(_tree('routes_messages.py')), literals(_tree('routes_reference.py'))
    assert {'/api/messages/board', r"/api/patients/(\d+)/messages", r"/api/messages/([^/]+)/(approve|discard|resolve)"} <= messages
    assert {'/api/reference/local', '/api/reference/search', '/api/reference/open', '/api/library', r"/api/patients/(\d+)/reference-matches", r"/api/patients/(\d+)/candidate-checks", r"/api/patients/(\d+)/suggestions(?:/context)?"} <= reference
    others = literals(_tree('api.py')) | literals(_tree('routes_system.py')) | literals(_tree('routes_work.py')) | literals(_tree('routes_report.py'))
    assert not ((messages | reference) & others) and not (messages & reference)


def test_message_and_reference_routes_keep_their_literal_behaviour(conn, tmp_path):
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder) VALUES ('ann','Ann Alpha','confirmed',0,?)", (str(tmp_path),)); conn.commit()
    h = api.handle
    assert h(conn, 'POST', '/api/patients/999/messages', {}, {}) == (404, {'error': 'patient not found'})
    assert h(conn, 'POST', '/api/messages/nope/approve', {}, {}) == (404, {'error': 'message not found'})
    assert h(conn, 'POST', '/api/messages/nope/resolve', {}, {}) == (404, {'error': 'message not found'})
    assert h(conn, 'POST', '/api/reference/open', {}, {}) == (400, {'error': 'Invalid local reference request'})
    assert h(conn, 'GET', '/api/patients/999/reference-matches', {}, None) == (404, {'error': 'patient not found'})
    assert h(conn, 'GET', '/api/patients/999/candidate-checks', {}, None) == (404, {'error': 'patient not found'})
    assert h(conn, 'GET', '/api/patients/999/suggestions', {}, None) == (404, {'error': 'patient not found'})


def test_domain_modules_do_not_import_the_api_facade():
    # steps, report and suggestion_context used to reach medicine confirmation through api; they own a domain module now.
    for name in ('steps.py', 'report.py', 'suggestion_context.py', 'lifecycle.py', 'timeline.py', 'messaging.py', 'dev_seed.py'):
        for node in ast.walk(_tree(name)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert 'api' not in [m.split('.')[0] for m in modules], f'{name} imports api'


def test_followup_and_medicine_routes_have_one_owner_and_medicine_review_keeps_its_names(conn, tmp_path):
    def literals(tree):
        return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')}
    follow, meds = literals(_tree('routes_followup.py')), literals(_tree('routes_medicines.py'))
    assert r"/api/patients/(\d+)/(timeline|followup/([12])(/export)?)" in follow and r"/api/patients/(\d+)/meds" in meds
    others = literals(_tree('api.py')) | literals(_tree('routes_report.py')) | literals(_tree('routes_clinical_records.py'))
    assert not ((follow | meds) & others) and not (follow & meds)
    import medicine_review
    for name in ('report_data', 'proposal', 'interview_usage', 'conflicting_medicines', 'relevant_usage', 'valid_alternatives', 'same_name_as_stopped', 'current_medicine_snapshot', 'confirmed_medicines_current'):
        assert getattr(api, name) is getattr(medicine_review, name)
    (tmp_path / 'Ann_Alpha').mkdir()
    conn.execute("INSERT INTO patients(key,name,state,is_test,folder) VALUES ('ann','Ann Alpha','visited',0,?)", (str(tmp_path / 'Ann_Alpha'),)); conn.commit()
    assert api.handle(conn, 'GET', '/api/patients/999/meds', {}, None) == (404, {'error': 'patient not found'})
    assert api.handle(conn, 'GET', '/api/patients/999/timeline', {}, None) == (404, {'error': 'patient not found'})
    assert api.handle(conn, 'POST', '/api/patients/1/meds', {}, {}) == (400, {'error': 'invalid medicine list'})
