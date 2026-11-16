"""Deterministic medicine reconciliation checks for the manual HMR pathway.

This module never makes treatment decisions. It surfaces discrepancies for
pharmacist review without replacing the patient's recorded medicine list.
"""
import hashlib
import json
import re

VERSION = 1
VALID_STATES = {"", "unknown", "taking", "not_using"}


def normalise(name):
    if not isinstance(name, str):
        return ""
    return re.sub(r"\s+", " ", name).strip().casefold()


def _flag(flags, code, medicine_id, message, severity="review"):
    flags.append({"code": code, "medicine_id": medicine_id,
                  "message": message, "severity": severity})


def audit(record):
    """Return a stable, source-indexed review checklist, never inferred doses."""
    if not isinstance(record, dict):
        raise ValueError("invalid interview")
    details = record.get("details") or {}
    flags = []
    groups = {}
    entries = []
    for section, width in (("meds", 5), ("other_meds", 4)):
        rows = record.get(section) or []
        meta = details.get(section) or []
        if not isinstance(rows, list) or not isinstance(meta, list):
            raise ValueError("invalid medicine rows")
        for i, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != width:
                raise ValueError("invalid medicine row")
            if not all(isinstance(x, str) for x in row):
                raise ValueError("invalid medicine values")
            m = meta[i] if i < len(meta) else {}
            if not isinstance(m, dict):
                raise ValueError("invalid medicine metadata")
            status = m.get("use_status", "")
            if status not in VALID_STATES:
                raise ValueError("invalid use status")
            key = section + ":" + str(i)
            name = row[0].strip()
            if not name:
                if any(x.strip() for x in row[1:]):
                    _flag(flags, "missing_medicine_name", key,
                          "Medicine row contains information but no name")
                continue
            groups.setdefault(normalise(name), []).append(key)
            entries.append({"id": key, "medicine": name, "source": section,
                            "status": status or "unknown"})
            if status in ("", "unknown"):
                _flag(flags, "use_unconfirmed", key,
                      "Confirm whether the patient is actually taking this medicine")
            if section == "meds":
                referral, actual = row[1].strip(), row[2].strip()
                if status == "taking" and not actual:
                    _flag(flags, "actual_directions_missing", key,
                          "Actual directions not recorded for a medicine marked taking")
                if status == "taking" and referral and actual and normalise(referral) != normalise(actual):
                    _flag(flags, "directions_differ", key,
                          "Actual directions differ from referral; verify and document reason")
                if status == "not_using" and not (m.get("use_reason") or m.get("use_details")):
                    _flag(flags, "cessation_reason_missing", key,
                          "Medicine marked not using without a recorded reason")
            elif status == "taking" and not row[1].strip():
                _flag(flags, "actual_directions_missing", key,
                      "Directions not recorded for an additional medicine")
    for name, ids in groups.items():
        if len(ids) > 1:
            for key in ids:
                _flag(flags, "possible_duplicate", key,
                      "Same medicine name appears in multiple rows; check brand, strength and formulation")
    flags.sort(key=lambda x: (x["medicine_id"], x["code"]))
    return {"version": VERSION, "medicines": entries, "flags": flags,
            "review_required": bool(flags), "flag_count": len(flags)}


def digest(record):
    """Hash only reconciliation inputs; no identifiers in the audit artifact."""
    subset = {"meds": record.get("meds", []),
              "other_meds": record.get("other_meds", []),
              "details": {k: (record.get("details") or {}).get(k, [])
                          for k in ("meds", "other_meds")}}
    return hashlib.sha256(json.dumps(subset, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def review_status(record, saved=None):
    """Only a pharmacist acknowledgement for the current digest is valid."""
    current = digest(record)
    saved = saved if isinstance(saved, dict) else {}
    reviewed = saved.get('source_hash') == current and bool(saved.get('reviewed_at'))
    return {'source_hash': current, 'reviewed': reviewed,
            'stale': bool(saved.get('reviewed_at')) and not reviewed,
            'reviewed_at': saved.get('reviewed_at') if reviewed else None,
            'reviewed_by': saved.get('reviewed_by') if reviewed else None}


def acknowledge(record, source_hash, reviewed_by):
    """Persist an explicit, version-bound review; never mark unknown medicines taking."""
    import datetime
    if source_hash != digest(record):
        raise ValueError('Medicines changed; reload the reconciliation before acknowledging')
    if not isinstance(reviewed_by, str) or not reviewed_by.strip() or len(reviewed_by) > 120:
        raise ValueError('Pharmacist identity required for acknowledgement')
    return {'version': VERSION, 'source_hash': source_hash,
            'reviewed_by': reviewed_by.strip(),
            'reviewed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
