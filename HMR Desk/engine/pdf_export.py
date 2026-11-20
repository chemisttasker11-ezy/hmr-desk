"""Offline DOCX to PDF conversion using the exact bundled soffice.exe.

Does not use Microsoft Word, the shell or a developer-profile PowerShell skill.
No report text or patient identifiers are included in error messages/logs.
"""
import os
import app_paths
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


def profile_root():
    """Parent for the per-run converter profile.

    The packaged app always uses the per-user temp folder. The HMR_PDF_PROFILE_ROOT override is a
    development and test setting, ignored when frozen so a shared folder cannot be set silently.
    """
    if not getattr(sys, 'frozen', False):
        override = os.environ.get('HMR_PDF_PROFILE_ROOT')
        if override:
            return override
    return tempfile.gettempdir()


def _remove_all(*folders):
    """Remove each folder; return (name or path of the first one left behind, error text), else None."""
    left = None
    for folder in folders:
        error = remove_tree(folder)
        if error and left is None:
            left = (Path(folder).name if Path(folder).name.startswith('.hmr-pdf-') else str(folder), error)
    return left


def masked_tail(raw, limit=300):
    """Last part of converter output with every path-like text replaced, so a patient or folder name in a
    path never reaches the log or the screen. Returns '' for empty output."""
    import re
    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw or '')
    text = re.sub(r'(?:[A-Za-z]:)?[\\/][^\r\n"\']*', '<path>', text)
    text = re.sub(r'file:[^\s]*', '<path>', text)
    return ' '.join(text.split())[-limit:]


def failure_text(exc):
    """Why a conversion failed, safe to show and log: the converter message for our own errors, only the
    error type and code for OS errors (their text can hold a patient folder path)."""
    if isinstance(exc, OSError) and not isinstance(exc, FileExistsError):
        return '%s (errno %s, winerror %s)' % (type(exc).__name__, exc.errno, getattr(exc, 'winerror', None))
    return str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__


def bundled_converter():
    """The portable converter that scripts/bundle-libreoffice.ps1 extracts (pinned, checksum-verified) into the
    source checkout. Only a source run uses it; the packaged app is given its own copy through HMR_PDF_CONVERTER."""
    if getattr(sys, 'frozen', False):
        return None
    candidate = app_paths.resource_root() / 'vendor' / 'libreoffice' / 'program' / 'soffice.exe'
    return str(candidate) if candidate.is_file() else None


def resolve_converter():
    """Converter order: the configured path, then (source runs only) the bundled portable copy, then a PATH install.
    A packaged run never looks further than its configured, bundled path."""
    selected = os.environ.get('HMR_PDF_CONVERTER')
    if selected:
        return selected if Path(selected).is_file() else None
    if getattr(sys, 'frozen', False):
        return None  # never resolve a host-installed LibreOffice in production
    return bundled_converter() or shutil.which('soffice')


def available():
    return bool(resolve_converter())


def convert(docx, pdf, timeout=120):
    source, target = Path(docx).resolve(), Path(pdf).resolve()
    if not source.is_file() or source.suffix.lower() != '.docx':
        raise ValueError('Existing Word report required for PDF conversion')
    if target.suffix.lower() != '.pdf' or source.parent != target.parent:
        raise ValueError('PDF output must be beside the local Word report')
    if target.exists():
        raise FileExistsError('A PDF already exists for this report revision')
    engine = resolve_converter()
    if not engine:
        if getattr(sys, 'frozen', False):
            raise RuntimeError('Bundled PDF converter missing; reinstall complete application')
        raise RuntimeError('Bundled PDF converter unavailable: run scripts/bundle-libreoffice.ps1 or set HMR_PDF_CONVERTER')
    directory = tempfile.mkdtemp(prefix='.hmr-pdf-', dir=target.parent)
    # LibreOffice's profile nests about 180 characters deep. Keep it under a short root (the system temp
    # folder) so no path passes the Windows 260 character limit, whatever the patient folder depth.
    profile_dir = tempfile.mkdtemp(prefix='hp-', dir=profile_root())
    try:
        staging = Path(directory)
        profile = Path(profile_dir) / 'lo-profile'
        output_dir = staging / 'rendered'
        output_dir.mkdir()
        # Convert a private copy with a short ASCII name: the patient's Word file is never held open by the
        # converter or an antivirus scan that has only just seen it, and special characters in a patient or
        # folder name cannot reach the converter's command line.
        staged = staging / 'report.docx'
        shutil.copyfile(source, staged)
        cmd = [str(engine), '-env:UserInstallation=' + profile.as_uri(),
               '--headless', '--nologo', '--nodefault', '--nofirststartwizard',
               '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(output_dir), str(staged)]
        # stdin is closed explicitly: the packaged engine has no console, so an inherited stdin is invalid.
        kwargs = {'capture_output': True, 'timeout': timeout, 'check': False, 'stdin': subprocess.DEVNULL}
        if os.name == 'nt': kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        converted = output_dir / 'report.pdf'
        reason = ''
        for attempt in (1, 2):
            try:
                result = subprocess.run(cmd, **kwargs)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('PDF converter exceeded the safety timeout') from exc
            except OSError as exc:
                error = RuntimeError('Cannot launch bundled PDF converter (%s, winerror %s)' % (type(exc).__name__, getattr(exc, 'winerror', None)))
                raise error from exc
            ok = result.returncode == 0 and converted.is_file() and converted.stat().st_size >= 100
            if ok: break
            reason = 'attempt %d: converter exit code %s, %s' % (
                attempt, result.returncode, 'no PDF produced' if not converted.is_file() else 'PDF too small')
            tail = masked_tail(result.stderr) or masked_tail(result.stdout)
            if tail: reason += ', output: ' + tail
            if attempt == 1: time.sleep(2.0)  # a first-start profile or a just-written file can fail once
        if not ok:
            error = RuntimeError('Bundled PDF conversion failed (%s); review the Word draft' % reason)
            error.detail = reason
            raise error
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
