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
POLICY_VERSION = 2  # specs created from this version carry followup_decision; a missing key is then invalid, not "legacy"
import hashlib, re
_STOCK = re.compile(r"^If you have no objections, I will see .+ again in a few months to follow up on any ongoing issues\. A repeat HMR is recommended if clinical condition changes in 12 months' time\.$")
_PROPOSED = re.compile(r"^No follow-up interview is planned at this time\. Please contact me if you would like to discuss these findings or if .+'s clinical condition changes\.$")


def text_sha(text):
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def looks_generated(text):
    """Recognisable generated sentence for any patient name: the stock paragraph or the proposed not-required one."""
    text = (text or "").strip()
    return bool(_STOCK.match(text) or _PROPOSED.match(text))


def review_valid(data):
    """A review is bound to the exact follow-up text (sha256 stored when the pharmacist confirmed it)."""
    return bool(data.get("followup_reviewed_sha256")) and data["followup_reviewed_sha256"] == text_sha(data.get("followup", ""))


def initial_text(patient_name, gp_name):
    # Identity is inserted locally and never sent to a clinical agent.
    data = dict(DEFAULTS)
    data["followup_decision"] = ""  # the pharmacist decides; no follow-up claim is generated before that
    data["followup_policy"] = POLICY_VERSION
    name = (patient_name or '').strip()
    if name:
        data["thanks"] = "Thank you for referring " + name + " for a Home Medicines Review."
    return data


def generated_followup_texts(name):
    return {"", NEUTRAL_FOLLOWUP, required_followup(name), not_required_followup(name)}


def apply_followup_decision(data):
    """Only 'not_required' offers a PROPOSED sentence, and only into blank, neutral or unedited generated text, still
    review-gated. 'required' never generates timing or a repeat-HMR statement: the pharmacist must enter the plan.
    Authored text is never overwritten."""
    decision = data.get("followup_decision", "")
    text = data.get("followup", "").strip()
    name = (data.get("name") or "").strip()
    if not name or not (text in ("", NEUTRAL_FOLLOWUP) or looks_generated(text)): return data
    if decision == "not_required": return {**data, "followup": not_required_followup(name)}
    if decision == "required": return {**data, "followup": NEUTRAL_FOLLOWUP}
    return data


def unresolved(data):
    keys = [key for key in ("reason", "intro")
            if key in data.get("needs_review", []) and not data.get(key, "").strip()]
    text = data.get("followup", "").strip()
    if data.get("followup_policy") == POLICY_VERSION and "followup_decision" not in data:
        keys.append("followup_decision")  # a new-style spec cannot drop the key to bypass the gate
        return keys
    decision = data.get("followup_decision")
    if decision == "": keys.append("followup_decision")
    elif decision == "required" and (not text or text == NEUTRAL_FOLLOWUP or looks_generated(text)):
        keys.append("followup_plan")  # the pharmacist must enter the actual plan and timing
    elif looks_generated(text) and not review_valid(data):
        keys.append("followup_review")  # generated wording (also legacy stock) is not blessed until reviewed for this exact text
    return keys
