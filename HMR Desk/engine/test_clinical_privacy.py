"""Synthetic clinical privacy contract tests; no patient files or external agents."""
import datetime as dt
import json
import pytest

import clinical_privacy as cp


def record():
    return {
        "header": {
            "name": "Private Example", "dob": "1950-05-01", "age": "",
            "medicare": "1234567890", "ihi": "8003600000000000",
            "address": "7 Example Street", "phone": "0412345678",
            "gp": "Dr Private GP",
        },
        "meds": [["apixaban", "5 mg twice daily", "5 mg twice daily", "", ""]],
        "other_meds": [["paracetamol", "500 mg PRN", "", ""]],
        "obs": [["Blood pressure", "120/80", "118/72"]],
        "conditions": "Atrial fibrillation",
        "notes": "Patient lives at 7 Example Street, contact 0412345678",
        "pathology": [["Creatinine", "119", "2026-11-01", "umol/L"]],
        "details": {"meds": [{"use_status": "taking", "prn_use": ""}],
                    "sx_falls": "no", "missed_doses": "sometimes"},
    }


def test_projection_contains_only_allowlisted_clinical_fields():
    result = cp.project(record(), sex="female")
    assert result["demographics"]["age_years"] == 76
    assert result["demographics"]["sex"] == "female"
    assert result["medicines"][0]["medicine"] == "apixaban"
    assert result["structured_flags"]["missed_doses"] == "sometimes"
    raw = json.dumps(result)
    for secret in ("Private", "1950-05-01", "1234567890", "8003600000000000",
                   "0412345678", "Example Street", "Dr Private GP", "2026-11-01"):
        assert secret not in raw


@pytest.mark.parametrize("field,secret", [
    (0, "Medicare: 1234567890"), (0, "IHI: 8003600000000000"),
    (0, "0412345678"), (0, "alice@example.com"), (0, "2026-11-01"),
    (0, "7 Example Street\nGP Dr Example"),
])
def test_identity_in_medicine_is_blocked(field, secret):
    source = record()
    source["meds"][0][field] = secret
    with pytest.raises(cp.PrivacyBlocked):
        cp.project(source, sex="female")


def test_free_text_is_never_copied():
    source = record()
    source["notes"] = "Sensitive name, address and carer details"
    source["conditions"] = "Rare condition involving a named family member"
    assert "Sensitive name" not in json.dumps(cp.project(source))
    assert "named family member" not in json.dumps(cp.project(source))


def test_output_evidence_must_exist():
    payload = cp.project(record())
    good = {"findings": [{"title": "Review anticoagulation",
                          "recommendation": "Confirm the indication and dose",
                          "rationale": "Current therapy merits review",
                          "evidence_ids": ["med_1"]}]}
    assert cp.validate_findings(good, payload)[0]["title"] == "Review anticoagulation"
    bad = json.loads(json.dumps(good))
    bad["findings"][0]["evidence_ids"] = ["made_up"]
    with pytest.raises(cp.PrivacyBlocked):
        cp.validate_findings(bad, payload)
    bad = json.loads(json.dumps(good))
    bad["findings"][0]["patient_name"] = "Private Example"
    with pytest.raises(cp.PrivacyBlocked):
        cp.validate_findings(bad, payload)


def test_payload_schema_rejects_extra_keys():
    payload = cp.project(record())
    payload["patient_name"] = "Private Example"
    with pytest.raises(cp.PrivacyBlocked):
        cp.validate_payload(payload)



def test_numeric_pathology_value_reaches_payload_and_text_is_withheld():
    rec = record()
    rec["pathology"] = [["Creatinine", "119", "2026-11-01", "umol/L"],
                        ["eGFR", "45.5", "2026-11-01", "mL/min"],
                        ["Potassium", "-1.2", "", ""],
                        ["Comment", "see Dr Private GP", "", ""],
                        ["Sodium", "1e5", "", ""]]
    result = cp.project(rec, sex="female")
    values = {row["test"]: row["value"] for row in result["pathology"]}
    assert values == {"Creatinine": "119", "eGFR": "45.5", "Potassium": "-1.2"}
    raw = json.dumps(result)
    assert "2026-11-01" not in raw and "Private" not in raw
