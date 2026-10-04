"""Weekly / Monthly / To date picker shared by the Team Lead Dashboard rollup
and the per-agent dashboard (My Dashboard, and the team lead's drill-down into
one agent).

pick() draws a radio (Weekly / Monthly / To date) and, for Weekly or Monthly, a
dropdown of calendar weeks (Mon-Sun) or months — newest first, reaching back to
the earliest audit date it was given, and always including the current week /
month even if nothing has been logged in it yet. It returns a Period the caller
uses to filter its own entries; the picker never touches the database itself.

Widget keys are f"{key_prefix}_mode" / "_week" / "_month". Streamlit drops a
widget's state on any run where it isn't drawn, so a page that st.stop()s
before drawing the picker (the Team Lead Dashboard's drill-down) calls
keep_state() near the top of the script to carry the choice across.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import streamlit as st

PERIOD_MODES = ["Weekly", "Monthly", "To date"]


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _fmt_day(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _week_range_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"{_fmt_day(monday)} – {_fmt_day(sunday)}, {sunday.year}"


@dataclass(frozen=True)
class Period:
    mode: str
    start: date | None  # None for "To date"
    end: date | None
    label: str  # "October 2026", "Sep 28 – Oct 4, 2026", or "to date"
    phrase: str  # for sentences: "all-time", "in October 2026", "in the week of Sep 28 – Oct 4, 2026"

    @property
    def is_all_time(self) -> bool:
        return self.start is None

    def contains(self, qa_date) -> bool:
        if self.is_all_time:
            return True
        d = _parse_date(qa_date)
        return d is not None and self.start <= d <= self.end

    def filter(self, entries: list[dict]) -> list[dict]:
        """Entries inside the period. "To date" keeps everything, including an
        audit with no qa_date; Weekly/Monthly drop undated ones."""
        if self.is_all_time:
            return list(entries)
        return [e for e in entries if self.contains(e.get("qa_date"))]


def keep_state(*key_prefixes: str) -> None:
    """Re-assign any picker keys that exist so they survive a run where the
    picker isn't drawn (the standard persist-widget-state idiom)."""
    for prefix in key_prefixes:
        for suffix in ("mode", "week", "month"):
            k = f"{prefix}_{suffix}"
            if k in st.session_state:
                st.session_state[k] = st.session_state[k]


def pick(
    entries: list[dict],
    *,
    key_prefix: str,
    default_mode: str = "Monthly",
    today: date | None = None,
) -> Period:
    today = today or date.today()
    week_monday = today - timedelta(days=today.weekday())

    dates = [d for d in (_parse_date(e.get("qa_date")) for e in entries) if d is not None]
    earliest = min(dates) if dates else today

    week_options: list[date] = []
    cursor = week_monday
    while cursor >= earliest - timedelta(days=earliest.weekday()):
        week_options.append(cursor)
        cursor -= timedelta(days=7)

    month_options: list[date] = []
    y, m = today.year, today.month
    while (y, m) >= (earliest.year, earliest.month):
        month_options.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12

    def week_label(monday: date) -> str:
        label = _week_range_label(monday)
        return f"{label} (this week)" if monday == week_monday else label

    def month_label(first: date) -> str:
        label = first.strftime("%B %Y")
        return f"{label} (this month)" if (first.year, first.month) == (today.year, today.month) else label

    mode_key = f"{key_prefix}_mode"
    # Default via session state (not index=) so the key can also be restored
    # by keep_state() without Streamlit warning about a double-set default.
    st.session_state.setdefault(mode_key, default_mode)

    left, right = st.columns([2, 3])
    with left:
        mode = st.radio("Show numbers for", PERIOD_MODES, horizontal=True, key=mode_key)
    with right:
        if mode == "Weekly":
            monday = st.selectbox("Week", week_options, format_func=week_label, key=f"{key_prefix}_week")
            period = Period(
                "Weekly",
                monday,
                monday + timedelta(days=6),
                _week_range_label(monday),
                f"in the week of {_week_range_label(monday)}",
            )
        elif mode == "Monthly":
            first = st.selectbox("Month", month_options, format_func=month_label, key=f"{key_prefix}_month")
            last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
            period = Period("Monthly", first, last, first.strftime("%B %Y"), f"in {first.strftime('%B %Y')}")
        else:
            period = Period("To date", None, None, "to date", "all-time")

    if not period.is_all_time:
        st.caption(f"Showing {period.start.isoformat()} to {period.end.isoformat()}.")
    return period
