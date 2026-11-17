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


def generated_followup_texts(name):
    return {"", NEUTRAL_FOLLOWUP, required_followup(name), not_required_followup(name)}


def apply_followup_decision(data):
    """Only 'not_required' offers a PROPOSED sentence, and only into blank or unedited generated text, still review-gated.
    'required' never generates timing or a repeat-HMR statement: the pharmacist must enter and review the plan.
    Authored text is never overwritten."""
    decision, name = data.get("followup_decision", ""), (data.get("name") or "").strip()
    if not name or data.get("followup", "").strip() not in generated_followup_texts(name): return data
    if decision == "not_required": return {**data, "followup": not_required_followup(name)}
    if decision == "required": return {**data, "followup": NEUTRAL_FOLLOWUP}  # drops a proposed or stock sentence; no timing is implied
    return data


def unresolved(data):
    keys = [key for key in ("reason", "intro")
            if key in data.get("needs_review", []) and not data.get(key, "").strip()]
    if "followup_decision" not in data: return keys  # legacy spec: authored text stands
    decision, name = data["followup_decision"], (data.get("name") or "").strip()
    text = data.get("followup", "").strip()
    if decision == "": keys.append("followup_decision")
    elif decision == "required" and (not text or text in generated_followup_texts(name)):
        keys.append("followup_plan")  # the pharmacist must enter the actual plan and timing
    elif decision == "not_required" and not data.get("followup_text_reviewed", False):
        keys.append("followup_review")  # proposed wording is not approved until the pharmacist confirms it
    return keys
