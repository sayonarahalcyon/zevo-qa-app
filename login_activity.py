"""Turns the raw login_events log into the tables and numbers on the "Sign-in
activity" panel on the QA Log page (Weng and Kristine). Kept free of Streamlit
so it can be tested on its own.

login_events holds one row per event: a sign-in, a reviewer's "View as team
lead", or something a person did afterward (see lib/activity.py). Rows written
before activity logging existed have no `kind` and read as sign-ins."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from lib.activity import ACTION_LABELS

ROLE_LABELS = {"agent": "Agent", "team_lead": "Team lead", "reviewer": "Reviewer"}

SIGN_IN = "sign_in"
VIEW_AS = "view_as"


def _tz(tz_name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(dt: datetime | None, tz_name: str = "UTC") -> str:
    return dt.astimezone(_tz(tz_name)).strftime("%Y-%m-%d %H:%M") if dt else "Never"


def _kind(e: dict) -> str:
    return e.get("kind") or SIGN_IN


def _by_reviewer(e: dict) -> str | None:
    """The reviewer behind this event, or None if no reviewer was involved (the
    person themselves, as far as the app can tell). Reviewer-role rows are the
    reviewer's own events and never count as "by a reviewer"."""
    if e.get("role") == "reviewer":
        return None
    return e.get("by_reviewer") or None


def _how(e: dict) -> str:
    who = _by_reviewer(e)
    if not who:
        return "Themselves"
    if _kind(e) == VIEW_AS:
        return f"View as, by {who}"
    return f"Reviewer session, {who}"


def _what(e: dict) -> str:
    return ACTION_LABELS.get(_kind(e), _kind(e).replace("_", " ").capitalize())


def local_date(e: dict, tz_name: str = "UTC") -> date | None:
    when = _parse(e.get("signed_in_at"))
    return when.astimezone(_tz(tz_name)).date() if when else None


def in_range(events: list, start: date | None, end: date | None, tz_name: str = "UTC") -> list:
    """Events whose date, in the chosen time zone, is between start and end
    inclusive. None for either end means no limit on that side."""
    out = []
    for e in events:
        d = local_date(e, tz_name)
        if d is None:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(e)
    return out


def totals(events: list) -> dict:
    """Headline numbers for a set of events: sign-ins by the people themselves,
    how many times a reviewer signed in as or viewed as someone, how many
    different people signed in themselves, and the actions people took."""
    own_people = set()
    out = {"sign_ins": 0, "reviewer_access": 0, "people": 0, "actions": 0}
    for e in events:
        kind = _kind(e)
        by = _by_reviewer(e)
        if kind in (SIGN_IN, VIEW_AS):
            if by:
                out["reviewer_access"] += 1
            elif kind == SIGN_IN:
                out["sign_ins"] += 1
                own_people.add((e.get("role"), str(e.get("person_id"))))
        elif not by:
            out["actions"] += 1
    out["people"] = len(own_people)
    return out


def summarize(events: list, agents: list, team_leads: list, is_excluded=lambda name: False,
              reviewers: list | None = None, tz_name: str = "UTC") -> pd.DataFrame:
    """One row per person: role, name, sign-in count and last sign-in by the
    person themselves, how many times, and when last, a reviewer signed in as
    them or viewed as them, and how many actions they took.

    "By themselves" means no reviewer was signed in on that browser session. A
    password cannot prove who typed it, so this is the closest the app can get:
    a reviewer who signs in as an agent or team lead in a separate browser or
    private window looks like the person themselves. "Reviewer access" is
    either a password sign-in made while a reviewer was signed in on the same
    session, or a reviewer's "View as team lead". "Actions" is everything the
    person did after signing in (pages opened and so on), not counting what a
    reviewer did while signed in as them.

    Everyone on the current roster appears, including people who have no
    events in the set (count 0, "Never"). Someone who appears in the events and
    has since been removed from the roster still appears, using the name
    recorded at the time. Sorted with the most recent sign-in first."""
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
    actions: dict = {}
    for e in events:
        role = e.get("role")
        if role not in ROLE_LABELS:
            continue
        key = (role, str(e.get("person_id")))
        people.setdefault(key, e.get("person_name") or key[1])
        kind = _kind(e)
        by = _by_reviewer(e)
        if kind not in (SIGN_IN, VIEW_AS):
            if not by:
                actions[key] = actions.get(key, 0) + 1
            continue
        if kind == VIEW_AS and not by:
            continue
        when = _parse(e.get("signed_in_at"))
        bucket = by_rev if by else own
        count, last, who = bucket.get(key, (0, None, None))
        if when and (last is None or when > last):
            last, who = when, by
        bucket[key] = (count + 1, last, who)

    sign_col = f"Last sign-in ({tz_name})"
    rev_col = f"Last reviewer access ({tz_name})"
    rows = []
    for (role, pid), name in people.items():
        count, last, _ = own.get((role, pid), (0, None, None))
        rcount, rlast, rwho = by_rev.get((role, pid), (0, None, None))
        if role == "reviewer":
            reviewer_cols = (None, "")
        else:
            reviewer_cols = (rcount, f"{_fmt(rlast, tz_name)} by {rwho}" if rlast and rwho else "Never")
        rows.append({"_sort": last or datetime.min.replace(tzinfo=timezone.utc), "Role": ROLE_LABELS[role],
                     "Name": name, "Sign-ins": count, sign_col: _fmt(last, tz_name),
                     "Reviewer access": reviewer_cols[0], rev_col: reviewer_cols[1],
                     "Actions": actions.get((role, pid), 0)})
    rows.sort(key=lambda r: (r["_sort"], r["Name"].lower()), reverse=True)
    cols = ["_sort", "Role", "Name", "Sign-ins", sign_col, "Reviewer access", rev_col, "Actions"]
    df = pd.DataFrame(rows, columns=cols).drop(columns="_sort")
    # Nullable integers (a reviewer's own row has no "reviewer access") so the
    # table serializes cleanly instead of mixing numbers with blank text.
    df["Reviewer access"] = df["Reviewer access"].astype("Int64")
    return df.reset_index(drop=True)


def timeline(events: list, tz_name: str = "UTC", person: str | None = None, kinds: list | None = None,
             limit: int | None = None) -> pd.DataFrame:
    """Individual events, newest first: when (in the chosen time zone), who,
    what they did, the detail (page, agent, period, ticket), and how it
    happened (themselves, or a reviewer signed in as / viewing as them).
    `person` limits to one name; `kinds` to those event kinds."""
    rows = []
    for e in events:
        when = _parse(e.get("signed_in_at"))
        if e.get("role") not in ROLE_LABELS or not when:
            continue
        if person and (e.get("person_name") or "") != person:
            continue
        if kinds is not None and _kind(e) not in kinds:
            continue
        rows.append((when, ROLE_LABELS[e["role"]], e.get("person_name") or "", _what(e), e.get("detail") or "", _how(e)))
    rows.sort(key=lambda r: r[0], reverse=True)
    if limit:
        rows = rows[:limit]
    return pd.DataFrame(
        [{f"When ({tz_name})": _fmt(w, tz_name) + ":" + f"{w.astimezone(_tz(tz_name)).second:02d}", "Role": r, "Name": n,
          "What": what, "Detail": d, "How": h} for w, r, n, what, d, h in rows],
        columns=[f"When ({tz_name})", "Role", "Name", "What", "Detail", "How"],
    )


def recent(events: list, limit: int = 25) -> pd.DataFrame:
    """The most recent sign-ins (not other activity), newest first, with how
    each happened. Kept for the older, simpler view."""
    return timeline(events, "UTC", kinds=[SIGN_IN, VIEW_AS], limit=limit)[["When (UTC)", "Role", "Name", "How"]]


def per_day(events: list, start: date | None, end: date | None, tz_name: str = "UTC") -> pd.DataFrame:
    """Sign-ins by the people themselves per local day, as a one-column frame
    indexed by date. Days with none are filled in as 0 when the range is known
    and at most 120 days long, so the chart shows quiet days too."""
    counts: dict = {}
    for e in events:
        if _kind(e) != SIGN_IN or _by_reviewer(e):
            continue
        d = local_date(e, tz_name)
        if d:
            counts[d] = counts.get(d, 0) + 1
    if start and end and (end - start).days <= 120:
        day = start
        while day <= end:
            counts.setdefault(day, 0)
            day += timedelta(days=1)
    s = pd.Series(counts, dtype="int64").sort_index()
    return pd.DataFrame({"Sign-ins": s})
