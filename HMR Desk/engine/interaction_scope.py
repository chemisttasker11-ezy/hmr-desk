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


def _classify(name, keys, checked, ingredients):
    """on_list: same name as a confirmed entry. ingredient_only: shares an ingredient with an entry, which does not
    establish the same product, strength or combination. off_list: no shared ingredient and every lookup worked.
    unmatched: matching was unavailable or incomplete, so nothing is claimed either way."""
    if _norm(name) in keys: return 'on_list'
    if not ingredients: return 'unmatched'
    try:
        mine = set(ingredients(name))
        theirs = [set(ingredients(n)) for n in checked]
    except Exception:
        return 'unmatched'
    if mine and any(mine & t for t in theirs): return 'ingredient_only'
    if mine and all(theirs): return 'off_list'
    return 'unmatched'


def compute(confirmed, rows, evidence, ingredients=None, duplicates=None):
    """confirmed: names on the confirmed list, or None. rows: dicts with name, status, source, has_text.
    Membership of the confirmed list is not proof that an interaction check covered a medicine."""
    checked = [n for n in (confirmed or []) if str(n).strip()]
    keys = {_norm(n) for n in checked}
    groups = {'on_list': [], 'ingredient_only': [], 'off_list': [], 'unmatched': []}
    not_using = []
    row_notes = []  # parallel to not_using: this row's own recorded reason, verbatim, never pooled by name or inferred
    for row in rows:
        name, status = str(row.get('name', '')).strip(), row.get('status', '')
        if not name: continue
        if status == 'not_using':
            not_using.append(name)
            row_notes.append(' '.join(str(row.get('note', '')).split()))
        elif status == 'unknown' or (not status and row.get('has_text')):
            groups[_classify(name, keys, checked, ingredients)].append(name)
    # A row recorded as not using can carry the same name as another row recorded as taking. Name equality does not show that
    # they are duplicates or the same product, and it does not show what any interaction result covered. The row stays listed
    # as not using; the statement only adds the factual row-status note so the two lines do not read as a contradiction.
    # Only an explicit taking row counts. Confirmed-list membership alone proves neither a status nor coverage.
    active = {_norm(r.get('name')) for r in rows if r.get('status') == 'taking' and str(r.get('name', '')).strip()}
    namesake = [n for n in not_using if _norm(n) in active]
    return {'evidence': evidence, 'checked': checked, 'not_using': not_using, 'not_using_namesake': namesake, 'not_using_row_notes': row_notes, 'duplicates': list(duplicates or []), **groups}


GROUPS = ('on_list', 'ingredient_only', 'off_list', 'unmatched')


def has_unconfirmed(scope):
    return any(scope[g] for g in GROUPS)


def lines(scope):
    ev = scope['evidence']
    out = [{
        'automated_current': 'Interaction check: an eMIMS result for the current confirmed medicine list is on file. The app does not verify which products the result covered.',
        'manual_note': 'Interaction check: only a manually saved interaction note is on file. The app has not verified what it covers.',
        'stale': 'Interaction check: the saved result does not match the current confirmed medicine list. There is no current result.',
        'none': 'Interaction check: no interaction result is on file.',
        'no_current_confirmation': 'Interaction check: the medicine list has not been confirmed for the current interview, so no interaction check applies to it.',
    }[ev]]
    if scope['on_list']:
        out.append('On the confirmed medicine list although use is not confirmed: ' + ', '.join(scope['on_list']) + '. List membership is not proof that an interaction check covered it' + ('.' if ev == 'automated_current' else ', and no current result verifies coverage.'))
    if scope['ingredient_only']:
        out.append('Share an ingredient with a confirmed entry, not established as the same product, strength or combination: ' + ', '.join(scope['ingredient_only']) + '. Coverage is not established.')
    if scope['off_list']:
        out.append('Not on the confirmed medicine list: ' + ', '.join(scope['off_list']) + '. Any interaction result for the list does not cover them.')
    if scope['unmatched']:
        out.append('Could not be matched to the confirmed medicine list (use not confirmed): ' + ', '.join(scope['unmatched']) + '. Check manually.')
    if scope['not_using']:
        dup = {_norm(n) for n in scope.get('not_using_namesake', [])}
        shown = [n + ' (another row with this name is recorded as taking)' if _norm(n) in dup else n for n in scope['not_using']]
        out.append('Recorded as not using, not part of the check: ' + ', '.join(shown) + '.')
        # Each row's own reason, in full, on its own line. Rows that share a name are told apart by their order in the record.
        row_notes = scope.get('not_using_row_notes') or [''] * len(scope['not_using'])
        for n, (name, note) in enumerate(zip(scope['not_using'], row_notes)):
            if not note: continue
            same = [k for k, other in enumerate(scope['not_using']) if _norm(other) == _norm(name)]
            which = ' (entry ' + str(same.index(n) + 1) + ' of ' + str(len(same)) + ' recorded as not using with this name)' if len(same) > 1 else ''
            out.append('Recorded reason for ' + name + which + ': ' + note)
    for state in scope.get('duplicates', []):
        out.append(('Pharmacist confirmed a duplicate entry: ' + state['name'] + ' and ' + state['target_name'] + '. This does not record which entry is in use; use is as recorded on each entry.'
                    + (' Pharmacist note: ' + ' '.join(state['note'].split()) if state['note'].strip() else ''))
                   if state['current'] else ('An earlier duplicate confirmation for ' + state['name'] + ' is no longer current. Check by hand.'))
    if has_unconfirmed(scope):
        out.append('Medicine reconciliation is incomplete. Any interaction conclusion is limited to the confirmed medicine list.')
    return out


def needs_statement(scope):
    return scope['evidence'] != 'automated_current' or has_unconfirmed(scope) or bool(scope.get('duplicates'))


def row_tag(scope, name):
    key = _norm(name)
    for group, text in (
        ('on_list', 'On the confirmed list, use not confirmed. Interaction coverage ' + ('rests on the eMIMS result for the list' if scope['evidence'] == 'automated_current' else 'is not verified')),
        ('ingredient_only', 'Shares an ingredient with a confirmed entry only. Coverage not established. Use not confirmed'),
        ('off_list', 'Not on the confirmed list, use not confirmed. Not covered by the list result'),
        ('unmatched', 'Could not be matched to the confirmed list. Use not confirmed. Check manually'),
    ):
        if key in {_norm(n) for n in scope[group]}: return 'Interaction check: ' + text
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


def evidence_files(conn, p):
    """Every saved interaction result with its kind, when it was saved and whether it counts as current evidence.
    A rerun adds a file; nothing is replaced. The list is for display and for the build record."""
    import records, steps
    confirmed_stamp = records.stamp(conn, p['id'], 'confirmed_meds.json')
    out = []
    for name in records.names_like(conn, p['id'], 'mims interactions'):
        if not name.lower().endswith('.txt'): continue
        automated = name.lower().startswith('mims interactions generated')
        saved = records.stamp(conn, p['id'], name)
        if automated: current = bool(steps.interactions_result_current(conn, p, name))
        else: current = confirmed_stamp is not None and saved is not None and saved >= confirmed_stamp
        out.append({'name': name, 'kind': 'automated' if automated else 'manual', 'saved_at': saved, 'current': current})
    out.sort(key=lambda f: (f['saved_at'] or '', f['name']))
    return out


def evidence_digest(conn, p):
    """Changes when the evidence state changes or a current result file is added, replaced or rewritten.
    Recorded in the build evidence so a later check marks the report outdated for review."""
    import hashlib, json, records
    current = []
    for f in evidence_files(conn, p):
        if f['current']:
            body = records.get(conn, p['id'], f['name']) or b''
            current.append([f['name'], hashlib.sha256(body).hexdigest()])
    return hashlib.sha256(json.dumps([evidence_state(conn, p), current], sort_keys=True).encode()).hexdigest()


def _recorded_reason(meta):
    """The reason the pharmacist recorded for a not-using row: the chosen label and the free text, as saved."""
    import interview
    if meta.get('use_status') != 'not_using': return ''
    parts = [interview.USE_LABELS.get(meta.get('use_reason') or '', ''), str(meta.get('use_details') or '').strip()]
    return ': '.join(x for x in parts if x)


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
                rows.append({'name': row[0], 'status': meta.get('use_status', ''), 'source': key, 'has_text': bool(row[col].strip()),
                             'note': _recorded_reason(meta)})
    names = [m[0] for m in confirmed['meds']] if isinstance(confirmed, dict) and isinstance(confirmed.get('meds'), list) else None
    return compute(names, rows, evidence_state(conn, p), external_helpers.ingredient_names, interview.duplicate_state(data) if data is not None else [])


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
