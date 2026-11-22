"""Rendered image of the referral page region a medicine row was read from, for the pharmacist to compare by eye.

This is source evidence only. It says where the text was read from, not that the text is right and not that the medicine is in
current use. Nothing is written to disk and no path comes from the caller: the referral file is found in the patient's own folder,
and it must still be the exact PDF (SHA-256) the row was read from. When a safe crop cannot be established the whole page is shown;
when even the page cannot be established nothing is rendered and the caller says so."""
import base64
import hashlib
from pathlib import Path

import interview

ROW_DPI = 220
PAGE_DPI = 110
PAD_POINTS = 4.0
MAX_ROW_HEIGHT_FRACTION = 0.5     # a "row" taller than half the page is not a row crop worth trusting


def _referral_pdf(folder):
    base = Path(folder).resolve()
    for f in interview.referral_files(Path(folder)):
        if f.is_symlink(): continue
        real = f.resolve()
        if real.parent == base: return real
    return None


def render(folder, meta):
    """meta: the details.meds entry for one row. Returns a JSON-safe dict: kind row|page|none, note, and png (base64) unless none."""
    import fitz
    evidence = meta.get('source_evidence') if isinstance(meta, dict) else None
    if not evidence: return {'kind': 'none', 'note': 'This row was not read from the referral, so there is no page region to show.'}
    loc = evidence.get('location')
    pages = sorted({n for group in evidence.get('page_candidates', []) for n in group})
    pdf = _referral_pdf(folder)
    if pdf is None: return {'kind': 'none', 'note': 'The referral PDF was not found in the patient folder. Open the original from the Files tab.'}
    data = pdf.read_bytes()
    with fitz.open(stream=data, filetype='pdf') as doc:
        if loc:
            if hashlib.sha256(data).hexdigest() != loc['pdf_sha256']:
                return {'kind': 'none', 'note': 'The referral PDF in the folder is not the file this row was read from, so no page image is shown. Open the original and compare by eye.'}
            number = loc['page']
        elif len(pages) == 1:
            number = pages[0]       # page candidates come from text only; the file is not hash-bound here, so say so
        else:
            return {'kind': 'none', 'note': 'The page this row came from could not be established. Open the original PDF and compare by eye.'}
        if not 1 <= number <= len(doc): return {'kind': 'none', 'note': 'The recorded page is not in the referral PDF. Open the original and compare by eye.'}
        page = doc[number - 1]
        bound = page.rect
        if loc:
            x0, y0, x1, y1 = loc['box']
            clip = fitz.Rect(x0 - PAD_POINTS, y0 - PAD_POINTS, x1 + PAD_POINTS, y1 + PAD_POINTS) & bound
            if not clip.is_empty and clip.height <= MAX_ROW_HEIGHT_FRACTION * bound.height and clip.width > 10 and clip.height > 4:
                png = page.get_pixmap(matrix=fitz.Matrix(ROW_DPI / 72, ROW_DPI / 72), clip=clip, alpha=False).tobytes('png')
                return {'kind': 'row', 'page': number, 'png': base64.b64encode(png).decode('ascii'),
                        'note': 'Region of page %d where this row was read. It may show edges of neighbouring rows. For comparison only: it does not show current use and has not been checked for correctness.' % number}
        png = page.get_pixmap(matrix=fitz.Matrix(PAGE_DPI / 72, PAGE_DPI / 72), alpha=False).tobytes('png')
        why = 'A safe crop of this row could not be established' if loc else 'The exact row position was not recorded and the file is not verified as the one this row was read from'
        return {'kind': 'page', 'page': number, 'png': base64.b64encode(png).decode('ascii'),
                'note': why + ', so the whole of page %d is shown. For comparison only: it does not show current use and has not been checked for correctness.' % number}
