"""A deliberate report-date change is a real content change; a refresh never rewrites a saved date (synthetic data)."""
import json

import jobs
import report
import report_status
from test_report_save_revision import _setup, _saved_report


def test_saved_report_date_survives_refresh_and_a_deliberate_change_outdates_the_build(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        loaded.update(followup_decision='required', followup='Synthetic plan: review again in three months.',
                      report_date='18/11/2026', expected_revision=loaded['revision'])
        report.save(conn, patient, loaded); conn.commit()
    jobs.report_build(patient['id'])
    with connection() as conn:
        assert 'report_content_changed' not in report_status.report_status(conn, patient)['reasons']
        refreshed = report.refresh(conn, patient); conn.commit()
        assert refreshed['report_date'] == '18/11/2026'  # refresh never moves an explicit date
        assert 'report_date_review' not in json.dumps(report.load(conn, patient))  # advisory is renderer-only, never stored
        data = report.load(conn, patient)
        data.update(report_date='20/11/2026', expected_revision=data['revision'])
        report.save(conn, patient, data); conn.commit()
        assert 'report_content_changed' in report_status.report_status(conn, patient)['reasons']
