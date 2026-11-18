from pathlib import Path
from unittest.mock import patch

import engine_main
import pdf_selftest


def test_self_test_reports_pass_with_converted_pdf(tmp_path, capsys):
    def fake(docx, pdf, timeout=120):
        assert Path(docx).suffix == '.docx' and Path(docx).is_file()
        Path(pdf).write_bytes(b'%PDF-' + b'0' * 300); return {'created': True, 'bytes': 305}
    with patch('pdf_export.convert', side_effect=fake):
        assert pdf_selftest.run(tmp_path / "a b & o'c") == 0
    assert capsys.readouterr().out.strip() == 'PASS: packaged engine produced a PDF (305 bytes)'


def test_self_test_failure_writes_masked_reason_to_the_result_file_and_returns_one(tmp_path):
    out = tmp_path / 'result.txt'
    with patch('pdf_export.convert', side_effect=RuntimeError('Bundled PDF conversion failed (converter exit code 7)')):
        assert pdf_selftest.run(tmp_path / 'w', str(out)) == 1
    assert out.read_text(encoding='utf-8').strip() == 'FAIL: Bundled PDF conversion failed (converter exit code 7)'


def test_the_frozen_entry_point_accepts_the_flag_and_exits_before_touching_data(tmp_path, monkeypatch):
    # The packaged executable starts at engine_main, not service: the flag must be parsed here.
    monkeypatch.setattr('app_paths.ensure_writable', lambda p: (_ for _ in ()).throw(AssertionError('data dir touched')))
    with patch('pdf_selftest.run', return_value=3) as hook:
        assert engine_main.main(['--self-test-pdf', str(tmp_path), '--self-test-result', str(tmp_path / 'r.txt')]) == 3
    hook.assert_called_once_with(str(tmp_path), str(tmp_path / 'r.txt'))


def test_a_real_self_test_run_through_the_entry_point_writes_the_verdict_file(tmp_path):
    import pdf_export
    if not pdf_export.available(): __import__('pytest').skip('no converter here')
    out = tmp_path / 'r.txt'
    assert engine_main.main(['--self-test-pdf', str(tmp_path / 'w'), '--self-test-result', str(out)]) == 0
    assert out.read_text(encoding='utf-8').startswith('PASS')
