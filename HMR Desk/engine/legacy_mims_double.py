"""Synthetic stand-in for the licensed MIMS list helper, for the legacy script tests only.

The real `MIMS Interaction Helper/make-lists.py` is not in the repository, and the product deliberately does not
infer ingredients without it (see manual_medicine_names). The legacy API script asserts how the list wiring and the
workflow behave when a helper IS present. This double implements just enough parsing for its synthetic inputs
("Aspirin 100 mg (Cartia)", "codeine: rash"). It proves the engine's wiring, NOT the real helper's ingredient,
brand or allergy parsing, which stays unverified until the real helper is available to a test.
"""
import re

SKIP = re.compile(r'^(?:\s*|nil|none|not known|unknown)$', re.I)
ALIASES = {}


def ingredients(name):
    if not isinstance(name, str) or SKIP.fullmatch(name.strip()):
        return []
    return [re.split(r'\s+\d|\s*\(', name.strip(), maxsplit=1)[0].strip().lower()]


def brand(name):
    found = re.search(r'\(([^)]+)\)', name or '')
    return found.group(1).strip().lower() if found else ''


def allergies(text):
    if isinstance(text, list):
        return [x for item in text for x in allergies(item)]
    if not isinstance(text, str):
        return []
    return [x.split(':')[0].strip().lower() for x in re.split(r'[\n;,]+', text) if x.strip()]
