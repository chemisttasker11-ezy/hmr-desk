"""Conservative exact-phrase sig lookup and patient-safe rendering.

This is not a dose calculator or free-text prescription parser. Semicolons are
explicit phrase separators. Unknown text, conflicting slots and unsafe aliases
never produce an actionable structured plan. All output needs pharmacist review.
"""
import json
from pathlib import Path
from .catalog import normalise


def library():
    result = json.loads(Path(__file__).with_name('sigs.json').read_text(encoding='utf-8'))
    if result['schema_version'] != 1:
        raise ValueError('Unsupported sig schema')
    return result['entries']


def index():
    result = {}
    for entry in library():
        for alias in entry['aliases']:
            key = normalise(alias)
            if key in result and result[key]['id'] != entry['id']:
                raise ValueError(f'Duplicate sig alias {alias}')
            result[key] = entry
    return result


def combine(entries):
    result = {}
    frequency_ids = []
    for entry in entries:
        if entry['category'] == 'frequency' and entry['structured'].get('as_needed') is not True:
            frequency_ids.append(entry['id'])
        for key, value in entry['structured'].items():
            if isinstance(value, list):
                result.setdefault(key, [])
                result[key] = list(dict.fromkeys(result[key] + value))
            elif key in result and result[key] != value:
                raise ValueError(f'Conflicting sig values for {key}')
            else:
                result[key] = value
    # BD is not the same as every 12 hours, even though both can average 2/day.
    if len(set(frequency_ids)) > 1:
        raise ValueError('Multiple frequency phrases require pharmacist reconciliation')
    if len(result.get('timing_tags', [])) > 1:
        # Retain possible combinations as suggestions only, not auto-conjoin
        # incompatible before/after-food or morning/night timing constraints.
        raise ValueError('Multiple timing phrases require pharmacist reconciliation')
    return result


def parse(text):
    lookup = index()
    phrases = [normalise(text)] if normalise(text) in lookup else [normalise(p) for p in str(text).split(';') if p.strip()]
    unknown = [p for p in phrases if p not in lookup]
    found = [lookup[p] for p in phrases if p in lookup]
    warnings = [e['warning'] for e in found if e['warning']]
    unsafe = any(e['safety'] in ('ambiguous', 'error_prone') for e in found)
    conflict = None
    try:
        proposed = combine(found)
    except ValueError as exc:
        proposed, conflict = {}, str(exc)
        warnings.append(conflict)
    usable = bool(phrases) and not unknown and not unsafe and not conflict
    return {'original_text': text, 'matched_ids': [e['id'] for e in found],
            'unknown': unknown, 'warnings': warnings, 'review_required': True,
            'status': 'review' if usable else 'unresolved',
            'structured': proposed if usable else None,
            'patient_text': '; '.join(e['patient_text'] for e in found) if usable else None}


def render(entry_ids, *, pharmacist_confirmed=False):
    if pharmacist_confirmed is not True:
        raise ValueError('Pharmacist confirmation required before patient-facing rendering')
    by_id = {e['id']: e for e in library()}
    entries = [by_id[i] for i in entry_ids]
    if not entries or any(e['safety'] in ('ambiguous', 'error_prone') for e in entries):
        raise ValueError('Choose confirmed canonical phrases, not unsafe legacy aliases')
    combine(entries)
    return '; '.join(e['patient_text'] for e in entries)


def render_structure(structured, *, pharmacist_confirmed=False):
    """Render one exact known structure, not arbitrary dosing instructions.

    Compound plans must use reviewed canonical IDs. When two canonical phrases
    have identical structure, prefer the first full-English phrase in the curated
    library (e.g. every 14 days, rather than a legacy alias). No numeric guessing.
    """
    if not isinstance(structured, dict) or not structured:
        raise ValueError('A nonempty known sig structure is required')
    for entry in library():
        if entry['safety'] not in ('ambiguous', 'error_prone') and entry['structured'] == structured:
            return render([entry['id']], pharmacist_confirmed=pharmacist_confirmed)
    raise ValueError('Unknown/compound structure; select reviewed canonical phrase IDs')
