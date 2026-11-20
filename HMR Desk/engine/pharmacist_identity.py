"""Reviewing-pharmacist identity for exported reports.

The values are the Settings entries the interview header already shows (interview.load fills the header from
Settings on every read). Nothing is looked up or invented: no email, no registration number. The credential
has a pre-filled default, so it is printed only when the pharmacist ticked the Settings confirmation for it.
"""
import hashlib
import json

import settings

CREDENTIAL_NOT_CONFIRMED = ('Credential not printed: not confirmed. Tick the credential confirmation in Settings, '
                            'then rebuild the report.')


def resolve(conn):
    name = (settings.get(conn, 'pharmacist_name') or '').strip()
    phone = (settings.get(conn, 'pharmacist_phone') or '').strip()
    credential = (settings.get(conn, 'pharmacist_credential') or '').strip()
    confirmed = bool(settings.get(conn, 'pharmacist_credential_confirmed')) and bool(credential)
    lines = ([name] if name else []) + ([credential] if name and confirmed else []) + (['Phone: ' + phone] if name and phone else [])
    note = ''
    if not name:
        note = 'Pharmacist name is not set in Settings; the report shows it as not supplied.'
    elif not confirmed:
        note = CREDENTIAL_NOT_CONFIRMED
    return {'name': name, 'phone': phone, 'credential': credential if confirmed else '', 'lines': lines,
            'text': '\n'.join(lines), 'note': note}


def digest(identity):
    """Hash of what the report prints, so a later Settings change shows the built report as outdated."""
    return hashlib.sha256(json.dumps(identity['lines']).encode('utf-8')).hexdigest()
