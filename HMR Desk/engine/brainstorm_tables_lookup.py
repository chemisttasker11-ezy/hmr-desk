"""Packaged Brainstorm tables lookup (read side).

Serves the reviewed extraction (references/brainstorm-mmr-v2.0-tables.json),
copied into the frozen engine's assets at package time with a hash-pin
manifest, as search hits the existing reference panel can render.

Honesty contract:
- Packaged hits are EXTRACTION excerpts, labelled as such. They are never
  claimed to be re-verified against the original PDF page at query time:
  v1 performs NO page re-verification (that is the stated re-check limit).
- "Open original" is only offered when the user's own registered private
  reference PDF exists and its byte hash equals the extraction's source
  hash. Opening shows the ORIGINAL page in the bundled viewer through the
  existing reference_library.open_source contract; the extraction is never
  presented as the original.
- Tamper, truncation, version drift or internal digest mismatch fail
  closed with TablesUnavailable. There is no fallback that upgrades an
  unverified hit into a trusted-looking one.

Raw source strings only. No clinical interpretation, validation, currency
or permission is implied. The reference is a writing guide; the clinician
remains responsible and must check current sources.
"""
import hashlib
import json
import re

import app_paths
import brainstorm_tables


class TablesUnavailable(ValueError):
    pass


DATA_FILENAME = 'brainstorm-mmr-v2.0-tables.json'
MANIFEST_FILENAME = 'brainstorm-tables-manifest.json'

MAX_QUERY_CHARS = 200
MAX_QUERY_WORDS = 12
MAX_RESULTS = 20
SNIPPET_LIMIT = 2000

DISCLAIMER = ('Packaged extraction from the Brainstorm writing guide, not re-verified against the '
              'original page. Writing guide only - not validated current clinical rules. '
              'Cross-check current clinical sources; pharmacist review required.')

_cache = None


def _paths():
    root = app_paths.engine_assets()
    return root / MANIFEST_FILENAME, root / DATA_FILENAME


def reset_cache():
    global _cache
    _cache = None


def load():
    """Read and integrity-check the packaged tables. Fails closed."""
    global _cache
    if _cache is not None:
        return _cache
    manifest_path, data_path = _paths()
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        raw = data_path.read_bytes()
    except (OSError, json.JSONDecodeError):
        raise TablesUnavailable('Packaged Brainstorm tables are not installed') from None
    digest = hashlib.sha256(raw).hexdigest()
    if not isinstance(manifest, dict) or manifest.get('file') != DATA_FILENAME or manifest.get('sha256') != digest:
        raise TablesUnavailable('Packaged Brainstorm tables failed integrity verification') from None
    try:
        structure = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TablesUnavailable('Packaged Brainstorm tables are unreadable') from None
    if structure.get('citation_version') != brainstorm_tables.CITATION_VERSION:
        raise TablesUnavailable('Unsupported packaged Brainstorm tables version') from None
    entries = structure.get('entries')
    source = structure.get('source')
    if not isinstance(entries, list) or not isinstance(source, dict) or not source.get('pdf_sha256'):
        raise TablesUnavailable('Packaged Brainstorm tables are incomplete') from None
    for entry in entries:
        if brainstorm_tables._entry_digest(entry) != entry.get('content_sha256'):
            raise TablesUnavailable('Packaged Brainstorm tables entry digest mismatch') from None
    _cache = structure
    return structure


def entry_text(entry):
    """Rebuild an entry's searchable text exactly as verification does."""
    return ' '.join((f['label'] + ' ' + f['text']) if f['label'] else f['text']
                    for f in entry['fields'])


def _snippet(text, patterns):
    match = None
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            break
    if not match:
        return text[:SNIPPET_LIMIT], False, len(text) > SNIPPET_LIMIT
    start = max(0, match.start() - 300)
    end = min(len(text), match.end() + (SNIPPET_LIMIT - 300))
    return text[start:end], start > 0, end < len(text)


def _openable(source):
    """True only when the user's registered private PDF is the exact source."""
    try:
        import reference_library
        current = reference_library.current()
    except Exception:
        return False
    return current.get('pdf_sha256') == source.get('pdf_sha256')


def public_reference(structure):
    source = structure['source']
    return {'edition': source.get('edition', '') + ' (packaged tables)',
            'page_count': source.get('page_count'),
            'pdf_sha256': source.get('pdf_sha256'),
            'packaged': True,
            'page_reverified': False}


def search(query):
    words = str(query).casefold().split()
    if len(words) > MAX_QUERY_WORDS or len(query) > MAX_QUERY_CHARS:
        raise TablesUnavailable('Search is too long')
    structure = load()
    source = structure['source']
    if not words:
        return {'reference': public_reference(structure), 'results': []}
    openable = _openable(source)
    patterns = [re.escape(w) for w in words]
    results = []
    for entry in structure['entries']:
        text = entry_text(entry)
        haystack = (entry['title'] + ' ' + text).casefold()
        if not all(w in haystack for w in words):
            continue
        snippet, omitted_before, omitted_after = _snippet(text, patterns)
        results.append({
            'title': entry['title'],
            'snippet': snippet,
            'omitted_before': omitted_before,
            'omitted_after': omitted_after,
            'page': entry['page_start'],
            'section_page': entry['page_start'],
            'section_page_end': entry['page_end'],
            'ordinal': entry['ordinal'],
            'edition': source.get('edition', ''),
            'pdf_sha256': source.get('pdf_sha256'),
            'openable': openable,
            'page_verified': False,
            'source': 'Brainstorm packaged tables (extraction, not re-verified against the original page)',
            'disclaimer': DISCLAIMER,
        })
        if len(results) >= MAX_RESULTS:
            break
    return {'reference': public_reference(structure), 'results': results}
