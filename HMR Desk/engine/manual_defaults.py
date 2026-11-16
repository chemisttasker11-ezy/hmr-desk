"""Built-in manual report prose defaults, independent of external AI skills.

Clinical content is derived from the interview; these are administrative
sentences only, never fabricated patient observations or recommendations.
"""
DEFAULTS = {
    "thanks": "Thank you for referring this patient for a Home Medicines Review.",
    "reason": "",
    "intro": "",
    "followup": "Please contact me if you would like to discuss these findings.",
}


def initial_text(patient_name, gp_name):
    # Identity is inserted locally and never sent to a clinical agent.
    data = dict(DEFAULTS)
    name = (patient_name or '').strip()
    if name:
        # The owner's standard administrative sentences name the patient.
        data["thanks"] = "Thank you for referring " + name + " for a Home Medicines Review."
        data["followup"] = ("If you have no objections, I will see " + name + " again in a few months to follow up "
                            "on any ongoing issues. A repeat HMR is recommended if clinical condition changes in 12 months' time.")
    return data


def unresolved(data):
    return [key for key in ("reason", "intro")
            if key in data.get("needs_review", []) and not data.get(key, "").strip()]
