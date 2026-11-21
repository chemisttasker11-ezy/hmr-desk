"""Medicine review domain: the report spec reader, the proposed medicine list, interview usage, stopped-medicine
overlap and the confirmed-medicine snapshot check.

Moved verbatim from api.py so that steps, report and suggestion_context depend on this module rather than on the
API facade. The optional MIMS helper is reached as external_helpers.mims at call time (it can be patched there).
"""
import re
import json

import jobs
import medicine_snapshot
import records
import external_helpers


def report_data(conn, p):
    try:
        return records.get_json(conn, p['id'], 'report_spec.json')
    except ValueError:
        return None


def proposal(conn, p):
    saved = records.get_json(conn, p['id'], 'interview.json')
    if saved is not None:
        import interview
        data = saved; interview.validate(data)
        meds = []
        for key, actual in (('meds', 2), ('other_meds', 1)):
            rows = data.get(key, []); meta = data.get('details', {}).get(key, [{} for _ in rows])
            for row, detail in zip(rows, meta):
                status = detail.get('use_status', '')
                if row[0].strip() and (status == 'taking' or (not status and row[actual].strip())):
                    identity = interview.reference_identity(detail)  # catalogue-owned names only; otherwise the row text, as before
                    meds.append([identity['generic_name'] or row[0], identity['brand_name'] or ''])
        usage = interview_usage(conn, p)
        stopped = {name for item in usage if item['status'] == 'not_using' for name in external_helpers.ingredient_names(item['name'])}
        taking = {name for item in usage if item['status'] == 'taking' for name in external_helpers.ingredient_names(item['name'])}
        meds = [row for row in meds if not stopped.intersection(external_helpers.ingredient_names(row[0])) or set(external_helpers.ingredient_names(row[0])) <= taking]
        return {'meds': meds, 'allergies': [x.strip() for x in data['allergies'].splitlines() if x.strip()], 'proposed': True}
    path = jobs.interview_spec_path(p)
    stored_spec = records.get_json(conn, p['id'], 'interview_spec.json')
    spec = stored_spec if stored_spec is not None else (json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {})
    meds = []
    for row in spec.get('meds', []):
        text = row[0] if isinstance(row, list) and row else row
        if not isinstance(text, str) or external_helpers.mims.SKIP.match(text.strip()): continue
        for name in external_helpers.ingredient_names(text):
            if name not in [r[0] for r in meds]: meds.append([name, external_helpers.mims.brand(text) or ''])
    usage = interview_usage(conn, p)
    stopped = {name for item in usage if item['status'] == 'not_using' for name in external_helpers.ingredient_names(item['name'])}
    taking = {name for item in usage if item['status'] == 'taking' for name in external_helpers.ingredient_names(item['name'])}
    meds = [row for row in meds if row[0] not in stopped or row[0] in taking]
    allergy = spec.get('allergies', '')
    allergies = [item for text in allergy for item in external_helpers.mims.allergies(text) if isinstance(text, str)] if isinstance(allergy, list) else external_helpers.mims.allergies(allergy)
    return {'meds': meds, 'allergies': allergies, 'proposed': True}


def interview_usage(conn, p):
    data = records.get_json(conn, p['id'], 'interview.json')
    if data is None: return []
    import interview
    interview.validate(data)
    result = []
    details = data.get('details', {})
    for key in ('meds', 'other_meds'):
        for row, meta in zip(data.get(key, []), details.get(key, [])):
            if meta.get('use_status'):
                result.append({'name': row[0], 'status': meta['use_status'], 'detail': interview.use_text(meta), 'source': 'Referral medicine' if key == 'meds' else 'Found during interview', 'directions': row[1:3]})
    return result

def conflicting_medicines(conn, p, meds):
    stopped = {name for item in interview_usage(conn, p) if item['status'] == 'not_using' for name in external_helpers.ingredient_names(item['name'])}
    return [row[0] for row in meds if stopped.intersection(external_helpers.ingredient_names(row[0]))]

def relevant_usage(usage, meds):
    names = {name for row in meds for name in external_helpers.ingredient_names(row[0])}
    return [item for item in usage if names.intersection(external_helpers.ingredient_names(item['name']))]

def valid_alternatives(meds, usage, alternatives):
    stopped = [item for item in usage if item['status'] == 'not_using']
    if not isinstance(alternatives, list) or len(alternatives) != len(meds): return False
    def normal(value): return re.sub(r'[^a-z0-9]+', '', value.casefold())
    for row, choice in zip(meds, alternatives):
        names = set(external_helpers.ingredient_names(row[0]))
        overlap = {name for item in stopped for name in external_helpers.ingredient_names(item['name']) if name in names}
        if not overlap: continue
        if not isinstance(choice, dict) or choice not in usage or choice.get('status') != 'taking' or not overlap <= set(external_helpers.ingredient_names(choice['name'])): return False
        # The exact recorded taking product must be selected; ingredient overlap alone is ambiguous.
        if normal(row[0]) != normal(choice['name']) or any(normal(choice['name']) == normal(item['name']) for item in stopped): return False
    return True

def same_name_as_stopped(meds, usage):
    """Listed medicines whose name equals a medicine recorded as not using in the interview. No alternative can resolve these."""
    def normal(value): return re.sub(r'[^a-z0-9]+', '', value.casefold())
    stopped = {normal(item['name']) for item in usage if item['status'] == 'not_using'}
    return [row[0] for row in meds if normal(row[0]) in stopped]


def current_medicine_snapshot(conn, p):
    data = records.get_json(conn, p['id'], 'interview.json')
    if data is None: return None
    import interview
    interview.validate(data)
    return medicine_snapshot.snapshot(data)


def confirmed_medicines_current(conn, p):
    data = records.get_json(conn, p['id'], 'confirmed_meds.json')
    if data is None: return False
    try:
        current_snapshot = current_medicine_snapshot(conn, p)
        if 'medicine_snapshot_sha256' in data:
            if current_snapshot is None or medicine_snapshot.digest(current_snapshot) != data['medicine_snapshot_sha256']: return False
        elif current_snapshot is not None and 'confirmed_at' in data:
            return False  # a real confirmation (always timestamped) made before any interview existed was never reviewed against these interview medicines
        meds = data['meds']
        if not isinstance(meds, list) or any(not isinstance(row, list) or len(row) != 2 or any(not isinstance(value, str) for value in row) for row in meds): return False
        current = relevant_usage(interview_usage(conn, p), meds)
        previous = data.get('interview_usage')
        if (previous is not None and previous != current) or (previous is None and any(item['status'] == 'not_using' for item in current)): return False
        return not any(item['status'] == 'not_using' for item in current) or valid_alternatives(meds, current, data.get('alternatives'))
    except (ValueError, KeyError, TypeError): return False
