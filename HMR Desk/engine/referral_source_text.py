"""Non-destructive, source-preserving extraction of referral PDF text.

FreeText annotations can contain GP-authored clinical information. Never
remove or silently ignore them based on annotation type or colour. Preserve
page text exactly as PyMuPDF provides it, and independently surface
annotation contents for pharmacist source review. Neither the original file
nor the in-memory PDF page is modified.

A flattened annotation may be indistinguishable from native document text.
All extracted content is an unverified proposal, not established GP authorship.
"""
import fitz

MAX_ANNOTATIONS_PER_PAGE = 100
MAX_ANNOTATION_TEXT = 1200


def _freetext_evidence(page):
    """Only metadata for transparent visual review; never auto-promote values.

    More than MAX_ANNOTATIONS_PER_PAGE is flagged by the caller: this cap limits
    previews, not extraction of page text or access to the original document.
    """
    evidence = []
    total = 0
    for annot in page.annots() or ():
        if annot.type[0] != fitz.PDF_ANNOT_FREE_TEXT:
            continue
        total += 1
        if len(evidence) < MAX_ANNOTATIONS_PER_PAGE:
            info = annot.info or {}
            rect = annot.rect
            evidence.append({
                'type': 'FreeText',
                'text_unverified': str(info.get('content') or '')[:MAX_ANNOTATION_TEXT],
                'rect': [round(float(x), 2) for x in rect],
            })
    return {'count': total, 'details': evidence, 'truncated': total > len(evidence)}


def extract_original_pages(doc, *, max_chars=150000):
    """Return unmodified source-page text and separately marked annotations.

    The source may contain either original GP content or later overlays;
    neither content origin nor clinical correctness is inferred from the PDF
    annotation type. The annotation preview never replaces original page text.
    """
    pages, annotation_pages = [], []
    for page in doc:
        pages.append(page.get_text()[:max_chars])
        annotation_pages.append(_freetext_evidence(page))
    return pages, annotation_pages
