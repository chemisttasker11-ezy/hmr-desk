"""Message routes: the board, drafting for a patient, approve, discard and resolve a reply.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re

import inbox
import messaging


def handle(conn, method, path, query, body):
    if path == '/api/messages/board' and method == 'GET': return 200, messaging.board(conn)
    if path == '/api/messages/check' and method == 'POST': return 200, messaging.check_now(conn)
    match = re.fullmatch(r'/api/patients/(\d+)/messages', path)
    if match and method == 'POST':
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not patient: return 404, {'error': 'patient not found'}
        return 200, messaging.draft(conn, patient, body)
    match = re.fullmatch(r'/api/messages/([^/]+)/(approve|discard|resolve)', path)
    if match and method == 'POST':
        row = conn.execute('SELECT * FROM messages WHERE id=?', (match[1],)).fetchone()
        if not row: return 404, {'error': 'message not found'}
        if match[2] == 'resolve': return 200, inbox.resolve(conn, row, body)
        return 200, messaging.approve(conn, row, body) if match[2] == 'approve' else messaging.discard(conn, row)
    return None
