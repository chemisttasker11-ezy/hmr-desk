"""Offline claim preparation check. Local data only: no network, no PPA client, no submission.

It reports which claim rows are missing information the pharmacist must supply before any
claim could be considered. It does not know the current PPA schema and does not say a row is
accepted, valid or ready to submit. Connection status is always 'not_connected'."""

# claim_data field -> plain wording shown to the pharmacist
REQUIRED = (
    ('given', 'given name'), ('family', 'family name'), ('dob', 'date of birth'),
    ('medicare', 'Medicare number'), ('interview', 'interview date'),
    ('reportSent', 'report sent date'), ('referral', 'referral date'),
    ('gpProvider', 'GP provider number'), ('outcomes', 'outcomes'),
)


def _blank(value):
    return value in ('', None) or value == [] or (isinstance(value, str) and not value.strip())


def missing(row):
    """Plain-English labels of required fields that are empty, plus consent when not held."""
    labels = [label for field, label in REQUIRED if _blank(row.get(field))]
    if not row.get('consentHeld'): labels.append('consent evidence')
    return labels


def prepare(rows):
    """One entry per row: name, the missing items and a status that never implies submission."""
    items = []
    for row in rows or []:
        gaps = missing(row)
        items.append({'name': f"{row.get('given', '')} {row.get('family', '')}".strip(),
                      'missing': gaps, 'status': 'needs_information' if gaps else 'details_complete_locally'})
    return {'connection': 'not_connected', 'submission': 'not_available',
            'note': 'Local completeness check only. Nothing has been sent to PPA and no claim has been made.',
            'items': items}
