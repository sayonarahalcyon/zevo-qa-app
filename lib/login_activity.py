"""Turns the raw login_events log into the "Sign-in activity" table on the
QA Log page (visible only to Weng). Kept free of Streamlit so it can be
tested on its own."""

from datetime import datetime, timezone

import pandas as pd

ROLE_LABELS = {"agent": "Agent", "team_lead": "Team lead", "reviewer": "Reviewer"}


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if dt else "Never"


def _by_reviewer(e: dict) -> str | None:
    """The reviewer behind this event, or None if no reviewer was involved (the
    person themselves, as far as the app can tell). Reviewer-role rows are the
    reviewer's own sign-ins and never count as "by a reviewer"."""
    if e.get("role") == "reviewer":
        return None
    return e.get("by_reviewer") or None


def _how(e: dict) -> str:
    who = _by_reviewer(e)
    if not who:
        return "Themselves"
    if e.get("kind") == "view_as":
        return f"View as, by {who}"
    return f"Reviewer session, {who}"


def summarize(events: list, agents: list, team_leads: list, is_excluded=lambda name: False, reviewers: list | None = None) -> pd.DataFrame:
    """One row per person: role, name, sign-in count and last sign-in (UTC) by
    the person themselves, plus how many times, and when last, a reviewer
    signed in as them or viewed as them.

    "By themselves" means no reviewer was signed in on that browser session. A
    password cannot prove who typed it, so this is the closest the app can get:
    a reviewer who signs in as an agent or team lead in a separate browser or
    private window looks like the person themselves. "Reviewer access" is
    either a password sign-in made while a reviewer was signed in on the same
    session, or a reviewer's "View as team lead".

    Everyone on the current roster appears, including people who have never
    signed in (count 0, "Never"). Someone who signed in once and has since been
    removed from the roster still appears, using the name recorded at the time.
    Sorted with the most recent sign-in first, never-signed-in last."""
    people: dict = {}
    for a in agents:
        if a.get("name") and not is_excluded(a["name"]):
            people[("agent", str(a["id"]))] = a["name"]
    for t in team_leads:
        if t.get("name"):
            people[("team_lead", str(t["id"]))] = t["name"]
    for name in reviewers or []:
        people[("reviewer", name)] = name

    own: dict = {}
    by_rev: dict = {}
    for e in events:
        role = e.get("role")
        if role not in ROLE_LABELS:
            continue
        key = (role, str(e.get("person_id")))
        when = _parse(e.get("signed_in_at"))
        bucket = by_rev if _by_reviewer(e) else own
        count, last, who = bucket.get(key, (0, None, None))
        if when and (last is None or when > last):
            last, who = when, _by_reviewer(e)
        bucket[key] = (count + 1, last, who)
        people.setdefault(key, e.get("person_name") or key[1])

    rows = []
    for (role, pid), name in people.items():
        count, last, _ = own.get((role, pid), (0, None, None))
        rcount, rlast, rwho = by_rev.get((role, pid), (0, None, None))
        if role == "reviewer":
            reviewer_cols = (None, "")
        else:
            reviewer_cols = (rcount, f"{_fmt(rlast)} by {rwho}" if rlast and rwho else "Never")
        rows.append({"_sort": last or datetime.min.replace(tzinfo=timezone.utc), "Role": ROLE_LABELS[role],
                     "Name": name, "Sign-ins": count, "Last sign-in (UTC)": _fmt(last),
                     "Reviewer access": reviewer_cols[0], "Last reviewer access (UTC)": reviewer_cols[1]})
    rows.sort(key=lambda r: (r["_sort"], r["Name"].lower()), reverse=True)
    cols = ["_sort", "Role", "Name", "Sign-ins", "Last sign-in (UTC)", "Reviewer access", "Last reviewer access (UTC)"]
    df = pd.DataFrame(rows, columns=cols).drop(columns="_sort")
    # Nullable integers (a reviewer's own row has no "reviewer access") so the
    # table serializes cleanly instead of mixing numbers with blank text.
    df["Reviewer access"] = df["Reviewer access"].astype("Int64")
    return df.reset_index(drop=True)


def recent(events: list, limit: int = 25) -> pd.DataFrame:
    """The most recent individual events, newest first, with how each happened."""
    rows = []
    for e in events:
        when = _parse(e.get("signed_in_at"))
        if e.get("role") in ROLE_LABELS and when:
            rows.append((when, ROLE_LABELS[e["role"]], e.get("person_name") or "", _how(e)))
    rows.sort(key=lambda r: r[0], reverse=True)
    return pd.DataFrame(
        [{"When (UTC)": _fmt(w), "Role": r, "Name": n, "How": h} for w, r, n, h in rows[:limit]],
        columns=["When (UTC)", "Role", "Name", "How"],
    )
