"""Synthetic true-DOCX to PDF smoke test of the pinned local Windows converter."""
import os
from pathlib import Path
import sys
import tempfile
from docx import Document

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'HMR Desk' / 'engine'))
import pdf_export


def main():
    converter = (root / 'vendor' / 'libreoffice' / 'program' / 'soffice.exe').resolve()
    assert converter.is_file(), 'No local converter in package resources'
    os.environ['HMR_PDF_CONVERTER'] = str(converter)
    assert pdf_export.available()
    with tempfile.TemporaryDirectory(prefix='hmr-pdf-smoke-') as directory:
        path = Path(directory)
        source, target = path / 'Synthetic HMR Test.docx', path / 'Synthetic HMR Test.pdf'
        document = Document()
        document.add_heading('Synthetic HMR Test', level=1)
        document.add_paragraph('No real patient data. This is an offline PDF conversion test.')
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = 'Medicine'
        table.cell(0, 1).text = 'Actual directions'
        table.cell(1, 0).text = 'Synthetic example'
        table.cell(1, 1).text = 'Not provided'
        document.save(source)
        result = pdf_export.convert(source, target)
        assert result['created'] and target.read_bytes().startswith(b'%PDF-')
        assert source.is_file()
        try:
            pdf_export.convert(source, target)
            raise AssertionError('PDF overwrite unexpectedly allowed')
        except FileExistsError:
            pass
    print('PASS: portable LibreOffice converted real DOCX with a medicine table; refused overwrite')


if __name__ == '__main__':
    main()
