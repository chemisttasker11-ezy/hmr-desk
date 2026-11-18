"""Windows CI: the frozen engine converts a synthetic DOCX to PDF the way the desktop launches it.

The desktop starts the engine without a console and with stdin, stdout and stderr ignored. A plain-Python
conversion test cannot see failures that exist only in that launch, so this runs the real executable detached.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def main():
    engine = Path(sys.argv[1]).resolve()
    converter = (Path(__file__).resolve().parents[1] / 'vendor' / 'libreoffice' / 'program' / 'soffice.exe').resolve()
    assert engine.is_file() and converter.is_file(), 'frozen engine or bundled converter missing'
    with tempfile.TemporaryDirectory(prefix='hmr-frozen-pdf-') as d:
        out = Path(d) / "folder with spaces & o'brien"
        report = Path(d) / 'self-test-result.txt'
        env = {**os.environ, 'HMR_PDF_CONVERTER': str(converter)}
        flags = DETACHED_PROCESS if os.name == 'nt' else 0
        with open(report, 'wb') as sink:
            process = subprocess.run([str(engine), '--self-test-pdf', str(out)], env=env, stdin=subprocess.DEVNULL,
                                     stdout=sink, stderr=subprocess.STDOUT, creationflags=flags, timeout=240)
        text = report.read_text(errors='replace').strip()
        print(text)
        pdfs = list(out.glob('*.pdf'))
        assert process.returncode == 0 and text.startswith('PASS'), 'Frozen engine PDF conversion failed'
        assert len(pdfs) == 1 and pdfs[0].read_bytes().startswith(b'%PDF-'), 'No valid PDF beside the Word file'
        assert not [x for x in out.iterdir() if x.name.startswith('.hmr-pdf-')], 'Staging left behind'
    print('PASS: frozen engine launched detached with closed stdin converted a synthetic DOCX to PDF')


if __name__ == '__main__':
    main()
