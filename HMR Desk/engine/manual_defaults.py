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
    return dict(DEFAULTS)


def unresolved(data):
    return [key for key in ("reason", "intro")
            if key in data.get("needs_review", []) and not data.get(key, "").strip()]
