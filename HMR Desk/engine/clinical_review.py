"""Per-field PDF page provenance for pharmacist-confirmed referral facts.

Version 2 reviews record the original PDF page separately for each clinical
field (conditions, allergies, medicines, observations), so a multi-page
referral is traced field by field. Version 1 reviews carried one page for
everything; they are read by treating that page as the page of each populated
field, and are never silently upgraded on disk.
"""

FIELDS = ('conditions', 'allergies', 'medicines', 'observations')


def populated(review, field):
    """True when the review carries a clinical fact for this field."""
    if field == 'allergies':
        return (review.get('allergies_status') == 'explicit_none' or
                bool(str(review.get('allergies') or '').strip()))
    return bool(str(review.get(field) or '').strip())


def page_map(review):
    """Return {field: page} for every field; 0 means no page recorded."""
    pages = review.get('source_pages')
    if isinstance(pages, dict):
        return {field: pages[field] if type(pages.get(field)) is int else 0 for field in FIELDS}
    legacy = review.get('source_page', 0)
    legacy = legacy if type(legacy) is int else 0
    return {field: legacy if populated(review, field) else 0 for field in FIELDS}


def field_page(review, field):
    """Page that supports one populated field, or 0 when unsupported."""
    if not populated(review, field):
        return 0
    return page_map(review)[field]


def is_reviewed(review):
    """A named pharmacist confirmed every populated field against a page."""
    if not isinstance(review, dict) or review.get('confirmed') is not True:
        return False
    reviewer = review.get('reviewed_by')
    if not isinstance(reviewer, str) or len(reviewer.strip()) < 3:
        return False
    pages = page_map(review)
    filled = [field for field in FIELDS if populated(review, field)]
    if 'source_pages' not in review:
        # Version 1 compatibility: one page that must be real.
        return type(review.get('source_page')) is int and review['source_page'] >= 1
    return bool(filled) and all(pages[field] >= 1 for field in filled)


def origin(review, field):
    page = field_page(review, field)
    return 'referral.pdf page ' + str(page) if page >= 1 else 'referral.pdf (page not recorded)'
