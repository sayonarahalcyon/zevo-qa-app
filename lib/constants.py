"""Shared constants for the Ticket QA Sampler.

Mirrors the rubric and rules from the retired "2026 - ZEVO QA Tracker v2"
Google Sheet, with the same two scoring-scale fixes applied in the original
Claude-artifact version of this app:
  - Resolution Quality now offers 0/10/20 (the sheet only allowed 0 or 20).
  - Acknowledge Issue, Communication, and Documentation now include 0
    (the sheet's dropdown only allowed 5/10/15).
Policy Accuracy/Process Compliance/Risk & Safety is unchanged (15/25/35).
"""

import unicodedata

REVIEWER_NAMES = ["Erwin Bagnol", "Weng Yee", "Kristine Lariosa"]

# Reviewers who can open the Team Lead Dashboard "as" any team lead (read-only,
# no password needed). Not every reviewer: Erwin is deliberately left out.
VIEW_AS_TEAM_LEAD_REVIEWERS = ["Weng Yee", "Kristine Lariosa"]
# Who gets "View as agent" on My Dashboard: the same two reviewers, read-only.
VIEW_AS_AGENT_REVIEWERS = ["Weng Yee", "Kristine Lariosa"]

# Reviewers who can open QA Log's "Sign-in activity" panel (how many times, and
# when most recently, each agent, team lead and reviewer signed in). Erwin is
# deliberately left out.
SIGN_IN_ACTIVITY_REVIEWERS = ["Weng Yee", "Kristine Lariosa"]

# Names/words that identify a non-frontline reviewer rather than an agent.
# Conversations authored/handled by these people are never offered up as
# something to sample, and they're excluded from the auto-learned agent
# roster.
#
# "erwin" was dropped from this set on 2026-10-03: Erwin Bagnol's Intercom
# admin account (id 9817286, display name "Erwin") turned out to be
# actively handling frontline tickets (400+ conversations), and Weng
# confirmed he should now be tracked and QA'd like any other agent, under
# Kristine's team. If ZEVO ever adds a reviewer-only "Erwin" whose tickets
# should stay out of the roster, exclude that specific admin id in code
# rather than re-adding "erwin" here — a word match would block every
# agent who happens to share that first name.
EXCLUDED_AGENT_WORDS = {"kristine", "weng"}

# Full Intercom admin display names that are shared inboxes, bots, or
# non-frontline stakeholders rather than real agents (e.g. a shared support
# mailbox, or a senior stakeholder whose Intercom account shows a shortened
# name). Matched as a whole name rather than word-by-word like
# EXCLUDED_AGENT_WORDS above, since several of these are common first names
# that would otherwise risk excluding a real agent who happens to share one.
EXCLUDED_AGENT_NAMES = {
    "sunny",
    "taylor",
    "sam",
    "zevo customer care",
    "garron",
    "damir luketic",
    "cameron preston",
}

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

# Which support channel a QA audit came from. "Chat" covers every audit
# logged before phone QA existed (all sourced from Intercom conversations);
# "Phone" audits are scored on the separate phone rubric below. Both use the
# same 100-point scale and the same result thresholds, so their totals can be
# compared directly. See QA Log's Audit log filter and lib/qa_form.py.
CHANNEL_OPTIONS = ["Chat", "Phone"]

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

# ---------------------------------------------------------------------------
# Phone rubric (added 2026-10-19, from the "Phone Support QA Evaluation
# Framework" of Sep 23, 2026). Six categories, 100 points, same PASS / COACHING
# / FAIL / AUTO FAIL thresholds as chat. Audits are scored from the call
# recording (tone, pace and silence do not show in a transcript), and the
# call's Intercom/ZOMP notes are checked for Documentation.
#
# The category weights, the evaluator guide text and the five critical errors
# below are the framework as written (approved by Weng). To change a weight or
# a critical error, edit this block only: every screen reads it from here.
#
# Keys "policy", "resolution" and "documentation" are shared with the chat
# rubric on purpose (the same idea in both), so those categories stay
# comparable in the data. "opening", "listening" and "call_control" exist only
# on phone, and are what tells a phone audit's scores apart from a chat one.
# ---------------------------------------------------------------------------
PHONE_RUBRIC = [
    {"key": "opening", "name": "Opening & Verification", "max": 10},
    {"key": "listening", "name": "Acknowledge & Listen", "max": 10},
    {"key": "call_control", "name": "Communication & Call Control", "max": 15},
    {"key": "policy", "name": "Policy Accuracy, Process Compliance, Risk & Safety", "max": 30},
    {"key": "resolution", "name": "Resolution & Closing", "max": 20},
    {"key": "documentation", "name": "Documentation", "max": 15},
]
# Phone categories have no fixed levels: the reviewer enters a whole number from
# 0 to the category's points, as written in the Phone Support QA Evaluation
# Framework (Sep 23, 2026). The text below is that framework's "what the
# evaluator listens for" column.

PHONE_RUBRIC_GUIDE = {
    "opening": "Greeting and name given, reason for the call confirmed, identity checked before any account details are discussed or changed.",
    "listening": "Lets the caller finish without interrupting, restates the issue accurately, asks clarifying questions, shows empathy where it fits.",
    "call_control": "Clear, steady pace and confident tone; no long silences; proper hold etiquette (asks first, gives a time estimate, checks back in); warm transfers with context; steers the call back when it drifts.",
    "policy": "Correct policy information, follows the right process, handles safety situations correctly (accidents, roadside issues, vehicle condition).",
    "resolution": "Solves the issue or gives clear next steps with a timeframe, recaps before hanging up, confirms nothing else is needed.",
    "documentation": "Post-call notes in Intercom/ZOMP are accurate and complete enough for the next agent to pick up without calling the customer back.",
}

# Keys that only exist on the phone rubric. An audit whose saved scores contain
# any of these was scored on the phone rubric.
PHONE_ONLY_KEYS = {"opening", "listening", "call_control"}

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

# Categories offered on the "Question or dispute about this audit?" form on
# My Dashboard (lib/disputes.py) when the agent picks "Dispute the score" —
# mirrors the rubric categories plus "Critical Error", matching the old
# external QA Audit Question & Dispute Form's category checkboxes.
DISPUTE_CATEGORIES = [r["name"] for r in RUBRIC] + ["Critical Error"]

# The five phone critical errors (any one is an AUTO FAIL). "refund" and
# "safety" reuse the chat keys, since they are the same kind of mistake, so
# reports that count critical errors by key stay consistent across channels.
# The wording is the phone framework's: "refund" is broader (any credit or
# exception, not only a refund) and "safety" is about giving incorrect
# guidance. "verification", "hangup" and "conduct" are phone-only. The chat
# flags "access" (allowed access during a dispute) and "policy" (wrong policy
# given) are not on the phone list.
PHONE_CRITICAL_ERRORS = [
    {
        "key": "verification",
        "label": "Shared or changed account details before verifying the caller",
        "desc": "Identity must be verified before any account details are discussed or changed.",
    },
    {
        "key": "safety",
        "label": "Gave incorrect safety guidance",
        "desc": "Agent gave wrong guidance in a safety or urgent situation (accident, roadside issue, vehicle condition).",
    },
    {
        "key": "hangup",
        "label": "Hung up on the caller, or muted them without telling them",
        "desc": "The caller must never be hung up on, and must be told before being muted.",
    },
    {
        "key": "conduct",
        "label": "Rude or unprofessional conduct",
        "desc": "Agent was rude or unprofessional with the caller.",
    },
    {
        "key": "refund",
        "label": "Promised a refund, credit, or exception they are not authorized to give",
        "desc": "Refunds, credits and exceptions may only be offered when the agent is authorized to give them.",
    },
]

PHONE_DISPUTE_CATEGORIES = [r["name"] for r in PHONE_RUBRIC] + ["Critical Error"]

# Everything that depends on the channel, looked up by channel name. Use the
# helpers below rather than indexing these directly, so an unknown or blank
# channel falls back to Chat.
RUBRICS = {"Chat": RUBRIC, "Phone": PHONE_RUBRIC}
RUBRIC_GUIDES = {"Chat": RUBRIC_GUIDE, "Phone": PHONE_RUBRIC_GUIDE}
CRITICAL_ERROR_SETS = {"Chat": CRITICAL_ERRORS, "Phone": PHONE_CRITICAL_ERRORS}
DISPUTE_CATEGORY_SETS = {"Chat": DISPUTE_CATEGORIES, "Phone": PHONE_DISPUTE_CATEGORIES}


def rubric_channel(entry: dict | None) -> str:
    """Which rubric a saved audit was scored on: "Phone" or "Chat".

    A Phone audit uses the phone rubric. The exception is a Phone-tagged audit
    saved before the phone rubric existed (when the Channel tag was only a
    label): its scores use the chat keys, so it keeps being shown with the chat
    rubric instead of with six categories it was never scored on."""
    entry = entry or {}
    if (entry.get("channel") or "Chat") != "Phone":
        return "Chat"
    scores = entry.get("scores") or {}
    if scores and not (PHONE_ONLY_KEYS & set(scores)):
        return "Chat"
    return "Phone"


def rubric_for(channel: str | None) -> list:
    return RUBRICS.get(channel or "Chat", RUBRIC)


def rubric_guide_for(channel: str | None) -> dict:
    return RUBRIC_GUIDES.get(channel or "Chat", RUBRIC_GUIDE)


def critical_errors_for(channel: str | None) -> list:
    return CRITICAL_ERROR_SETS.get(channel or "Chat", CRITICAL_ERRORS)


def dispute_categories_for(channel: str | None) -> list:
    return DISPUTE_CATEGORY_SETS.get(channel or "Chat", DISPUTE_CATEGORIES)

RESULT_PASS = "PASS"
RESULT_COACHING = "COACHING"
RESULT_FAIL = "FAIL"
RESULT_AUTOFAIL = "AUTO FAIL"


def compute_total(scores: dict, channel: str | None = "Chat") -> int:
    """scores: {rubric_key: int}. `channel` picks the rubric ("Chat" unless
    told otherwise, so every existing call behaves exactly as before)."""
    return sum(int(scores.get(r["key"], 0) or 0) for r in rubric_for(channel))


def compute_result(total: int, critical: dict, channel: str | None = "Chat") -> str:
    if any(critical.get(c["key"]) for c in critical_errors_for(channel)):
        return RESULT_AUTOFAIL
    if total >= 85:
        return RESULT_PASS
    if total >= 70:
        return RESULT_COACHING
    return RESULT_FAIL


def _normalize_name(name: str) -> str:
    """Lowercased, whitespace-trimmed, and stripped of accents (so "Luketić"
    and "Luketic" compare equal) — used for the exact-name exclusion check."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.strip().lower()


def is_excluded_agent_name(name: str) -> bool:
    normalized = _normalize_name(name)
    if normalized in EXCLUDED_AGENT_NAMES:
        return True
    return any(w in EXCLUDED_AGENT_WORDS for w in normalized.split())
