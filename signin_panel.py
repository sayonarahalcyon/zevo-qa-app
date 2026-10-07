"""The "Sign-in activity" panel on QA Log (Weng and Kristine): who signed in,
how often, when, and what they did, for a day, week, month, custom range or
all time. The numbers come from lib/login_activity.py."""

from datetime import datetime, timedelta, timezone

import streamlit as st

from lib import db, login_activity
from lib.activity import ACTION_LABELS
from lib.constants import REVIEWER_NAMES, is_excluded_agent_name
from lib.weeks import week_bounds

MODES = ["Day", "Week", "Month", "Custom range", "All time"]
ROLE_FILTERS = ["Everyone", "Team leads", "Agents", "Reviewers"]
ROLE_OF_FILTER = {"Team leads": "Team lead", "Agents": "Agent", "Reviewers": "Reviewer"}
TIMELINE_CAP = 500


def _time_zones() -> list:
    try:
        from zoneinfo import available_timezones

        zones = sorted(z for z in available_timezones() if "/" in z)
    except Exception:
        zones = []
    return ["UTC"] + zones


def _today(tz_name: str):
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _day(d) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _pick_range(events: list, tz_name: str):
    """Draws the period controls and returns (start, end, label); None for an
    open end. All dates are in the chosen time zone."""
    today = _today(tz_name)
    mode = st.radio("Show", MODES, index=1, horizontal=True, key="login_activity_mode")
    dated = [d for d in (login_activity.local_date(e, tz_name) for e in events) if d]
    earliest = min(dated) if dated else today

    if mode == "Day":
        d = st.date_input("Date", value=today, max_value=today, key="login_activity_day")
        return d, d, _day(d)
    if mode == "Week":
        first = week_bounds(min(earliest, today))[0]
        starts, cur = [], week_bounds(today)[0]
        while cur >= first:
            starts.append(cur)
            cur -= timedelta(days=7)

        def label(s):
            e = s + timedelta(days=6)
            tag = " (this week)" if s == week_bounds(today)[0] else ""
            return f"{s.strftime('%b')} {s.day} – {e.strftime('%b')} {e.day}, {e.year}{tag}"

        s = st.selectbox("Week (Sunday to Saturday)", starts, format_func=label, key="login_activity_week")
        return s, s + timedelta(days=6), label(s).replace(" (this week)", "")
    if mode == "Month":
        months, y, m = [], today.year, today.month
        while (y, m) >= (earliest.year, earliest.month):
            months.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12

        def mlabel(ym):
            tag = " (this month)" if ym == (today.year, today.month) else ""
            return datetime(ym[0], ym[1], 1).strftime("%B %Y") + tag

        ym = st.selectbox("Month", months, format_func=mlabel, key="login_activity_month")
        start = datetime(ym[0], ym[1], 1).date()
        nxt = datetime(ym[0] + (ym[1] == 12), (ym[1] % 12) + 1, 1).date()
        return start, nxt - timedelta(days=1), mlabel(ym).replace(" (this month)", "")
    if mode == "Custom range":
        c1, c2 = st.columns(2)
        start = c1.date_input("From", value=today - timedelta(days=6), max_value=today, key="login_activity_from")
        end = c2.date_input("To", value=today, max_value=today, key="login_activity_to")
        if start > end:
            st.warning("The From date is after the To date, so nothing matches. Swap them.")
        return start, end, f"{_day(start)} to {_day(end)}"
    return None, None, "all time"


def render(agents: list, team_leads: list) -> None:
    all_events = db.list_login_events()
    st.caption(
        "Who signed in, how often, when, and what they did. Counting started the day the sign-in log was "
        "set up, and activity (pages opened and so on) the day activity logging was added; nothing earlier "
        "was recorded. The app records pages opened, opening an agent, changing the period, filing a "
        "question or dispute, changing a password, and signing out. It cannot see scrolling, reading, or "
        "opening a section on a page."
    )
    st.caption(
        "\"Sign-ins\" counts a person signing in themselves (no reviewer was signed in on that browser "
        "session). \"Reviewer access\" counts a password sign-in made while a reviewer was signed in, and a "
        "reviewer's View as team lead. A password can't prove who typed it, so a reviewer signing in as "
        "someone from a separate or private window looks like the person."
    )
    if not all_events:
        st.info(
            "Nothing recorded yet. If the login_events table hasn't been created in Supabase, run "
            "sql/migrations/2026_10_06_add_login_events.sql first."
        )

    zones = _time_zones()
    tz_name = st.selectbox("Time zone", zones, index=0, key="login_activity_tz",
                           help="Days, weeks and months, and every time shown below, use this time zone.")
    start, end, label = _pick_range(all_events, tz_name)
    role_filter = st.radio("Who", ROLE_FILTERS, horizontal=True, key="login_activity_role")

    events = login_activity.in_range(all_events, start, end, tz_name)
    if role_filter != "Everyone":
        want = {v: k for k, v in login_activity.ROLE_LABELS.items()}[ROLE_OF_FILTER[role_filter]]
        events = [e for e in events if e.get("role") == want]

    st.markdown(f"**{label.capitalize() if label == 'all time' else label}**")
    t = login_activity.totals(events)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sign-ins", t["sign_ins"], help="Times someone signed in themselves (no reviewer signed in on that browser session).")
    m2.metric("People who signed in", t["people"], help="Different people with at least one sign-in of their own.")
    m3.metric("Reviewer access", t["reviewer_access"], help="Sign-ins made while a reviewer was signed in, plus View as team lead picks.")
    m4.metric("Actions", t["actions"], help="Pages opened, agents opened, period changes, questions and disputes filed, password changes and sign-outs, by the people themselves.")

    per_day = login_activity.per_day(events, start, end, tz_name)
    if len(per_day) > 1:
        st.markdown("**Sign-ins per day**")
        st.bar_chart(per_day, height=220)

    st.markdown("**By person**")
    summary = login_activity.summarize(
        events, agents, team_leads, is_excluded=is_excluded_agent_name, reviewers=REVIEWER_NAMES, tz_name=tz_name
    )
    if role_filter != "Everyone":
        summary = summary[summary["Role"] == ROLE_OF_FILTER[role_filter]]
    st.dataframe(summary, use_container_width=True, hide_index=True)

    st.markdown("**What happened, newest first**")
    names = sorted({e.get("person_name") for e in events if e.get("person_name")}, key=str.lower)
    f1, f2 = st.columns(2)
    person = f1.selectbox("Person", ["Everyone"] + names, key="login_activity_person")
    kinds = f2.multiselect(
        "What",
        list(ACTION_LABELS),
        default=list(ACTION_LABELS),
        format_func=lambda k: ACTION_LABELS[k],
        key="login_activity_kinds",
    )
    full = login_activity.timeline(events, tz_name, person=None if person == "Everyone" else person, kinds=kinds)
    if full.empty:
        st.info("Nothing matches these filters.")
    else:
        if len(full) > TIMELINE_CAP:
            st.caption(f"Showing the newest {TIMELINE_CAP} of {len(full)}. The download has all of them.")
        st.dataframe(full.head(TIMELINE_CAP), use_container_width=True, hide_index=True)
        st.download_button(
            "Download these rows (CSV)",
            full.to_csv(index=False).encode("utf-8"),
            file_name="sign-in-activity.csv",
            mime="text/csv",
            key="login_activity_download",
        )
