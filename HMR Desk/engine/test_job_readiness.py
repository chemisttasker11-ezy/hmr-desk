"""report_start and report_build started through /api/jobs (so also through the MCP) keep the Run queue's server-side readiness."""
import json, tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import api, db, jobs, records, settings, steps


@pytest.fixture
def world(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); db.BASE = tmp; db.DATA_DIR = tmp; monkeypatch.setenv('HMR_DB', str(root / 'test.db'))
        (root / 'patient').mkdir()
        conn = db.connect()
        settings.update(conn, {'ai_interview_assist': False, 'ai_report_assist': False})
        conn.execute("INSERT INTO patients(key,name,state,folder,gp,visit_date) VALUES ('job person','Job Person','confirmed','patient','Dr Example','2026-01-02')")
        conn.commit()
        with patch.object(jobs, 'ensure_worker'):
            yield conn
        conn.close()


def p(conn): return conn.execute('SELECT * FROM patients WHERE id=1').fetchone()
def set_state(conn, state): conn.execute('UPDATE patients SET state=? WHERE id=1', (state,)); conn.commit()
def tasks(conn): return conn.execute("SELECT step FROM tasks WHERE step IN ('report_start','report_build')").fetchall()
def refused(conn, name, text):
    with pytest.raises(ValueError) as exc: jobs.start(name, 1, conn)
    assert text in str(exc.value)
    assert not tasks(conn), 'a refused job must not be queued'


def test_report_start_needs_visit_medicines_and_interaction_check(world):
    conn = world
    refused(conn, 'report_start', 'visit not recorded')
    set_state(conn, 'visited')
    refused(conn, 'report_start', 'confirm the medicine list first')
    records.put(conn, 1, 'confirmed_meds.json', json.dumps({'meds': [['aspirin', '']], 'allergies': []}).encode('utf-8')); conn.commit()
    refused(conn, 'report_start', 'run the eMIMS interaction check first')
    records.put(conn, 1, 'MIMS interactions.txt', b'synthetic manual interaction note'); conn.commit()
    assert steps.ready('report_start', conn, p(conn))[0]
    assert jobs.start('report_start', 1, conn)
    assert [r[0] for r in tasks(conn)] == ['report_start']


def test_report_start_refuses_when_a_spec_already_exists(world):
    conn = world; set_state(conn, 'visited')
    records.put(conn, 1, 'report_spec.json', json.dumps({'issues': []}).encode('utf-8')); conn.commit()
    refused(conn, 'report_start', 'already done')


def test_report_build_needs_state_spec_and_a_finding(world):
    conn = world
    refused(conn, 'report_build', 'patient is not awaiting report')
    set_state(conn, 'visited')
    refused(conn, 'report_build', 'report spec missing')
    records.put(conn, 1, 'report_spec.json', json.dumps({'issues': []}).encode('utf-8')); conn.commit()
    refused(conn, 'report_build', 'add at least one finding')
    records.put(conn, 1, 'report_spec.json', json.dumps({'issues': [{'title': 't', 'rec': 'r', 'rationale': 'x'}]}).encode('utf-8')); conn.commit()
    assert jobs.start('report_build', 1, conn)


def test_deliberate_rebuild_after_a_report_exists_is_still_allowed(world):
    conn = world; set_state(conn, 'report_drafted')
    records.put(conn, 1, 'report_spec.json', json.dumps({'issues': [{'title': 't', 'rec': 'r', 'rationale': 'x'}]}).encode('utf-8')); conn.commit()
    assert steps.done('report_build', conn, p(conn))
    assert steps.ready('report_build', conn, p(conn))[0] is False  # the queue still reports it as done
    assert jobs.start('report_build', 1, conn, 'pdf')  # an explicit rebuild is allowed, with the same checks
    set_state(conn, 'signed_off')
    conn.execute("DELETE FROM tasks"); conn.commit()
    refused(conn, 'report_build', 'patient is not awaiting report')


def test_the_api_route_returns_the_same_refusal(world):
    conn = world
    result = api.handle(conn, 'POST', '/api/jobs', {}, {'job': 'report_start', 'patient_id': 1})
    assert result[0] == 400 and 'visit not recorded' in json.dumps(result[1])
    assert not tasks(conn)


def test_the_worker_check_refuses_a_job_that_became_ineligible_after_queueing(world):
    conn = world; set_state(conn, 'confirmed')
    with pytest.raises(ValueError, match='visit not recorded'): jobs.check_report_ready('report_start', conn, 1)
    jobs.check_report_ready('interview_pack', conn, 1)  # other jobs are not changed by this gate
    jobs.check_report_ready('register_xlsx', conn, None)


def test_report_build_rejects_format_both_before_queueing_and_keeps_docx_and_pdf(world):
    """'both' used to be accepted and silently produced a DOCX only. It is refused up front; docx and pdf are unchanged."""
    with pytest.raises(ValueError) as exc: jobs.start('report_build', 1, world, 'both')
    assert "does not support format 'both'" in str(exc.value) and "'pdf'" in str(exc.value)
    assert not tasks(world)
    for fmt in ('docx', 'pdf'):  # not format-refused: they reach the readiness check instead
        with pytest.raises(ValueError) as exc: jobs.start('report_build', 1, world, fmt)
        assert 'format' not in str(exc.value)
