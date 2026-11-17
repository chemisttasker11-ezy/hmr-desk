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
    with tempfile.TemporaryDirectory(prefix='.hmr-pdf-', dir=target.parent) as directory:
        staging = Path(directory)
        profile = staging / 'lo-profile'
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
    return {'created': True, 'bytes': target.stat().st_size}
