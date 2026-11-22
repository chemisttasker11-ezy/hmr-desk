"""Synthetic stand-in for the PPA claim helper, for the legacy script tests only.

`PPA Claim Helper/make-claims.py` and `record_report.py` are not in the repository. These doubles give the claim-row
code just enough to run on synthetic names and dates. They prove the engine's row assembly, NOT the real helper's
name splitting, date or outcome parsing, which stays unverified until the real helper is available to a test.
"""
import types


def split_name(name):
    parts = (name or '').split()
    return (' '.join(parts[:-1]), parts[-1]) if len(parts) > 1 else (name or '', '')


def iso(value):
    return value or ''


claims_helper = types.SimpleNamespace(split_name=split_name, iso=iso)
record = types.SimpleNamespace(outcomes=lambda spec: ([], ''), reasons=lambda spec: [])
