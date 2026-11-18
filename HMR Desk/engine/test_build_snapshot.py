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

    def render_then_source_changes(data, draft):
        out = real(data, draft)
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
