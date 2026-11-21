"""Per-patient results, later online refresh, and interaction evidence in the build record. Synthetic data only."""
import json

import db
import interaction_scope
import medicine_review
import patient_actions
import records
import report_auth
import report_status
import results
import routes_clinical_records
import routes_pathology
import steps
from test_report_auth import case


def _complete(conn, patient, **extra):
    fields = dict(name='Synthetic Patient', dob='01-Jan-1950', sex='F', medicare='2123456701')
    fields.update(extra)
    with conn:
        conn.execute('UPDATE patients SET name=?,dob=?,sex=?,medicare=?,state=? WHERE id=?',
                     (fields['name'], fields['dob'], fields['sex'], fields['medicare'], fields.get('state', 'visited'), patient['id']))
    return conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()


def _confirmed(conn, patient, monkeypatch):
    monkeypatch.setattr(medicine_review, 'confirmed_medicines_current', lambda c, p: True)
    records.put(conn, patient['id'], 'confirmed_meds.json', b'{"meds":[["alpha",""]],"allergies":[]}'); conn.commit()


def test_a_done_interaction_step_can_be_run_again_but_the_automatic_flow_still_skips_it(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    patient = _complete(conn, patient)
    monkeypatch.setattr(steps, 'interactions_done', lambda c, p: True)
    monkeypatch.setattr(steps, 'medicines_current', lambda c, p: True)
    assert steps.done('interactions', conn, patient) is True          # flow() and advance() test done() first and skip it
    assert steps.ready('interactions', conn, patient) == (True, '')   # a deliberate run is still allowed
    monkeypatch.setattr(steps, 'medicines_current', lambda c, p: False)
    assert steps.ready('interactions', conn, patient) == (False, 'confirm the medicine list first')
    assert steps.ready('pathology', conn, patient)[1] in ('patient is not scheduled', 'already done')  # unchanged
    conn.close()


def test_pathology_recheck_is_explicit_per_patient_and_clears_when_a_result_is_recorded(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    patient = _complete(conn, patient, state='visited')
    with conn: conn.execute('UPDATE patients SET has_pathology=1 WHERE id=?', (patient['id'],))
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
    assert steps.done('pathology', conn, patient) and steps.ready('pathology', conn, patient) == (False, 'already done')
    assert routes_pathology.handle(conn, 'GET', '/api/pathology/queue', {}, None)[1]['patients'] == []
    patient_actions.action(conn, patient, {'action': 'pathology_recheck'})
    patient = conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
    assert steps.pathology_recheck_pending(conn, patient) and not steps.done('pathology', conn, patient)
    ok, why = steps.ready('pathology', conn, patient)
    assert ok, why
    queue = routes_pathology.handle(conn, 'GET', '/api/pathology/queue', {}, None)[1]['patients']
    assert [q['id'] for q in queue] == [patient['id']]
    status, _ = routes_pathology.handle(conn, 'POST', '/api/pathology/result', {}, {'id': patient['id'], 'saved': ['x.pdf'], 'status': 'saved'})
    assert status == 200
    after = conn.execute('SELECT * FROM patients WHERE id=?', (patient['id'],)).fetchone()
    assert after['state'] == 'visited' and after['has_pathology'] == 1   # never moved back to a scheduled stage
    assert not steps.pathology_recheck_pending(conn, after)
    assert routes_pathology.handle(conn, 'GET', '/api/pathology/queue', {}, None)[1]['patients'] == []
    conn.close()


def test_recheck_is_refused_for_an_unscheduled_new_patient(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    patient = _complete(conn, patient, state='new')
    try:
        patient_actions.action(conn, patient, {'action': 'pathology_recheck'})
        raise AssertionError('should refuse')
    except ValueError as error:
        assert 'invalid patient state' in str(error)
    conn.close()


def test_a_new_or_changed_current_interaction_result_changes_the_evidence_digest(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    patient = _complete(conn, patient)
    none = interaction_scope.evidence_digest(conn, patient)
    _confirmed(conn, patient, monkeypatch)
    no_result = interaction_scope.evidence_digest(conn, patient)
    records.put(conn, patient['id'], 'MIMS interactions (manual) 2026-11-21.txt', b'Checked by hand'); conn.commit()
    manual = interaction_scope.evidence_digest(conn, patient)
    records.put(conn, patient['id'], 'MIMS interactions (manual) 2026-11-21 (2).txt', b'Checked again'); conn.commit()
    two = interaction_scope.evidence_digest(conn, patient)
    assert len({none, no_result, manual, two}) == 4
    assert interaction_scope.evidence_state(conn, patient) == 'manual_note'
    assert [f['kind'] for f in interaction_scope.evidence_files(conn, patient)] == ['manual', 'manual']
    conn.close()


def test_report_becomes_outdated_when_interaction_evidence_changes_but_old_builds_are_not_judged(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    assert report_status.report_status(conn, patient)['status'] == 'current'            # build predates the field
    assert report_status.build_basis(conn, patient)['interactions'] == 'not_recorded'
    latest = conn.execute("SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1", (patient['id'],)).fetchone()
    detail = json.loads(latest['detail'])
    detail['interactions_evidence_sha256'] = interaction_scope.evidence_digest(conn, patient)
    with conn: conn.execute('UPDATE events SET detail=? WHERE id=?', (json.dumps(detail), latest['id']))
    assert report_status.report_status(conn, patient)['status'] == 'current'
    assert report_status.build_basis(conn, patient)['interactions'] == 'used_by_report'
    _confirmed(conn, patient, monkeypatch)
    records.put(conn, patient['id'], 'MIMS interactions (manual) 2026-11-21.txt', b'Checked by hand'); conn.commit()
    status = report_status.report_status(conn, patient)
    assert status['status'] == 'outdated' and 'interactions_changed' in status['reasons']
    assert report_status.build_basis(conn, patient)['interactions'] == 'changed_since_build'
    conn.close()


def test_results_route_shows_what_is_on_file_and_whether_the_report_used_it(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    status, view = routes_clinical_records.handle(conn, 'GET', '/api/patients/%d/results' % patient['id'], {}, None)
    assert status == 200 and set(view) == {'pathology', 'interactions', 'report_built_at', 'note'}
    assert view['pathology']['records'] == [] and view['pathology']['recheck_pending'] is False
    assert view['pathology']['report'] == 'used_by_report'
    assert view['interactions']['evidence_state'] == 'no_current_confirmation' and view['interactions']['files'] == []
    assert 'not clinical sign-off' in view['note']
    assert routes_clinical_records.handle(conn, 'GET', '/api/patients/9999/results', {}, None)[0] == 404
    assert routes_clinical_records.handle(conn, 'POST', '/api/patients/%d/results' % patient['id'], {}, {}) is None
    conn.close()


def test_results_view_does_not_change_sign_off_rules(tmp_path, monkeypatch):
    conn, patient, folder, body = case(tmp_path, monkeypatch)
    before = report_auth.check_approval(conn, patient, body)
    results.for_patient(conn, patient)
    _confirmed(conn, patient, monkeypatch)
    records.put(conn, patient['id'], 'MIMS interactions (manual) 2026-11-21.txt', b'Checked by hand'); conn.commit()
    assert report_auth.check_approval(conn, patient, body).keys() == before.keys()   # no new sign-off condition
    conn.close()
