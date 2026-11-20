"""What an interaction check can and cannot claim, derived from current records.

The check is run on the confirmed medicine list. Medicines whose use is not
confirmed may or may not be on that list, and a result file may be missing, stale
or only a manual note. This module states exactly that. It never clears anything
and it adds no gate: the pharmacist can still document uncertainty.
"""
import re

EVIDENCE = ('automated_current', 'manual_note', 'stale', 'none', 'no_current_confirmation')


def _norm(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').casefold())


def compute(confirmed, rows, evidence, ingredients=None):
    """confirmed: names on the confirmed list, or None. rows: dicts with name, status, source, has_text."""
    checked = [n for n in (confirmed or []) if str(n).strip()]
    keys = {_norm(n) for n in checked}
    def on_list(name):
        if _norm(name) in keys: return True
        if ingredients:
            try:
                mine = set(ingredients(name))
                return bool(mine) and any(mine & set(ingredients(n)) for n in checked)
            except Exception:
                return False
        return False
    included, excluded, not_using = [], [], []
    for row in rows:
        name, status = str(row.get('name', '')).strip(), row.get('status', '')
        if not name: continue
        if status == 'not_using':
            not_using.append(name)
        elif status == 'unknown' or (not status and row.get('has_text')):
            (included if on_list(name) else excluded).append(name)
    return {'evidence': evidence, 'checked': checked, 'included_unconfirmed': included,
            'excluded_unconfirmed': excluded, 'not_using': not_using}


def lines(scope):
    ev = scope['evidence']
    out = []
    out.append({
        'automated_current': 'Interaction check: an eMIMS result matching the confirmed medicine list is on file.',
        'manual_note': 'Interaction check: only a manually saved interaction note is on file. The app has not verified that it covers the confirmed medicine list.',
        'stale': 'Interaction check: the saved result does not match the current confirmed medicine list. There is no current result.',
        'none': 'Interaction check: no interaction result is on file.',
        'no_current_confirmation': 'Interaction check: the medicine list has not been confirmed for the current interview, so no interaction check applies to it.',
    }[ev])
    if scope['included_unconfirmed']:
        out.append('Included in the checked list although use is not confirmed: ' + ', '.join(scope['included_unconfirmed']) + '.')
    if scope['excluded_unconfirmed']:
        out.append('Not in the checked list because use is not confirmed: ' + ', '.join(scope['excluded_unconfirmed']) + '. Interactions with these were not checked.')
    if scope['not_using']:
        out.append('Recorded as not using, not part of the check: ' + ', '.join(scope['not_using']) + '.')
    if scope['included_unconfirmed'] or scope['excluded_unconfirmed']:
        out.append('Medicine reconciliation is incomplete. Any interaction conclusion applies only to the checked list.')
    return out


def needs_statement(scope):
    return scope['evidence'] != 'automated_current' or bool(scope['included_unconfirmed'] or scope['excluded_unconfirmed'])


def row_tag(scope, name):
    key = _norm(name)
    if key in {_norm(n) for n in scope['excluded_unconfirmed']}:
        return 'Interaction check: NOT included (use not confirmed)'
    if key in {_norm(n) for n in scope['included_unconfirmed']}:
        return 'Interaction check: included although use is not confirmed'
    return ''


def evidence_state(conn, p):
    import records, steps, medicine_review
    confirmed = records.get(conn, p['id'], 'confirmed_meds.json')
    if confirmed is None or not medicine_review.confirmed_medicines_current(conn, p): return 'no_current_confirmation'
    stamp = records.stamp(conn, p['id'], 'confirmed_meds.json')
    seen = manual = False
    for name in records.names_like(conn, p['id'], 'mims interactions'):
        if not name.lower().endswith('.txt'): continue
        seen = True
        if name.lower().startswith('mims interactions generated'):
            if steps.interactions_result_current(conn, p, name): return 'automated_current'
        elif records.stamp(conn, p['id'], name) >= stamp:
            manual = True
    return 'manual_note' if manual else ('stale' if seen else 'none')


def for_patient(conn, p):
    import records, interview, external_helpers
    data = records.get_json(conn, p['id'], 'interview.json')
    confirmed = records.get_json(conn, p['id'], 'confirmed_meds.json')
    rows = []
    if data is not None:
        interview.validate(data)
        for key in ('meds', 'other_meds'):
            col = 2 if key == 'meds' else 1
            for row, meta in zip(data.get(key, []), data.get('details', {}).get(key, [])):
                rows.append({'name': row[0], 'status': meta.get('use_status', ''), 'source': key, 'has_text': bool(row[col].strip())})
    names = [m[0] for m in confirmed['meds']] if isinstance(confirmed, dict) and isinstance(confirmed.get('meds'), list) else None
    return compute(names, rows, evidence_state(conn, p), external_helpers.mims.ingredients)


def apply_to_report(conn, p, data):
    """A copy of the report data with row tags and a scope statement. Computed at build time; not stored."""
    scope = for_patient(conn, p)
    out = dict(data)
    for key in ('meds', 'otc'):
        rows = []
        for row in data.get(key, []):
            tag = row_tag(scope, row[0])
            row = list(row)
            if tag: row[2] = (row[2] + '\n' if row[2] else '') + tag
            rows.append(row)
        out[key] = rows
    out['interaction_scope_note'] = '\n'.join(lines(scope)) if needs_statement(scope) else ''
    return out, scope
