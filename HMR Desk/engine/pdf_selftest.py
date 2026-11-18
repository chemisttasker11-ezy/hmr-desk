"""Packaged-engine PDF check used by CI.

Converts a synthetic Word file with this executable's own runtime and the configured converter. It touches no
patient data, database or network. The packaged engine has no console, so the verdict goes to a result file.
"""
from pathlib import Path


def run(directory, result_file=None):
    import docx
    import pdf_export
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "Synthetic O'Brien & Test.docx"
    try:
        document = docx.Document()
        document.add_paragraph('Synthetic packaged-engine PDF self-test. No patient data.')
        document.save(source)
        result = pdf_export.convert(source, source.with_suffix('.pdf'))
        line, code = 'PASS: packaged engine produced a PDF (%s bytes)' % result['bytes'], 0
    except Exception as exc:
        line, code = 'FAIL: ' + pdf_export.failure_text(exc), 1
    if result_file:
        Path(result_file).write_text(line + '\n', encoding='utf-8')
    else:
        print(line)
    return code
