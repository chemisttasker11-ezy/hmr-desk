import sys
from pathlib import Path
from unittest.mock import patch

import pdf_export
import service


def test_self_test_reports_pass_with_converted_pdf(tmp_path, capsys):
    def fake(docx, pdf, timeout=120):
        assert Path(docx).suffix == '.docx' and Path(docx).is_file()
        Path(pdf).write_bytes(b'%PDF-' + b'0' * 300); return {'created': True, 'bytes': 305}
    with patch('pdf_export.convert', side_effect=fake):
        assert service.self_test_pdf(tmp_path / "a b & o'c") == 0
    assert capsys.readouterr().out.strip() == 'PASS: packaged engine produced a PDF (305 bytes)'


def test_self_test_failure_prints_masked_reason_and_returns_one(tmp_path, capsys):
    with patch('pdf_export.convert', side_effect=RuntimeError('Bundled PDF conversion failed (converter exit code 7)')):
        assert service.self_test_pdf(tmp_path) == 1
    assert capsys.readouterr().out.strip() == 'FAIL: Bundled PDF conversion failed (converter exit code 7)'


def test_self_test_flag_exits_with_result_before_any_data_is_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['service.py', '--self-test-pdf', str(tmp_path)])
    with patch.object(service, 'self_test_pdf', return_value=3) as hook, patch.object(service.db, 'connect', side_effect=AssertionError('database touched')):
        try: service.main(); raise AssertionError('must exit')
        except SystemExit as exc: assert exc.code == 3
    hook.assert_called_once_with(str(tmp_path))
