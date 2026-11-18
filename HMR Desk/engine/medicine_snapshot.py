"""Versioned, non-destructive medicine adapter. No matching or clinical inference.

Interview arrays remain the only editable source. Read adapters never assign IDs
or rewrite records. Stable IDs are assigned by the explicit locked save path.
"""
import copy
import hashlib
import json
import re
import uuid

VERSION = 1
SECTIONS = (('meds', 5), ('other_meds', 4))
ID = re.compile(r'^[0-9a-f]{32}$')


def valid_id(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def validate_ids(record):
    seen = set()
    if not isinstance(record, dict): raise ValueError('Invalid medicine record')
    details = record.get('details', {})
    if not isinstance(details, dict): raise ValueError('Invalid medicine details')
    for section, _ in SECTIONS:
        metadata = details.get(section, [])
        if not isinstance(metadata, list): raise ValueError('Invalid medicine metadata')
        for meta in metadata:
            if not isinstance(meta, dict): raise ValueError('Invalid medicine metadata')
            if 'item_id' not in meta:
                continue
            value = meta['item_id']
            if not valid_id(value) or value in seen:
                raise ValueError('Invalid or duplicate medicine item ID')
            seen.add(value)


def assign_ids(record):
    """Copy an already validated interview; caller supplies complete row metadata.

    Never guess missing metadata or clinical fields. Persist once under the
    existing interview revision lock, with original bytes retained for rollback.
    """
    validate_ids(record)
    result = copy.deepcopy(record)
    for section, _ in SECTIONS:
        rows = result.get(section, [])
        meta = result.get('details', {}).get(section, [])
        if len(meta) != len(rows):
            raise ValueError('Medicine metadata must be aligned before assigning IDs')
        for item in meta:
            item.setdefault('item_id', uuid.uuid4().hex)
    validate_ids(result)
    return result


def snapshot(record):
    """Lossless medicine-only projection including unknown metadata/ref fields.

    Legacy rows without IDs remain explicitly unassigned, not index-identities.
    Full interview/source/report revision guards remain independent.
    """
    validate_ids(record)
    items = []
    details = record.get('details', {})
    for section, width in SECTIONS:
        rows, metadata = record.get(section, []), details.get(section, [])
        if not isinstance(rows, list) or not isinstance(metadata, list) or (metadata and len(rows) != len(metadata)):
            raise ValueError('Invalid medicine table alignment')
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != width or not all(isinstance(x, str) for x in row):
                raise ValueError('Invalid medicine row')
            meta = metadata[index] if index < len(metadata) else None
            if meta is not None and not isinstance(meta, dict):
                raise ValueError('Invalid medicine metadata')
            items.append({'item_id': meta.get('item_id') if meta else None,
                          'source_section': section, 'source_index': index,
                          'values': copy.deepcopy(row), 'metadata': copy.deepcopy(meta)})
    allergies = record.get('allergies', '')
    if not isinstance(allergies, str): raise ValueError('Invalid allergy narrative')
    value = {'schema_version': VERSION, 'items': items, 'allergies': allergies}
    # Strict JSON guards against accidental nonfinite or nonserialisable metadata.
    json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value


def digest(value):
    if not isinstance(value, dict) or value.get('schema_version') != VERSION:
        raise ValueError('Unsupported medicine snapshot version')
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()
