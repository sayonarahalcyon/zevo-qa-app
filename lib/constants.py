"""Shared constants for the Ticket QA Sampler.

Mirrors the rubric and rules from the retired "2026 - ZEVO QA Tracker v2"
Google Sheet, with the same two scoring-scale fixes applied in the original
Claude-artifact version of this app:
  - Resolution Quality now offers 0/10/20 (the sheet only allowed 0 or 20).
  - Acknowledge Issue, Communication, and Documentation now include 0
    (the sheet's dropdown only allowed 5/10/15).
Policy Accuracy/Process Compliance/Risk & Safety is unchanged (15/25/35).
"""

REVIEWER_NAMES = ["Erwin Bagnol", "Weng Yee", "Kristine Lariosa"]

# Names/words that identify a non-frontline reviewer rather than an agent.
# Conversations authored/handled by these people are never offered up as
# something to sample, and they're excluded from the auto-learned agent
# roster.
EXCLUDED_AGENT_WORDS = {"kristine", "weng", "erwin"}

CONCERN_TYPES = [
    "Extension",
    "Billing",
    "Vehicle Issue",
    "Claims",
    "Access",
    "Dispute",
    "Refund",
    "Vehicle Listing/Details",
    "Other",
]

RENTER_HOST_OPTIONS = ["", "Renter", "Host", "Other Entity"]

# key, label, max points, allowed score options
RUBRIC = [
    {"key": "acknowledge", "name": "Acknowledge Issue", "max": 15, "options": [0, 10, 15]},
    {"key": "communication", "name": "Communication", "max": 15, "options": [0, 10, 15]},
    {
        "key": "policy",
        "name": "Policy Accuracy, Process Compliance, Risk & Safety",
        "max": 35,
        "options": [15, 25, 35],
    },
    {"key": "resolution", "name": "Resolution Quality", "max": 20, "options": [0, 10, 20]},
    {"key": "documentation", "name": "Documentation", "max": 15, "options": [0, 10, 15]},
]

RUBRIC_GUIDE = {
    "acknowledge": "0 = No acknowledgment · 10 = Generic · 15 = Specific + empathetic — Did the agent clearly identify and acknowledge the renter's concern(s)?",
    "communication": "0 = Hard to understand / unprofessional · 10 = Understandable but not smooth · 15 = Clear, natural, professional — Was the response clear, professional, and easy to understand?",
    "policy": "15 = KB/Policy guidance not followed · 25 = Partially followed · 35 = Followed — Did the agent apply the correct ZEVO policy, follow the correct workflow, and handle any urgent/safety concern properly?",
    "resolution": "0 = No resolution · 10 = Partial resolution · 20 = Clear and actionable resolution — Did the agent move the issue toward a real next step for the renter?",
    "documentation": "0 = No notes · 10 = Incomplete/incorrect notes · 15 = Complete notes — Are vehicle notes, override notes, and host-dashboard notes documented in ZOMP/Intercom as needed?",
}

CRITICAL_ERRORS = [
    {
        "key": "refund",
        "label": "Promised refund incorrectly",
        "desc": "Refunds must only be explained, not promised, without confirming eligibility or following the ZEVO refund process.",
    },
    {
        "key": "access",
        "label": "Allowed access with dispute",
        "desc": "Access must stay restricted while a payment dispute is active — only restore after official closure.",
    },
    {
        "key": "policy",
        "label": "Wrong policy given / process applied",
        "desc": "Agent provided incorrect ZEVO policy or misleading information.",
    },
    {
        "key": "safety",
        "label": "Ignored safety issue",
        "desc": "Agent failed to properly prioritize or escalate a safety or urgent concern (stranded renter, battery, lockout).",
    },
]

DISPUTE_FORM_URL = "https://forms.gle/zWbCg2ZRAcpmK6zb7"

RESULT_PASS = "PASS"
RESULT_COACHING = "COACHING"
RESULT_FAIL = "FAIL"
RESULT_AUTOFAIL = "AUTO FAIL"


def compute_total(scores: dict) -> int:
    """scores: {rubric_key: int}"""
    return sum(int(scores.get(r["key"], 0) or 0) for r in RUBRIC)


def compute_result(total: int, critical: dict) -> str:
    if any(critical.get(c["key"]) for c in CRITICAL_ERRORS):
        return RESULT_AUTOFAIL
    if total >= 85:
        return RESULT_PASS
    if total >= 70:
        return RESULT_COACHING
    return RESULT_FAIL


def is_excluded_agent_name(name: str) -> bool:
    words = (name or "").lower().split()
    return any(w in EXCLUDED_AGENT_WORDS for w in words)
