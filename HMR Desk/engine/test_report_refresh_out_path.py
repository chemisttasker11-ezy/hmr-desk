"""Synthetic check: Refresh repairs a report output path that points outside the patient folder (e.g. after a restore)."""
from pathlib import Path

import jobs
import report
from test_report_save_revision import _setup, _saved_report


def test_refresh_rebases_an_out_of_workspace_output_path(tmp_path, monkeypatch):
    connection = _setup(tmp_path, monkeypatch)
    with connection() as conn:
        patient, loaded = _saved_report(conn)
        folder = jobs.patient_folder(patient)
        stale = dict(loaded); stale['out'] = str(tmp_path / 'old-machine' / 'workspace' / 'synthetic' / 'HMR Synthetic Patient.docx')
        report.save(conn, patient, stale); conn.commit()
        refreshed = report.refresh(conn, patient)
        assert Path(refreshed['out']) == folder / 'HMR Synthetic Patient.docx'
        assert Path(report.load(conn, patient)['out']).parent == folder
