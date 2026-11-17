"""Offline DOCX to PDF conversion using the exact bundled soffice.exe.

Does not use Microsoft Word, the shell or a developer-profile PowerShell skill.
No report text or patient identifiers are included in error messages/logs.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

CLEANUP_WAIT_SECONDS = 10.0


def extended(path, nt=None):
    """Windows extended-length form, so removal works past the 260 character limit."""
    text = os.path.abspath(str(path))
    if (os.name == 'nt' if nt is None else nt) and not text.startswith('\\\\?\\'):
        text = '\\\\?\\UNC\\' + text[2:] if text.startswith('\\\\') else '\\\\?\\' + text
    return text


def remove_tree(path, wait=None, sleep=time.sleep, clock=time.monotonic):
    """Remove a directory this module created, retrying while Windows still holds files.

    No ignore_errors. Returns None when removed, else the last OSError text.
    """
    path = Path(path)
    deadline = clock() + (CLEANUP_WAIT_SECONDS if wait is None else wait)
    delay = 0.1
    while True:
        try:
            shutil.rmtree(extended(path))
            if not path.exists():
                return None
            exc = OSError('directory still present after removal reported success')
        except FileNotFoundError as caught:
            if not path.exists():
                return None  # the folder itself is gone
            exc = caught  # a nested entry vanished mid-walk; the folder remains, so retry
        except OSError as caught:
            exc = caught
        if clock() >= deadline:
            return type(exc).__name__ + ': ' + str(exc)
        sleep(delay)
        delay = min(delay * 2, 1.0)


def _remove_all(*folders):
    """Remove each folder; return (name or path of the first one left behind, error text), else None."""
    left = None
    for folder in folders:
        error = remove_tree(folder)
        if error and left is None:
            left = (Path(folder).name if Path(folder).name.startswith('.hmr-pdf-') else str(folder), error)
    return left


def available():
    selected = os.environ.get('HMR_PDF_CONVERTER')
    if selected:
        return Path(selected).is_file()
    if getattr(sys, 'frozen', False):
        return False  # never resolve a host-installed LibreOffice in production
    return bool(shutil.which('soffice'))


def convert(docx, pdf, timeout=120):
    source, target = Path(docx).resolve(), Path(pdf).resolve()
    if not source.is_file() or source.suffix.lower() != '.docx':
        raise ValueError('Existing Word report required for PDF conversion')
    if target.suffix.lower() != '.pdf' or source.parent != target.parent:
        raise ValueError('PDF output must be beside the local Word report')
    if target.exists():
        raise FileExistsError('A PDF already exists for this report revision')
    engine = os.environ.get('HMR_PDF_CONVERTER')
    if not engine:
        if getattr(sys, 'frozen', False):
            raise RuntimeError('Bundled PDF converter missing; reinstall complete application')
        engine = shutil.which('soffice')
    if not engine or not Path(engine).is_file():
        raise RuntimeError('Bundled PDF converter unavailable')
    directory = tempfile.mkdtemp(prefix='.hmr-pdf-', dir=target.parent)
    # LibreOffice's profile nests about 180 characters deep. Keep it under a short root (the system temp
    # folder) so no path passes the Windows 260 character limit, whatever the patient folder depth.
    profile_dir = tempfile.mkdtemp(prefix='hp-', dir=os.environ.get('HMR_PDF_PROFILE_ROOT') or tempfile.gettempdir())
    try:
        staging = Path(directory)
        profile = Path(profile_dir) / 'lo-profile'
        output_dir = staging / 'rendered'
        output_dir.mkdir()
        cmd = [str(engine), '-env:UserInstallation=' + profile.as_uri(),
               '--headless', '--nologo', '--nodefault', '--nofirststartwizard',
               '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(output_dir), str(source)]
        kwargs = {'capture_output': True, 'timeout': timeout, 'check': False}
        if os.name == 'nt': kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('PDF converter exceeded the safety timeout') from exc
        except OSError as exc:
            raise RuntimeError('Cannot launch bundled PDF converter') from exc
        converted = output_dir / source.with_suffix('.pdf').name
        if result.returncode != 0 or not converted.is_file() or converted.stat().st_size < 100:
            raise RuntimeError('Bundled PDF conversion failed; review the Word draft')
        if target.exists():
            raise FileExistsError('PDF appeared during conversion; refusing overwrite')
        os.replace(converted, target)
    except BaseException as exc:
        failure = _remove_all(directory, profile_dir)
        if failure:
            # Keep the primary error; add the cleanup evidence beside it (folder name only, no patient path).
            exc.cleanup_pending = failure[0]
            exc.cleanup_error = failure[1]
        raise
    failure = _remove_all(directory, profile_dir)
    result = {'created': True, 'bytes': target.stat().st_size, 'cleanup_pending': None}
    if failure:
        # Conversion succeeded; the scratch folder is still locked. Report it, do not hide it.
        result['cleanup_pending'] = failure[0]
        result['cleanup_error'] = failure[1]
    return result


def pending_note(name):
    return ('Temporary PDF working folder ' + name + ' could not be removed yet (Windows still holds files). '
            'It is in the patient report folder or the Windows temp folder. Close other programs using it, then delete that folder.')
