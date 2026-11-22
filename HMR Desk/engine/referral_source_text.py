"""Source-only PDF text for referral analysis.

Owner's typed interview overlays must be ignored in this baseline-referral
stage. Identifiable PDF FreeText annotations are removed from the IN-MEMORY
document before text extraction. The original PDF bytes never change.

Flattened overlays and content-stream text boxes cannot reliably be distinguished
from original GP text without independent original-page adjudication. Do NOT
silently assign those fields to the GP; refer ambiguous pages for source review.
"""
import fitz

FREE_TEXT_ANNOTATION = fitz.PDF_ANNOT_FREE_TEXT


def exclude_typed_annotations(page):
    """Remove identifiable FreeText annotations from only the opened memory PDF.

    Call before all page text/word extraction and before deciding OCR fallback.
    No save is performed. Never delete highlight/note ink or arbitrary content.
    Return the count removed, which is a risk/coverage metric, not clinical data.
    """
    removed = 0
    for annot in list(page.annots() or []):
        if annot.type[0] == FREE_TEXT_ANNOTATION:
            page.delete_annot(annot)
            removed += 1
    return removed


def extract_original_pages(doc, *, max_chars=150000):
    """Return text pages and annotation-exclusion counts from the same document."""
    result, counts = [], []
    for page in doc:
        counts.append(exclude_typed_annotations(page))
        result.append(page.get_text()[:max_chars])
    return result, counts
