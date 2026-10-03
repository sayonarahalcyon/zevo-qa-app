"""Team Lead Dashboard — a team lead's rollup of, and drill-down into, the
agents assigned to them.

Sign-in here is lib.team_lead_auth — a third, separate gate from lib.auth
(the 3 reviewers) and lib.agent_auth (one agent's My Dashboard). Nothing on
this page writes to qa_entries or agents; it only reads. Which agents
"belong" to a team lead is agents.team_lead_id, set from QA Log → Manage
agents → "Assign a team lead" — that assignment is the whole source of truth
for both the rollup below and who can be drilled into.
"""

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


def _entries_for(agent: dict) -> list[dict]:
    return [
        e
        for e in metric_entries
        if e.get("agent_id") == agent["id"] or (e.get("agent_name") or "").lower() == (agent.get("name") or "").lower()
    ]


team_entries = [
    e
    for e in metric_entries
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

# Company-wide figures, for the "vs. company" deltas below — same
# metric_entries (all non-test audits, every agent) and the same
# avg-score/pass-rate math QA Log's own dashboard uses, so the comparison
# is apples-to-apples with what a reviewer sees there.
company_avg = round(sum(e.get("total_score") or 0 for e in metric_entries) / len(metric_entries), 1) if metric_entries else None
company_pass_rate = (
    round(sum(1 for e in metric_entries if e.get("result") == "PASS") / len(metric_entries) * 100, 1)
    if metric_entries
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
)
c4.metric(
    "Team Pass Rate",
    f"{team_pass_rate}%" if team_pass_rate is not None else "—",
    delta=f"{pass_rate_delta:+.1f}% vs. company" if pass_rate_delta is not None else None,
)

b1, b2, b3 = st.columns(3)
b1.metric("Pass", team_counts["PASS"])
b2.metric("Coaching", team_counts["COACHING"])
b3.metric("Fail", team_counts["FAIL"] + team_counts["AUTO FAIL"])

st.divider()

# ---------- per-agent rollup ----------
st.subheader("Your team")
st.caption("Click View to open an agent's own My Dashboard view — scores, trend, and category breakdown.")

today = date.today()
week_monday = today - timedelta(days=today.weekday())
week_sunday = week_monday + timedelta(days=6)

row_widths = [2, 1, 1, 1, 1.3, 1]
h1, h2, h3, h4, h5, h6 = st.columns(row_widths)
for h, label in zip((h1, h2, h3, h4, h5), ("Agent", "Audits", "Avg Score", "Status", "This week (of 3)")):
    h.markdown(f"**{label}**")

for a in my_agents:
    mine = _entries_for(a)
    avg = round(sum(e.get("total_score") or 0 for e in mine) / len(mine), 1) if mine else None
    week_count = sum(
        1 for e in mine if e.get("qa_date") and week_monday.isoformat() <= e["qa_date"] <= week_sunday.isoformat()
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
