"""Activity log: what each signed-in person does in the app, for Weng's and
Kristine's "Sign-in activity" panel on QA Log.

Everything goes into the same login_events table as sign-ins, one row per
event, with `kind` saying what it was (see ACTION_LABELS). An event is only
recorded when something real happened that makes the app run: opening a page,
opening an agent, changing the period, filing a question or dispute, changing
a password, signing out. The app cannot see scrolling, reading, or opening or
closing a section on a page, so those are not recorded.

Every function here is best-effort and silent: logging must never get in the
way of someone using the app, so any failure is swallowed.
"""

import streamlit as st

from lib import db

ACTION_LABELS = {
    "sign_in": "Signed in",
    "view_as": "Viewed as team lead",
    "page_view": "Opened a page",
    "open_agent": "Opened an agent",
    "change_period": "Changed the period",
    "file_question": "Filed a question",
    "file_dispute": "Filed a dispute",
    "change_password": "Changed password",
    "sign_out": "Signed out",
}

_LAST = "_act_last::"
_VAL = "_act_val::"
_MISSING = object()


def set_view_as(lead: dict | None) -> None:
    """Called by the Team Lead Dashboard on every run: while a reviewer is
    viewing as a team lead, what they do is recorded under that team lead and
    marked as the reviewer's, never as the team lead's own."""
    ss = st.session_state
    if lead and ss.get("reviewer_name"):
        ss["_activity_view_as"] = (lead["id"], lead["name"])
    else:
        ss.pop("_activity_view_as", None)


def reset() -> None:
    """Forget the "already logged" bookkeeping, so the next page a person
    opens after signing in or out is recorded."""
    ss = st.session_state
    for k in [k for k in ss.keys() if isinstance(k, str) and k.startswith(_LAST)]:
        ss.pop(k, None)


def _identity(role: str | None):
    """(role, person_id, person_name, by_reviewer) for who is acting, or None.
    `role` says which identity the page belongs to: "agent" for My Dashboard,
    "team_lead" for the Team Lead Dashboard, None for the reviewer pages."""
    ss = st.session_state
    reviewer = ss.get("reviewer_name")
    if role == "team_lead":
        view_as = ss.get("_activity_view_as")
        if view_as and reviewer:
            return "team_lead", view_as[0], view_as[1], reviewer
        lead = ss.get("team_lead_signed_in")
        if lead:
            return "team_lead", lead["id"], lead["name"], reviewer or None
        return None
    if role == "agent":
        agent = ss.get("agent_signed_in")
        if agent:
            return "agent", agent["id"], agent["name"], reviewer or None
        return None
    if reviewer:
        return "reviewer", reviewer, reviewer, None
    return None


def log(action: str, detail: str = "", role: str | None = None, *, dedupe=None) -> None:
    """Records one event for whoever is acting. `dedupe=(name, value)` skips
    the event when the last one logged under `name` had the same value, so
    Streamlit re-running a page does not log it again."""
    try:
        who = _identity(role)
        if not who:
            return
        if dedupe is not None:
            key = _LAST + dedupe[0]
            value = (dedupe[1], who[1], who[3])
            if st.session_state.get(key) == value:
                return
            st.session_state[key] = value
        db.record_login(who[0], who[1], who[2], by_reviewer=who[3], kind=action, detail=detail)
    except Exception:
        pass


def page_view(title: str, role: str | None = None) -> None:
    """Records opening a page once, not on every rerun of it."""
    log("page_view", title, role, dedupe=("page", title))


def changed(key: str, value, action: str, detail: str = "", role: str | None = None) -> None:
    """Records a change to something (the period picker, say). The first time a
    value is seen it is only remembered, so just opening a page records nothing."""
    try:
        ss = st.session_state
        previous = ss.get(_VAL + key, _MISSING)
        ss[_VAL + key] = value
        if previous is _MISSING or previous == value:
            return
        log(action, detail, role)
    except Exception:
        pass
