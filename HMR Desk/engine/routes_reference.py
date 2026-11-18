"""Reference and suggestion routes: the local reference PDF, library search, reference matches, candidate checks, suggestions.

Moved verbatim from api.handle. handle() returns (status, payload) for a route it owns and None otherwise.
ValueError and TypeError still propagate to api.handle (same 400 response).
"""
import re


def handle(conn, method, path, query, body):
    if path in ('/api/reference/local', '/api/reference/search', '/api/reference/open'):
        import reference_library
        try:
            if path == '/api/reference/local' and method == 'POST': return 200, reference_library.register(body)
            if path == '/api/reference/local' and method == 'GET': return 200, reference_library.public(reference_library.current())
            if path == '/api/reference/search' and method == 'GET':
                q = (query.get('q') or [''])[0]
                try:
                    return 200, reference_library.search(q)
                except reference_library.ReferenceUnavailable:
                    # Packaged tier: serve the reviewed packaged tables, explicitly
                    # labelled as unverified extraction - never as the user's own PDF.
                    import brainstorm_tables_lookup
                    try:
                        return 200, brainstorm_tables_lookup.search(q)
                    except brainstorm_tables_lookup.TablesUnavailable as tables_exc:
                        if 'too long' in str(tables_exc):
                            raise reference_library.ReferenceUnavailable(str(tables_exc)) from None
                        # No usable PDF and no intact packaged tables: the same
                        # user-facing state as before packaged tables existed.
                        raise reference_library.ReferenceUnavailable('Local reference unavailable; choose the original PDF') from None
            if path == '/api/reference/open' and method == 'POST' and isinstance(body,dict) and set(body)=={'pdf_sha256','page'}:
                return 200, reference_library.open_source(body['pdf_sha256'],body['page'])
        except reference_library.ReferenceUnavailable as exc: return 409, {'error':str(exc)}
        return 400, {'error':'Invalid local reference request'}
    if method == 'GET' and path == '/api/library':
        import report
        q = query.get('q', '')
        return 200, {'results': report.library(q[0] if isinstance(q, list) and q else q)}
    match = re.fullmatch(r'/api/patients/(\d+)/reference-matches', path)
    if method == 'GET' and match:
        import reference_matches, reference_library
        patient=conn.execute('SELECT * FROM patients WHERE id=?',(int(match[1]),)).fetchone()
        if not patient: return 404, {'error':'patient not found'}
        try: return 200, reference_matches.for_patient(conn,patient)
        except reference_library.ReferenceUnavailable as exc:
            return 409, {'error':str(exc),'matches':[], 'review_status':'reference_unavailable'}
    match = re.fullmatch(r'/api/patients/(\d+)/candidate-checks', path)
    if method == 'GET' and match:
        import candidate_checks
        patient=conn.execute('SELECT * FROM patients WHERE id=?',(int(match[1]),)).fetchone()
        if not patient: return 404, {'error':'patient not found'}
        try: return 200, candidate_checks.for_patient(conn,patient)
        except ValueError as exc:
            return 409, {'error':str(exc),'observations':[], 'review_status':'checks_unavailable'}
    match = re.fullmatch(r'/api/patients/(\d+)/suggestions(?:/context)?', path)
    if method == 'GET' and match:
        import suggest
        p = conn.execute('SELECT * FROM patients WHERE id=?', (int(match[1]),)).fetchone()
        if not p: return 404, {'error': 'patient not found'}
        context = suggest.context_for(conn, p)
        if path.endswith('/context'):
            return 200, {'context_snapshot_sha256': context['context_snapshot_sha256']}
        try:
            suggestions = suggest.suggest(context)
        except suggest.LibraryUnavailable:
            return 503, {'error': 'Offline suggestions unavailable: the reviewed reference library is not installed or cannot be read. Current interview evidence is retained; no suggestions were generated.'}
        return 200, {'suggestions': suggestions, 'context_gaps': suggest.context_gaps(context),
                     'context_snapshot_sha256': context['context_snapshot_sha256']}
    return None
