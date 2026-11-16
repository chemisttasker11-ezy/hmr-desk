"""Privacy boundary for clinical HMR agent requests.

Only allowlisted structured clinical data may cross this boundary. Narrative
notes, source documents, patient/GP identity and patient folder paths stay local.
A negative identifier screen is defense-in-depth, not proof of anonymisation.
"""
import datetime as dt
import hashlib
import json
import re

SCHEMA = "hmr-clinical-v1"
SENSITIVE = re.compile(
    r"(?i)(?:\b(?:medicare|\bihi\b|\birn\b|\bdob\b|date of birth|"
    r"\bmrn\b|patient name|\bgp name|\bprovider number|\bphone\b|"
    r"\baddress\b|\bemail\b|\bsuburb\b)\s*[:#=]|"
    r"\b\d{4}\s?\d{5}\s?\d{1}\b|"
    r"\b8003\s?\d{4}\s?\d{4}\s?\d{4}\b|"
    r"\b(?:04\d{2}[ -]?\d{3}[ -]?\d{3})\b|"
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|"
    r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b)"
)
SAFE_LABEL = re.compile(r"^[\w ,.'()/+%:-]{1,160}$", re.UNICODE)
SAFE_VALUE = re.compile(r"^[\w ,.'()/+%:;=-]{1,180}$", re.UNICODE)


class PrivacyBlocked(ValueError):
    pass


def clean(value, *, label=False):
    if not isinstance(value, str):
        raise PrivacyBlocked("Clinical value must be text")
    value = value.strip()
    if not value:
        return ""
    if SENSITIVE.search(value) or not (SAFE_LABEL if label else SAFE_VALUE).fullmatch(value):
        raise PrivacyBlocked("Clinical value contains unsupported or potentially identifying text")
    return value


def age_years(header, *, today=None):
    # Use age from the local validated interview header, never transmit DOB.
    age = str(header.get("age", "")).strip()
    if age.isdigit() and 0 <= int(age) <= 120:
        return int(age)
    dob = str(header.get("dob", "")).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            born = dt.datetime.strptime(dob[:10], fmt).date()
            now = today or dt.date.today()
            age = now.year - born.year - ((now.month, now.day) < (born.month, born.day))
            if 0 <= age <= 120:
                return age
        except ValueError:
            pass
    return None


def project(record, *, sex=""):
    """Create a new clinical-only object; never copy the source record."""
    if not isinstance(record, dict):
        raise PrivacyBlocked("Invalid clinical interview")
    header = record.get("header") or {}
    if not isinstance(header, dict):
        raise PrivacyBlocked("Invalid interview header")
    gender = str(sex or "").strip().lower()
    if gender not in ("male", "female", "other", "unknown", ""):
        gender = "unknown"
    medicines = []
    rows = record.get("meds") or []
    meta = (record.get("details") or {}).get("meds") or []
    if len(rows) > 80 or not isinstance(rows, list):
        raise PrivacyBlocked("Invalid medicines")
    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 5:
            raise PrivacyBlocked("Invalid medicine row")
        m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
        status = m.get("use_status", "")
        if status not in ("", "taking", "not_using", "unknown"):
            raise PrivacyBlocked("Invalid medicine status")
        medicines.append({
            "id": "med_" + str(i + 1),
            "medicine": clean(row[0], label=True),
            "referral_directions": clean(row[1]),
            "actual_directions": clean(row[2]),
            "status": status or "unconfirmed",
            "prn_frequency": clean(m.get("prn_use", "")),
        })
    other = []
    for i, row in enumerate(record.get("other_meds") or []):
        if not isinstance(row, list) or len(row) != 4:
            raise PrivacyBlocked("Invalid additional medicine row")
        other.append({"id": "otc_" + str(i + 1), "medicine": clean(row[0], label=True),
                      "directions": clean(row[1])})
    observations = []
    for i, row in enumerate(record.get("obs") or []):
        if not isinstance(row, list) or len(row) != 3:
            raise PrivacyBlocked("Invalid observation row")
        # Free-form observation notes can contain patient identifiers: omit.
        # A later structured pathology schema can safely provide values and units.
        observations.append({"id": "obs_" + str(i + 1), "type": clean(row[0], label=True)})
    details = record.get("details") or {}
    symptoms = {}
    for key in ("sx_falls", "sx_dizziness", "sx_drowsiness", "sx_pain",
                "sx_sleep", "sx_bowel", "sx_bladder", "sx_mood", "sx_memory",
                "sx_appetite", "missed_doses", "swallowing", "device_technique"):
        value = details.get(key, "")
        if value in ("", "yes", "no", "not_asked", "none", "sometimes",
                     "often", "ok", "issues", "not_checked"):
            if value:
                symptoms[key] = value
        else:
            raise PrivacyBlocked("Invalid structured clinical flag")
    result = {
        "schema_version": SCHEMA,
        "demographics": {"age_years": age_years(header), "sex": gender},
        "medicines": medicines,
        "other_medicines": other,
        "observation_types": observations,
        "structured_flags": symptoms,
        "omitted": ["free_text_notes", "pathology_values_pending_structured_review"],
    }
    validate_payload(result)
    return result


def validate_payload(payload):
    if set(payload) != {"schema_version", "demographics", "medicines", "other_medicines",
                        "observation_types", "structured_flags", "omitted"}:
        raise PrivacyBlocked("Unexpected clinical payload fields")
    if payload["schema_version"] != SCHEMA:
        raise PrivacyBlocked("Invalid clinical schema version")
    encoded = json.dumps(payload, ensure_ascii=False)
    if SENSITIVE.search(encoded):
        raise PrivacyBlocked("Possible identifier in clinical payload")
    if len(encoded.encode("utf-8")) > 60000:
        raise PrivacyBlocked("Clinical payload exceeds size limit")
    return payload


def fingerprint(payload):
    validate_payload(payload)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_findings(response, payload):
    """Reject extra keys and invented source references before local merge."""
    if not isinstance(response, dict) or set(response) != {"findings"}:
        raise PrivacyBlocked("Invalid agent findings envelope")
    findings = response["findings"]
    if not isinstance(findings, list) or len(findings) > 15:
        raise PrivacyBlocked("Invalid findings count")
    ids = {m["id"] for m in payload["medicines"] + payload["other_medicines"]}
    ids.update(x["id"] for x in payload["observation_types"])
    result = []
    for item in findings:
        if not isinstance(item, dict) or set(item) != {"title", "recommendation", "rationale", "evidence_ids"}:
            raise PrivacyBlocked("Invalid finding structure")
        refs = item["evidence_ids"]
        if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or x not in ids for x in refs):
            raise PrivacyBlocked("Unknown clinical evidence reference")
        result.append({"title": clean(item["title"]), "rec": clean(item["recommendation"]),
                       "rationale": clean(item["rationale"])})
    return result
