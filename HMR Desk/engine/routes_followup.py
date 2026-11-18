"""Patient timeline and follow-up record routes.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import db
import records
from patient_actions import action, date


def handle(conn, method, path, query, body):
    match = re.fullmatch(r'/api/patients/(\d+)/(timeline|followup/([12])(/export)?)', path)
    if match:
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        if match[2] == 'timeline' and method == 'GET':
            import timeline
            return 200, timeline.build(conn, p)
        if match[3]:
            import followup
            number = int(match[3])
            if method == 'GET' and not match[4]:
                record = followup.load(conn, p, number)
                return 200, {**record, 'review_issues': followup.review_issues(record)}
            if method == 'POST' and match[4]: return 200, {'file': followup.export(conn, p, number)}
            if method == 'POST':
                followup.validate(body)
                if body['date']: date(body['date'])
                before = records.get_json(conn, p['id'], f'followup{number}.json')
                result = followup.save(conn, p, number, body)
                claimed = conn.execute("SELECT claimed FROM visits WHERE patient_id=? AND kind=? AND claimed IS NOT NULL LIMIT 1", (p['id'], 'followup' + str(number))).fetchone()
                if claimed and before is not None and followup.normalize(before) != followup.normalize(body):
                    db.log(conn, p['id'], 'followup_record_changed_after_claim', {'kind': 'followup' + str(number)}, 'app')
                    result = {**result, 'changed_after_claim': True, 'review_issues': followup.review_issues(result)}
                if body['date'] and not conn.execute("SELECT 1 FROM visits WHERE patient_id=? AND kind=? AND visit_date IS NOT NULL", (p['id'], 'followup' + str(number))).fetchone():
                    action(conn, p, {'action': 'followup_done', 'kind': 'followup' + str(number), 'date': body['date']})
                return 200, result
    return None
