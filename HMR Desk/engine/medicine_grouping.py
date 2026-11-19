"""Group search rows that are the same listed product, without guessing.

Only PBS listing rows can be grouped, and only when every identity field below is
present and exactly equal after trimming. Missing or uncertain metadata keeps the
row on its own. Strength text is never parsed: it is compared as the
source wrote them. Nothing is merged in storage; every listing keeps its own
source, code and release, so the chosen listing stays traceable.
"""
import json

# Fields that must match exactly for two PBS listings to share one line.
_IDENTITY_DETAIL_FIELDS = ('schedule_form', 'li_form', 'manner_of_administration')
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


def plain_label(row):
    """User-facing text without the billing code. Only a trailing ' | <pbs_code>' that
    pbs.py itself appended is removed; anything else is shown exactly as stored."""
    display = row.get('display') or ''
    code = _text(_details(row).get('pbs_code'))
    if row.get('kind') == 'pbs_listing' and code and display.endswith(' | ' + code):
        return display[:-len(' | ' + code)]
    return display


def group_rows(rows, max_groups):
    """Return (groups, more_available). Order follows the first row of each group.

    Rows after the group limit can still join an existing group, so repeated
    listings are counted; a row that would need a new group sets more_available.
    """
    groups, index, more = [], {}, False
    for position, row in enumerate(rows):
        key = identity_key(row)
        if key is not None and key in index:
            groups[index[key]]['listings'].append(_listing(row))
            groups[index[key]]['indexes'].append(position)
            continue
        if len(groups) >= max_groups:
            more = True
            continue
        entry = {'grouped': key is not None, 'listings': [_listing(row)], 'indexes': [position]}
        if key is not None:
            details = _details(row)
            form = _text(details.get('schedule_form')) or _text(details.get('li_form'))
            route = _text(details.get('manner_of_administration'))
            # Pack, bottle and blister size never separate lines. Form and route do.
            entry['label'] = ' | '.join(filter(None, [key[3], form, route.lower() if route else None]))
            entry['generic_name'], entry['brand_name'] = key[2], key[3]
            index[key] = len(groups)
        else:
            entry['label'] = plain_label(row)
        groups.append(entry)
    return groups, more


def finish(groups):
    """Order each group's listings by source code so the first one, the stored
    representative when the pharmacist picks the group, is deterministic."""
    seen = {}
    for group in groups:
        seen[group['label']] = seen.get(group['label'], 0) + 1
    for group in groups:
        if seen[group['label']] > 1 and not group['grouped']:
            # Same words, but the source details are incomplete or differ: never hide that.
            group['label'] += ' (source details incomplete, entry kept separate)'
        order = sorted(range(len(group['listings'])), key=lambda n: (str(group['listings'][n].get('source')), str(group['listings'][n].get('code'))))
        group['listings'] = [group['listings'][n] for n in order]
        group['indexes'] = [group['indexes'][n] for n in order]
        group['count'] = len(group['listings'])
    return groups
