"""PDF conversion: what the converter is given, one retry, and a reason that reaches the screen and log."""
import subprocess
from pathlib import Path

import docx
import pytest

import pdf_export


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_PDF_PROFILE_ROOT', str(tmp_path / 'profiles'))
    (tmp_path / 'profiles').mkdir()
    fake = tmp_path / 'soffice.exe'; fake.write_bytes(b'x')
    monkeypatch.setenv('HMR_PDF_CONVERTER', str(fake))
    monkeypatch.setattr(pdf_export.time, 'sleep', lambda s: None)
    folder = tmp_path / "Jane O'Neil & Sons"; folder.mkdir()
    source = folder / "HMR Jane O'Neil & Sons-v2.docx"; docx.Document().save(source)
    return folder, source


def _run(results, seen):
    """A stand-in converter: each call pops the next (exit code, wrote_pdf, stderr)."""
    def run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        code, wrote, err = results.pop(0)
        out = Path(cmd[cmd.index('--outdir') + 1])
        if wrote: (out / (Path(cmd[-1]).stem + '.pdf')).write_bytes(b'%PDF-' + b'0' * 200)
        return subprocess.CompletedProcess(cmd, code, b'', err)
    return run


def test_converter_gets_a_private_ascii_copy_and_closed_stdin(setup, monkeypatch):
    folder, source = setup
    seen = []
    monkeypatch.setattr(pdf_export.subprocess, 'run', _run([(0, True, b'')], seen))
    original = source.read_bytes()
    result = pdf_export.convert(source, source.with_suffix('.pdf'))
    cmd, kwargs = seen[0]
    assert result['created'] and source.with_suffix('.pdf').is_file()
    assert Path(cmd[-1]).name == 'report.docx' and Path(cmd[-1]) != source and "O'Neil" not in Path(cmd[-1]).name
    assert kwargs['stdin'] == subprocess.DEVNULL
    assert source.read_bytes() == original            # the patient's Word file is untouched
    assert not [x for x in folder.iterdir() if x.name.startswith('.hmr-pdf-')]   # staging removed


def test_a_first_failure_is_retried_once(setup, monkeypatch):
    folder, source = setup
    seen = []
    monkeypatch.setattr(pdf_export.subprocess, 'run', _run([(81, False, b'first start'), (0, True, b'')], seen))
    assert pdf_export.convert(source, source.with_suffix('.pdf'))['created'] and len(seen) == 2


@pytest.mark.parametrize('results,expect', [
    ([(81, False, b'Error: cannot load C:\\Users\\jane\\Jane O\'Neil\\x.docx'), (81, False, b'Error: cannot load C:\\Users\\jane\\Jane O\'Neil\\x.docx')], 'attempt 2: converter exit code 81, no PDF produced, output: Error: cannot load <path>'),
    ([(0, False, b''), (0, False, b'')], 'attempt 2: converter exit code 0, no PDF produced'),
])
def test_failure_reason_names_the_exit_code_and_masks_paths(setup, monkeypatch, results, expect):
    folder, source = setup
    seen = []
    monkeypatch.setattr(pdf_export.subprocess, 'run', _run(list(results), seen))
    with pytest.raises(RuntimeError) as caught:
        pdf_export.convert(source, source.with_suffix('.pdf'))
    text = pdf_export.failure_text(caught.value)
    assert expect in text and 'Jane' not in text and 'Users' not in text and len(seen) == 2
    assert source.is_file() and not source.with_suffix('.pdf').exists()
    assert not [x for x in folder.iterdir() if x.name.startswith('.hmr-pdf-')]


def test_os_error_reason_carries_type_and_code_but_never_a_path():
    err = PermissionError(13, 'Permission denied', 'C:\\data\\Jane Smith\\r.docx')
    text = pdf_export.failure_text(err)
    assert text == 'PermissionError (errno 13, winerror None)' and 'Jane' not in text


def test_timeout_is_not_retried(setup, monkeypatch):
    folder, source = setup
    calls = []
    def run(cmd, **kwargs):
        calls.append(1); raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(pdf_export.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='safety timeout'):
        pdf_export.convert(source, source.with_suffix('.pdf'))
    assert len(calls) == 1
