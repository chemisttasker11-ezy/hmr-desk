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


NEUTRAL_FOLLOWUP = "Please contact me if you would like to discuss these findings."
# Existing stock sentence carried over unchanged from the repo (owner approval not re-verified in this change). Used only after the pharmacist records that a follow-up is required.
def required_followup(name):
    return ("If you have no objections, I will see " + name + " again in a few months to follow up "
            "on any ongoing issues. A repeat HMR is recommended if clinical condition changes in 12 months' time.")
# PROPOSED, not owner-approved: used only when the pharmacist records that no follow-up is required.
def not_required_followup(name):
    return ("No follow-up interview is planned at this time. Please contact me if you would like to discuss these findings "
            "or if " + name + "'s clinical condition changes.")
DECISIONS = ("", "required", "not_required")


def initial_text(patient_name, gp_name):
    # Identity is inserted locally and never sent to a clinical agent.
    data = dict(DEFAULTS)
    data["followup_decision"] = ""  # the pharmacist decides; no follow-up claim is generated before that
    name = (patient_name or '').strip()
    if name:
        data["thanks"] = "Thank you for referring " + name + " for a Home Medicines Review."
    return data


def apply_followup_decision(data):
    """Fill the follow-up paragraph from the recorded decision, only when it is blank or an unedited generated sentence.
    Authored text is never overwritten."""
    decision, name = data.get("followup_decision", ""), (data.get("name") or "").strip()
    if decision not in ("required", "not_required") or not name: return data
    text = data.get("followup", "").strip()
    generated = {"", NEUTRAL_FOLLOWUP, required_followup(name), not_required_followup(name)}
    if text in generated:
        data = {**data, "followup": required_followup(name) if decision == "required" else not_required_followup(name)}
    return data


def unresolved(data):
    keys = [key for key in ("reason", "intro")
            if key in data.get("needs_review", []) and not data.get(key, "").strip()]
    if "followup" in data.get("needs_review", []) and data.get("followup_decision", None) == "":
        keys.append("followup_decision")
    return keys
