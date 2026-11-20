"""Application-owned offline referral and clinical document extraction.

Extract source-attributed PDF text directly through bundled PyMuPDF. Scanned
pages use the bundled Windows OCR helper, where available. All text is
UNCONFIRMED; no clinical assertions or diagnoses are produced here.
"""
import hashlib
from pathlib import Path
import fitz

MAX_TOTAL_BYTES = 120 * 1024 * 1024
MAX_PAGES = 150
MIN_TEXT = 20


def extract(folder, image_dir):
    folder = Path(folder).resolve()
    image_dir = Path(image_dir).resolve()
    if image_dir.parent != folder or image_dir.exists():
        raise ValueError('Invalid extraction image directory')
    sources = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'
                     and not p.name.lower().startswith(('ppa consent', 'hmr interview')))
    if not sources:
        raise FileNotFoundError('No referral or pathology PDF available for extraction')
    if sum(p.stat().st_size for p in sources) > MAX_TOTAL_BYTES:
        raise ValueError('PDF extraction exceeds the 120 MB safety limit')
    total_pages = 0
    lines = ['APPLICATION-OWNED PDF EXTRACTION — ALL FACTS REQUIRE PHARMACIST SOURCE REVIEW',
             'Do not treat OCR text as confirmed data; verify units, medicine formulations and dates.']
    for source in sources:
        data = source.read_bytes()
        if not data.startswith(b'%PDF-'):
            raise ValueError('One source is not a PDF')
        digest = hashlib.sha256(data).hexdigest()
        try:
            with fitz.open(stream=data, filetype='pdf') as doc:
                if doc.needs_pass:
                    raise ValueError('Password protected PDF; open and review it manually')
                total_pages += doc.page_count
                if total_pages > MAX_PAGES:
                    raise ValueError('Extraction exceeds maximum of 150 pages')
                pages = [page.get_text('text', sort=True).strip() for page in doc]
        except (fitz.FileDataError, fitz.EmptyFileError) as exc:
            raise ValueError('Unreadable or damaged PDF; review original locally') from exc
        uncertain = [i for i, page in enumerate(pages) if len(page) < MIN_TEXT]
        if uncertain:
            import referral_entry
            try:
                extracted = referral_entry.parser().ocr_pdfs([source]).get(str(source), [])
            except Exception:
                extracted = []
            if len(extracted) == len(pages):
                for i in uncertain:
                    pages[i] = (extracted[i] or '').strip()
            else:
                # Missing OCR must not destroy the source or invent a result.
                for i in uncertain: pages[i] += '\n[OCR UNAVAILABLE — INSPECT ORIGINAL PDF]'
        lines.append('\nSOURCE: ' + source.name + ' | sha256: ' + digest)
        for i, page in enumerate(pages):
            method = 'OCR — UNCONFIRMED' if i in uncertain else 'PDF TEXT — UNCONFIRMED'
            lines.append('\n--- PAGE ' + str(i + 1) + ' (' + method + ') ---\n' +
                         (page or '[NO READABLE TEXT — VIEW ORIGINAL PDF]'))
    # Keep image_dir reserved for future previews; it is not needed to persist the
    # source-page mapping, because the originals are retained in the patient folder.
    return '\n'.join(lines)
