"""Team Lead Dashboard — a team lead's rollup of, and drill-down into, the
agents assigned to them.

Sign-in here is lib.team_lead_auth — a third, separate gate from lib.auth
(the 3 reviewers) and lib.agent_auth (one agent's My Dashboard). Nothing on
this page writes to qa_entries or agents; it only reads. Which agents
"belong" to a team lead is agents.team_lead_id, set from QA Log → Manage
agents → "Assign a team lead" — that assignment is the whole source of truth
for both the rollup below and who can be drilled into.
"""

import calendar
from datetime import date, timedelta

import streamlit as st

from lib import agent_dashboard, db, team_lead_auth, ui

st.set_page_config(page_title="Team Lead Dashboard — Ticket QA Sampler", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

ui.page_heading("Team Lead Dashboard")

if not team_lead_auth.is_signed_in():
    st.caption("Sign in to see a rollup of your team, and drill into any one agent's own dashboard.")
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        with st.container(border=True):
            team_lead_auth.render_sign_in()
    st.stop()

lead = team_lead_auth.current_team_lead()
ss = st.session_state
ss.setdefault("tl_open_agent_id", None)

# Streamlit drops a widget's state on any run where it isn't rendered, and the
# drill-down below st.stop()s before the period picker is drawn. Re-assigning
# the values here keeps the team lead's chosen period when they come back from
# viewing one agent, instead of snapping back to the default.
for _k in ("tl_period_mode", "tl_period_week", "tl_period_month"):
    if _k in ss:
        ss[_k] = ss[_k]

# ---------- drill-down into one agent ----------
if ss.get("tl_open_agent_id"):
    agents = db.list_agents()
    agent = next((a for a in agents if a["id"] == ss["tl_open_agent_id"]), None)
    if st.button("← Back to team rollup"):
        ss["tl_open_agent_id"] = None
        st.rerun()
    if not agent or agent.get("team_lead_id") != lead["id"]:
        st.warning("That agent is no longer assigned to your team.")
        st.stop()
    st.subheader(agent["name"])
    agent_dashboard.render(agent, submitted_by=lead["name"])
    st.stop()

# ---------- team rollup ----------
top_l, top_r = st.columns([3, 1])
with top_l:
    st.caption(f"Viewing your team, **{lead['name']}**.")
with top_r:
    team_lead_auth.render_sign_out()

all_agents = db.list_agents()
my_agents = sorted(
    [a for a in all_agents if a.get("team_lead_id") == lead["id"]],
    key=lambda a: (a.get("name") or "").lower(),
)

if not my_agents:
    st.info("No agents are assigned to you yet — ask a reviewer to assign some on the QA Log page (Manage agents).")
    st.divider()
    team_lead_auth.render_change_password()
    st.stop()

entries = db.list_qa_entries()
# Same rule as every other dashboard in the app: test audits never count
# toward the team or per-agent numbers below.
metric_entries = [e for e in entries if not e.get("is_test")]

my_agent_ids = {a["id"] for a in my_agents}
my_agent_names = {(a.get("name") or "").lower() for a in my_agents}


today = date.today()
week_monday = today - timedelta(days=today.weekday())
week_sunday = week_monday + timedelta(days=6)


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _fmt_day(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    label = f"{_fmt_day(monday)} – {_fmt_day(sunday)}, {sunday.year}"
    return f"{label} (this week)" if monday == week_monday else label


def _month_label(first: date) -> str:
    label = first.strftime("%B %Y")
    return f"{label} (this month)" if (first.year, first.month) == (today.year, today.month) else label


# ---------- period picker ----------
# Every figure below (headline tiles, Pass/Coaching/Fail, the vs.-company
# comparison, and the per-agent Audits/Avg Score/Status columns) is computed
# from the entries inside the chosen window. "To date" is the old all-time view.
entry_dates = [d for d in (_parse_date(e.get("qa_date")) for e in metric_entries) if d is not None]
earliest = min(entry_dates) if entry_dates else today

week_options: list[date] = []
_cursor = week_monday
while _cursor >= earliest - timedelta(days=earliest.weekday()):
    week_options.append(_cursor)
    _cursor -= timedelta(days=7)

month_options: list[date] = []
_y, _m = today.year, today.month
while (_y, _m) >= (earliest.year, earliest.month):
    month_options.append(date(_y, _m, 1))
    _m -= 1
    if _m == 0:
        _y, _m = _y - 1, 12

PERIOD_MODES = ["Weekly", "Monthly", "To date"]
ss.setdefault("tl_period_mode", "Monthly")  # default view; set via state so the key can also be restored after a drill-down
pick_l, pick_r = st.columns([2, 3])
with pick_l:
    period_mode = st.radio("Show numbers for", PERIOD_MODES, horizontal=True, key="tl_period_mode")
with pick_r:
    if period_mode == "Weekly":
        week_start = st.selectbox("Week", week_options, format_func=_week_label, key="tl_period_week")
        period_start, period_end = week_start, week_start + timedelta(days=6)
        period_label = f"the week of {_week_label(week_start).replace(' (this week)', '')}"
    elif period_mode == "Monthly":
        month_start = st.selectbox("Month", month_options, format_func=_month_label, key="tl_period_month")
        period_start = month_start
        period_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
        period_label = month_start.strftime("%B %Y")
    else:
        period_start = period_end = None
        period_label = "to date"

if period_start is None:
    period_phrase = "all-time"
    period_entries = metric_entries
else:
    period_phrase = f"in {period_label}"
    period_entries = [
        e
        for e in metric_entries
        if (d := _parse_date(e.get("qa_date"))) is not None and period_start <= d <= period_end
    ]
    st.caption(f"Showing {period_start.isoformat()} to {period_end.isoformat()}.")


def _entries_for(agent: dict, pool: list[dict]) -> list[dict]:
    return [
        e
        for e in pool
        if e.get("agent_id") == agent["id"] or (e.get("agent_name") or "").lower() == (agent.get("name") or "").lower()
    ]


team_entries = [
    e
    for e in period_entries
    if e.get("agent_id") in my_agent_ids or (e.get("agent_name") or "").lower() in my_agent_names
]

# ---------- team-wide summary ----------
team_avg = round(sum(e.get("total_score") or 0 for e in team_entries) / len(team_entries), 1) if team_entries else None
team_pass_rate = (
    round(sum(1 for e in team_entries if e.get("result") == "PASS") / len(team_entries) * 100, 1)
    if team_entries
    else None
)

team_counts = {"PASS": 0, "COACHING": 0, "FAIL": 0, "AUTO FAIL": 0}
for e in team_entries:
    if e.get("result") in team_counts:
        team_counts[e["result"]] += 1


# Company-wide figures, for the "vs. company" deltas below — the same
# non-test audits (every agent) and the same avg-score/pass-rate math QA
# Log's own dashboard uses, limited to the same period as the team numbers
# so the comparison is apples-to-apples.
company_avg = (
    round(sum(e.get("total_score") or 0 for e in period_entries) / len(period_entries), 1) if period_entries else None
)
company_pass_rate = (
    round(sum(1 for e in period_entries if e.get("result") == "PASS") / len(period_entries) * 100, 1)
    if period_entries
    else None
)
avg_delta = round(team_avg - company_avg, 1) if (team_avg is not None and company_avg is not None) else None
pass_rate_delta = (
    round(team_pass_rate - company_pass_rate, 1) if (team_pass_rate is not None and company_pass_rate is not None) else None
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Agents on your team", len(my_agents))
c2.metric("Total Evaluations", len(team_entries))
c3.metric(
    "Team Avg Score",
    team_avg if team_avg is not None else "—",
    delta=f"{avg_delta:+.1f} vs. company" if avg_delta is not None else None,
    help=(
        f"The average total score (out of 100) across the {len(team_entries)} non-test evaluations "
        f"logged for your team {period_phrase}. The note underneath compares this to the same "
        "average across every agent, every team, company-wide, for the same period."
    ),
)
c4.metric(
    "Team Pass Rate",
    f"{team_pass_rate}%" if team_pass_rate is not None else "—",
    delta=f"{pass_rate_delta:+.1f}% vs. company" if pass_rate_delta is not None else None,
    help=(
        f"The share of your team's {len(team_entries)} non-test evaluations {period_phrase} that scored "
        "PASS (85 or higher out of 100). The note underneath compares this to the same pass rate "
        "across every agent, every team, company-wide, for the same period."
    ),
)

b1, b2, b3 = st.columns(3)
b1.metric(
    "Pass",
    team_counts["PASS"],
    help=f"Evaluations that scored 85 or higher out of 100, counted {period_phrase}.",
)
b2.metric(
    "Coaching",
    team_counts["COACHING"],
    help=f"Evaluations that scored 70-84 out of 100, counted {period_phrase}.",
)
b3.metric(
    "Fail",
    team_counts["FAIL"] + team_counts["AUTO FAIL"],
    help=(
        "Evaluations that scored below 70 out of 100, or hit an AUTO FAIL (any critical error flagged), "
        f"counted {period_phrase}."
    ),
)

st.divider()

# ---------- per-agent rollup ----------
st.subheader("Your team")
st.caption("Click View to open an agent's own My Dashboard view — scores, trend, and category breakdown.")

row_widths = [2, 1, 1, 1, 1.3, 1]
h1, h2, h3, h4, h5, h6 = st.columns(row_widths)
for h, label in zip((h1, h2, h3, h4, h5), ("Agent", "Audits", "Avg Score", "Status", "This week (of 3)")):
    h.markdown(f"**{label}**")

for a in my_agents:
    # Audits / Avg Score / Status follow the period picked above; the weekly
    # quota column is always about the current calendar week, whatever period
    # is on screen, so it reads from the full set of entries.
    mine = _entries_for(a, period_entries)
    avg = round(sum(e.get("total_score") or 0 for e in mine) / len(mine), 1) if mine else None
    week_count = sum(
        1
        for e in _entries_for(a, metric_entries)
        if e.get("qa_date") and week_monday.isoformat() <= e["qa_date"] <= week_sunday.isoformat()
    )
    status = ("🟢 Pass" if (avg or 0) >= 85 else "🔴 Fail") if avg is not None else "—"

    r1, r2, r3, r4, r5, r6 = st.columns(row_widths)
    r1.write(a["name"])
    r2.write(len(mine))
    r3.write(avg if avg is not None else "—")
    r4.write(status)
    r5.write(f"{week_count} / 3")
    if r6.button("View", key=f"tl_view_agent_{a['id']}", use_container_width=True):
        ss["tl_open_agent_id"] = a["id"]
        st.rerun()

st.divider()
team_lead_auth.render_change_password()
