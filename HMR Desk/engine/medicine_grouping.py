"""Group search rows that are the same listed product, without guessing.

Only PBS listing rows can be grouped, and only when every identity field below is
present and exactly equal after trimming. Missing or uncertain metadata keeps the
row on its own. Strength and pack text are never parsed: they are compared as the
source wrote them. Nothing is merged in storage; every listing keeps its own
source, code and release, so the chosen listing stays traceable.
"""
import json

# Fields that must match exactly for two PBS listings to share one line.
_IDENTITY_DETAIL_FIELDS = ('schedule_form', 'li_form', 'pack_size', 'manner_of_administration')
_REQUIRED_ANY = ('schedule_form', 'li_form')   # at least one form/strength text is needed
_LISTING_FIELDS = ('source', 'code', 'display', 'kind', 'generic_name', 'brand_name', 'dose_form', 'release')


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value and value.lower() != 'null' else None


def _details(row):
    raw = row.get('details', row.get('details_json'))
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def identity_key(row):
    """Return a hashable identity for a groupable PBS row, or None when uncertain."""
    if row.get('kind') != 'pbs_listing':
        return None
    details = _details(row)
    if details.get('pbs_listed') is not True:
        return None
    generic, brand = _text(row.get('generic_name')), _text(row.get('brand_name'))
    if not generic or not brand:
        return None
    fields = tuple(_text(details.get(name)) for name in _IDENTITY_DETAIL_FIELDS)
    if not any(_text(details.get(name)) for name in _REQUIRED_ANY):
        return None
    return (row.get('source'), row.get('kind'), generic, brand, _text(row.get('dose_form')), fields)


def _listing(row):
    details = _details(row)
    out = {key: row.get(key) for key in _LISTING_FIELDS}
    out['program_code'] = _text(details.get('program_code'))
    out['pbs_code'] = _text(details.get('pbs_code'))
    return out


def group_rows(rows, max_groups):
    """Return (groups, more_available). Order follows the first row of each group.

    Rows after the group limit can still join an existing group, so repeated
    listings are counted; a row that would need a new group sets more_available.
    """
    groups, index, more = [], {}, False
    for row in rows:
        key = identity_key(row)
        if key is not None and key in index:
            groups[index[key]]['listings'].append(_listing(row))
            continue
        if len(groups) >= max_groups:
            more = True
            continue
        entry = {'grouped': key is not None, 'listings': [_listing(row)]}
        if key is not None:
            details = _details(row)
            form = _text(details.get('schedule_form')) or _text(details.get('li_form'))
            entry['label'] = ' | '.join(filter(None, [key[3], form]))
            entry['generic_name'], entry['brand_name'] = key[2], key[3]
            index[key] = len(groups)
        else:
            entry['label'] = row.get('display')
        groups.append(entry)
    return groups, more


def finish(groups):
    for group in groups:
        group['count'] = len(group['listings'])
    return groups
