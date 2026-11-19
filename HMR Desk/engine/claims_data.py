"""Rows for the PPA claim helper, built from local patient data only. No network, no portal access."""
import re

import steps


def claim_list(conn, claims_helper, record, report_data, consent_evidence):
    """Sent, real, unarchived patients as claim rows. The collaborators are passed in so the facade keeps
    one place to replace them (tests set api.claims_helper and api.record)."""
    if claims_helper is None or record is None: return []  # PPA integration unavailable
    result = []
    for p in conn.execute("SELECT * FROM patients WHERE state='sent' AND is_test=0 AND archived_at IS NULL ORDER BY name"):
        spec = report_data(conn, p) or {}
        dates = {name: steps.event_date(conn, p, name) or '' for name in ('visited', 'report_sent')}
        given, family = claims_helper.split_name(p['name']); gp_given, gp_family = claims_helper.split_name(p['gp'])
        suburb = p['suburb'] or ''; match = re.match(r'(\d{4})\s+(.*)', suburb)
        provider = re.search(r'(?im)^\s*Provider No:\s*(.+)$', spec.get('doctor', ''))
        outcomes, other = record.outcomes(spec) if spec else ([], '')
        result.append({'given': given, 'family': family, 'dob': claims_helper.iso(p['dob']),
            'medicare': re.sub(r'\D', '', p['medicare'] or '') + re.sub(r'\D', '', p['irn'] or ''),
            'interview': claims_helper.iso(dates.get('visited')), 'reportSent': claims_helper.iso(dates.get('report_sent')),
            'referral': claims_helper.iso(p['referral_date']), 'gpProvider': provider.group(1).strip() if provider else '',
            'gpGiven': gp_given, 'gpFamily': gp_family, 'suburb': match.group(2) if match else suburb,
            'postcode': p['postcode'] or (match.group(1) if match else ''),
            'reasons': record.reasons(spec) if spec.get('reason') else [], 'consentHeld': consent_evidence(conn, p) != '', 'consentEvidence': consent_evidence(conn, p), 'reasonOther': '', 'outcomes': outcomes, 'outcomeOther': other})
    return result
