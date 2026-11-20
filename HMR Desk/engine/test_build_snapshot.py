"""Synthetic check: build evidence records the sources as they were before rendering, not after."""
import json

import jobs
import local_report_builder
import pathology_records
import report
import report_auth
from test_report_save_revision import _setup, _saved_report


def test_source_saved_during_render_is_not_recorded_as_built_from(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.', expected_revision=loaded['revision'])
        report.save(conn, patient, loaded)
        conn.commit()
        before = pathology_records.revision(conn, patient)
        clinical_before = report_auth.clinical_snapshot_hash(conn, patient)
    real = local_report_builder.render

    def render_then_source_changes(data, draft, include_gp_plan=False):
        out = real(data, draft, include_gp_plan=include_gp_plan)
        with connection() as other:  # a pathology result is saved while the document is being rendered
            row = dict(id='a' * 32, test='Serum creatinine', value='98', unit='umol/L', reference_interval='60-110',
                       sample_date='2026-11-12', source='synthetic.pdf', verified=False, comment='')
            pathology_records.save(other, patient, {'revision': pathology_records.revision(other, patient), 'records': [row]})
        return out
    monkeypatch.setattr(local_report_builder, 'render', render_then_source_changes)
    jobs.report_build(patient['id'])
    with connection() as conn:
        after = pathology_records.revision(conn, patient)
        detail = json.loads(conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
                                         (patient['id'],)).fetchone()['detail'])
    assert after != before
    assert detail['pathology_revision'] == before
    assert detail['clinical_snapshot_sha256'] == clinical_before


def test_checks_and_evidence_come_from_one_read_snapshot(tmp_path, monkeypatch):
    """A pathology result committed by another connection between the first check and the evidence must not split them."""
    import interview
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.', expected_revision=loaded['revision'])
        report.save(conn, patient, loaded)
        conn.commit()
        before = pathology_records.revision(conn, patient)
    real, fired = interview.revision, []

    def revision_then_concurrent_save(conn, p):
        value = real(conn, p)
        if not fired:
            fired.append(True)
            with connection() as other:
                row = dict(id='b' * 32, test='Serum creatinine', value='98', unit='umol/L', reference_interval='60-110',
                           sample_date='2026-11-12', source='synthetic.pdf', verified=False, comment='')
                pathology_records.save(other, patient, {'revision': pathology_records.revision(other, patient), 'records': [row]})
        return value
    monkeypatch.setattr(interview, 'revision', revision_then_concurrent_save)
    jobs.report_build(patient['id'])
    with connection() as conn:
        detail = json.loads(conn.execute("SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
                                         (patient['id'],)).fetchone()['detail'])
        assert pathology_records.revision(conn, patient) != before
    assert detail['pathology_revision'] == before


def test_build_rebases_an_output_path_from_another_workspace_root(tmp_path, monkeypatch):
    """After a restore the spec still names the old workspace root; the report is built in this patient's folder."""
    import pytest
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        folder = jobs.patient_folder(patient)
        for stale in (str(tmp_path / 'old-root' / 'synthetic' / 'HMR Synthetic Patient.docx'),
                      'C:\\Users\\Old\\HMR-Desk-data\\workspace\\synthetic\\HMR Synthetic Patient.docx'):
            spec = dict(report.load(conn, patient), out=stale, followup_decision='required',
                        followup='Synthetic plan: review again in three months.')
            spec['expected_revision'] = spec['revision']
            report.save(conn, patient, spec)
            conn.commit()
            before = set(p.name for p in folder.iterdir())
            jobs.report_build(patient['id'])
            created = set(p.name for p in folder.iterdir()) - before
            assert created and all(name.endswith('.docx') for name in created), created
            assert not (tmp_path / 'old-root').exists()
        bad = dict(report.load(conn, patient), out=str(tmp_path / 'elsewhere' / 'x.txt'))
        bad['expected_revision'] = bad['revision']
        report.save(conn, patient, bad); conn.commit()
        with pytest.raises(ValueError, match='DOCX'):
            jobs.report_build(patient['id'])
