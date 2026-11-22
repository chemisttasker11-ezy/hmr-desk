"""Read-only page layout signals for source-fidelity review of referrals.

A large raster with searchable text over it is NOT proof that its OCR layer
matches the underlying pixels. Never mark it as safely read merely because
many native PDF words overlap the raster.
"""
import fitz

MIN_NATIVE_TEXT = 25
MIN_IMAGE_FRACTION = 0.20
MAX_OVERLAPPING_WORDS = 5


def inspect_page(page):
    """Describe image regions, separate searchable overlay from unread regions.

    This produces layout signals only. No diagnosis, directions, or source
    association can be inferred or confirmed from these counts.
    """
    native = page.get_text("text")
    words = page.get_text("words")
    bounds = page.rect
    total_area = max(float(bounds.width * bounds.height), 1.0)
    image_area = 0.0
    images = 0
    large_regions = 0
    text_layer_regions = 0
    unread_regions = 0
    for entry in page.get_image_info():
        if not entry.get("bbox"):
            continue
        region = fitz.Rect(entry["bbox"]) & bounds
        if region.is_empty:
            continue
        images += 1
        area = max(float(region.width * region.height), 0.0)
        image_area += area
        if area / total_area < MIN_IMAGE_FRACTION:
            continue
        large_regions += 1
        overlapping_words = sum(
            1 for word in words if region.contains(
                fitz.Point((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)
            )
        )
        if overlapping_words > MAX_OVERLAPPING_WORDS:
            text_layer_regions += 1
        else:
            unread_regions += 1
    native_present = len(native.strip()) >= MIN_NATIVE_TEXT
    return {
        "native_characters": len(native.strip()),
        "native_word_count": len(words),
        "image_count": images,
        "image_fraction": round(min(image_area / total_area, 1.0), 4),
        "rotation": int(page.rotation),
        "native_present": native_present,
        "needs_image_review": native_present and large_regions > 0,
        "large_image_regions": large_regions,
        "text_layer_over_image_regions": text_layer_regions,
        "unread_image_regions": unread_regions,
    }
