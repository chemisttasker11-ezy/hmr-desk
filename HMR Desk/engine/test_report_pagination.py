"""Rendered-output check: no generated report may end in a page with only the header and footer. Needs LibreOffice and PyMuPDF."""
import shutil
import subprocess

import pytest
fitz = pytest.importorskip('fitz')
import local_report_builder as builder
import pdf_page_check
import test_local_report_style as style

SOFFICE = shutil.which('soffice') or shutil.which('libreoffice')


@pytest.mark.skipif(not SOFFICE, reason='LibreOffice not installed')
@pytest.mark.parametrize('rows', [14, 15, 21, 22, 25, 26, 33])
def test_no_blank_trailing_page(tmp_path, rows):
    d = style.data(); d['otc'] = []; d['ceased'] = []; d['path'] = []
    d['meds'] = [['Medicine %d 50mg Tablet' % i, 'Taking confirmed - actual directions not recorded', '', ''] for i in range(rows)]
    docx = tmp_path / 'r.docx'; builder.render(d, docx)
    subprocess.run([SOFFICE, '--headless', '--convert-to', 'pdf', '--outdir', str(tmp_path), str(docx)], check=True, capture_output=True, timeout=100)
    counts = pdf_page_check.check(str(tmp_path / 'r.pdf'))
    assert counts and all(counts), counts
