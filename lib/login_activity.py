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


def summarize(events: list, agents: list, team_leads: list, is_excluded=lambda name: False, reviewers: list | None = None) -> pd.DataFrame:
    """One row per person: role, name, sign-in count, last sign-in (UTC).

    Everyone on the current roster appears, including people who have never
    signed in (count 0, "Never"), so a quiet person is visible rather than
    missing. Someone who signed in once and has since been removed from the
    roster still appears, using the name recorded at the time. Sorted with
    the most recent sign-in first, never-signed-in last."""
    people: dict = {}
    for a in agents:
        if a.get("name") and not is_excluded(a["name"]):
            people[("agent", str(a["id"]))] = a["name"]
    for t in team_leads:
        if t.get("name"):
            people[("team_lead", str(t["id"]))] = t["name"]
    for name in reviewers or []:
        people[("reviewer", name)] = name

    stats: dict = {}
    for e in events:
        role = e.get("role")
        if role not in ROLE_LABELS:
            continue
        key = (role, str(e.get("person_id")))
        when = _parse(e.get("signed_in_at"))
        count, last = stats.get(key, (0, None))
        stats[key] = (count + 1, max([x for x in (last, when) if x], default=None))
        people.setdefault(key, e.get("person_name") or key[1])

    rows = []
    for (role, pid), name in people.items():
        count, last = stats.get((role, pid), (0, None))
        rows.append({"_sort": last or datetime.min.replace(tzinfo=timezone.utc), "Role": ROLE_LABELS[role],
                     "Name": name, "Sign-ins": count, "Last sign-in (UTC)": _fmt(last)})
    rows.sort(key=lambda r: (r["_sort"], r["Name"].lower()), reverse=True)
    df = pd.DataFrame(rows, columns=["_sort", "Role", "Name", "Sign-ins", "Last sign-in (UTC)"]).drop(columns="_sort")
    return df.reset_index(drop=True)


def recent(events: list, limit: int = 25) -> pd.DataFrame:
    """The most recent individual sign-ins, newest first."""
    rows = []
    for e in events:
        when = _parse(e.get("signed_in_at"))
        if e.get("role") in ROLE_LABELS and when:
            rows.append((when, ROLE_LABELS[e["role"]], e.get("person_name") or ""))
    rows.sort(key=lambda r: r[0], reverse=True)
    return pd.DataFrame(
        [{"When (UTC)": _fmt(w), "Role": r, "Name": n} for w, r, n in rows[:limit]],
        columns=["When (UTC)", "Role", "Name"],
    )
