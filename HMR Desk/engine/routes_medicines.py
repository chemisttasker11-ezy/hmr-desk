"""Confirmed-medicines routes: the proposed list with its interview snapshot, and confirming it.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import db
import medicine_review
import medicine_snapshot
import records


def handle(conn, method, path, query, body):
    match = re.fullmatch(r'/api/patients/(\d+)/meds', path)
    if match:
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if method == 'GET':
            result = records.get_json(conn, p['id'], 'confirmed_meds.json') or medicine_review.proposal(conn, p)
            usage = medicine_review.interview_usage(conn, p)
            result['interview_usage'] = usage
            snapshot = medicine_review.current_medicine_snapshot(conn, p)
            current_digest = medicine_snapshot.digest(snapshot) if snapshot is not None else 'missing'
            result['medicine_snapshot_changed'] = (('medicine_snapshot_sha256' in result and result['medicine_snapshot_sha256'] != current_digest)
                                                   or ('medicine_snapshot_sha256' not in result and 'confirmed_at' in result and snapshot is not None))
            result['medicine_snapshot'] = snapshot
            import interaction_scope
            result['interaction_scope'] = interaction_scope.for_patient(conn, p)
            result['interaction_scope']['statement'] = interaction_scope.lines(result['interaction_scope']) if interaction_scope.needs_statement(result['interaction_scope']) else []
            if result['medicine_snapshot_changed'] and snapshot is not None:
                # The saved list froze the allergies at confirmation time. Show what the interview says now, never the old list, and keep the old one visible.
                result['allergies_confirmed_earlier'] = result.get('allergies', [])
                result['allergies'] = [x.strip() for x in snapshot['allergies'].splitlines() if x.strip()]
            result['medicine_snapshot_sha256'] = medicine_snapshot.digest(snapshot) if snapshot is not None else 'missing'
            return 200, result
        if method == 'POST':
            import interview
            with interview.record_lock(p):
                if not isinstance(body, dict) or set(body) - {'medicine_snapshot_sha256'} not in ({'meds', 'allergies'}, {'meds', 'allergies', 'interview_usage'}, {'meds', 'allergies', 'interview_usage', 'alternatives'}): raise ValueError('invalid medicine list')
                current_snapshot = medicine_review.current_medicine_snapshot(conn, p)
                current_digest = medicine_snapshot.digest(current_snapshot) if current_snapshot is not None else 'missing'
                if 'medicine_snapshot_sha256' in body and body['medicine_snapshot_sha256'] != current_digest: raise ValueError('Interview medicines or allergies changed; reload and review before confirming')
                if current_snapshot is not None and any(item['item_id'] for item in current_snapshot['items']) and 'medicine_snapshot_sha256' not in body: raise ValueError('Reload and review the current medicine snapshot before confirming')
                meds, allergies = body['meds'], body['allergies']
                if not isinstance(meds, list) or len(meds) > 60 or any(not isinstance(row, list) or len(row) != 2 or any(not isinstance(x, str) for x in row) or not row[0].strip() for row in meds): raise ValueError('invalid medicines')
                usage = medicine_review.interview_usage(conn, p)
                relevant = medicine_review.relevant_usage(usage, meds)
                snapshot = body.get('interview_usage')
                if relevant and snapshot is None: raise ValueError('Review and reconcile interview medicine use before confirming')
                if snapshot is not None and (not isinstance(snapshot, list) or any(not isinstance(item, dict) or not isinstance(item.get('name'), str) for item in snapshot) or medicine_review.relevant_usage(snapshot, meds) != relevant): raise ValueError('Interview medicine use changed; review before confirming')
                alternatives = body.get('alternatives', [None] * len(meds))
                if not medicine_review.valid_alternatives(meds, relevant, alternatives):
                    if medicine_review.same_name_as_stopped(meds, relevant): raise ValueError('A listed medicine has the same name as one recorded as not using in the interview. Remove it from the list, or correct its use in the interview.')
                    raise ValueError('Select the medicine actually taking for each stopped overlap')
                if not isinstance(allergies, list) or len(allergies) > 60 or any(not isinstance(x, str) for x in allergies): raise ValueError('invalid allergies')
                data = {'meds': meds, 'allergies': allergies, 'confirmed_at': db.now(), 'interview_usage': relevant, 'alternatives': alternatives}
                if current_snapshot is not None:
                    data.update(medicine_snapshot=current_snapshot, medicine_snapshot_sha256=current_digest)
                records.put_json(conn, p['id'], 'confirmed_meds.json', data)
                db.log(conn, p['id'], 'meds_confirmed', {}, 'api'); conn.commit()
                return 200, data
    return None
