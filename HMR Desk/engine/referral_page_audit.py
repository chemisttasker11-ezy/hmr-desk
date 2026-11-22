"""PHI-free page risk signals for local HMR referral source review.

A PDF text layer is not evidence that image-only content on that page was read.
This module deliberately does not OCR, infer field values, or invent coordinates.
"""

import fitz

MIN_NATIVE_TEXT = 25
MIN_IMAGE_FRACTION = 0.20
MAX_OVERLAPPING_WORDS = 5



def inspect_page(page):
    """Return non-clinical page layout metrics and an explicit mixed-page risk.

    Counts are observational signals, NOT an accuracy score. Some native words
    may overlie an image (a searchable scan); other native words may sit outside
    an image containing important unrecognised clinical facts.
    """
    native = page.get_text("text")
    words = page.get_text("words")
    page_rect = page.rect
    page_area = max(float(page_rect.width * page_rect.height), 1.0)
    image_area = 0.0
    unknown_image_regions = 0
    image_count = 0
    for item in page.get_image_info():
        if not item.get("bbox"):
            continue
        image_rect = fitz.Rect(item["bbox"]) & page_rect
        if image_rect.is_empty:
            continue
        image_count += 1
        area = max(float(image_rect.width * image_rect.height), 0.0)
        image_area += area
        overlap = 0
        for word in words:
            centre = fitz.Point((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)
            if image_rect.contains(centre):
                overlap += 1
        if area / page_area >= MIN_IMAGE_FRACTION and overlap <= MAX_OVERLAPPING_WORDS:
            unknown_image_regions += 1
    image_fraction = min(image_area / page_area, 1.0)
    native_present = len(native.strip()) >= MIN_NATIVE_TEXT
    return {
        "native_characters": len(native.strip()),
        "native_word_count": len(words),
        "image_count": image_count,
        "image_fraction": round(image_fraction, 4),
        "rotation": int(page.rotation),
        "native_present": native_present,
        "needs_image_review": native_present and unknown_image_regions > 0,
        "unread_image_regions": unknown_image_regions,
    }
