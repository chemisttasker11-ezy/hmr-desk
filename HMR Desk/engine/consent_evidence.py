"""Consent evidence for the PPA claim helper (kept out of api.py)."""
import datetime as dt

import records


def consent_evidence(conn, p):
    """Where the recorded consent comes from: 'app_signed', 'manual_attested' or ''.
    Both need interview.json consent.signed true (a pharmacist-ticked or app-set flag).
    'app_signed': the exact file consent_sign writes ('PPA Consent - <name> signed.pdf') exists in
    the patient's folder as a readable PDF with an image on its signature page.
    'manual_attested': no such app artifact (for example consent taken on paper), but the
    pharmacist ticked 'Consent form signed' and entered a valid consent date. This is the
    pharmacist's own attestation, not verified evidence. An unrelated file, a stub or a
    renamed patient's old file never counts as the app artifact."""
    try:
        data = records.get_json(conn, p['id'], 'interview.json') or {}
        consent = data.get('consent', {})
        if consent.get('signed') is not True: return ''
        try:
            import consent_sign, fitz
            path = consent_sign.unsigned_path(p)
            path = path.with_name(path.stem + ' signed.pdf')
            if path.is_file():
                with fitz.open(path) as pdf:
                    if len(pdf) >= 2 and pdf[1].get_images(): return 'app_signed'
        except Exception:
            pass
        try:
            dt.datetime.strptime(str(consent.get('date') or ''), '%Y-%m-%d')
        except ValueError:
            return ''
        return 'manual_attested'
    except Exception:
        return ''
