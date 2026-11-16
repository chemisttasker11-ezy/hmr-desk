"""Conservative offline names ONLY, not a clinical ingredient or interaction database.

Used to keep manual reconciliation functional when the separately licensed
MIMS portal/helper is not installed. NEVER infer brand/generic equivalence,
therapeutic duplication, interactions or clinical safety from this module.
"""
import re

SKIP = re.compile(r'^(?:\s*|nil|none|not known|unknown)$', re.I)
ALIASES = {}


def ingredients(name):
    if not isinstance(name, str) or SKIP.fullmatch(name.strip()):
        return []
    # Preserve the pharmacist-supplied formulation/strength text to avoid
    # claiming distinct products are the same ingredient.
    return [re.sub(r'\s+', ' ', name.strip()).casefold()]


def brand(name):
    return ''


def allergies(text):
    if isinstance(text, list):
        return [x.strip() for item in text for x in allergies(item)]
    if not isinstance(text, str):
        return []
    return [x.strip() for x in re.split(r'[\n;,]+', text) if x.strip()]
