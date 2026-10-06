"""Team Lead Dashboard — a team lead's rollup of, and drill-down into, the
agents assigned to them.

Sign-in here is lib.team_lead_auth — a third, separate gate from lib.auth
(the 3 reviewers) and lib.agent_auth (one agent's My Dashboard). Nothing on
this page writes to qa_entries or agents; it only reads. Which agents
"belong" to a team lead is agents.team_lead_id, set from QA Log → Manage
agents → "Assign a team lead" — that assignment is the whole source of truth
for both the rollup below and who can be drilled into.
"""

from datetime import date

import streamlit as st

from lib import agent_dashboard, auth, db, period_picker, team_lead_auth, ui, weeks
from lib.constants import VIEW_AS_TEAM_LEAD_REVIEWERS

st.set_page_config(page_title="Team Lead Dashboard — ZEVO Quality Evaluation", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

# This page is meant to be opened through app.py (which decides what the sidebar
# shows). On the rare cold start where Streamlit runs this file directly from its
# address, app.py never ran and the sidebar would list every page, so hide it.
if not st.session_state.get("app_entry_ran"):
    st.markdown(
        "<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] {display: none;}</style>",
        unsafe_allow_html=True,
    )

ui.page_heading("Team Lead Dashboard")

ss = st.session_state
ss.setdefault("tl_open_agent_id", None)

# ---------- "View as team lead" (Weng and Kristine only) ----------
# A signed-in reviewer on the allowed list can open this page as any team lead
# without their password. It is strictly read-only: no dispute can be filed on
# an agent's behalf from here, no password is shown or changed, and nothing is
# written. The selector is drawn on every run (including the drill-down) so its
# state is never dropped.
viewing_as = None
if auth.current_reviewer() in VIEW_AS_TEAM_LEAD_REVIEWERS:
    leads = sorted(db.list_team_leads(), key=lambda t: (t.get("name") or "").lower())
    lead_names = [t["name"] for t in leads if t.get("name")]
    NOT_VIEWING = "Not viewing as anyone"

    def _switched_team_lead() -> None:
        ss["tl_open_agent_id"] = None  # a different team lead's agent list: start from their rollup

    with st.container(border=True):
        st.markdown("**View as team lead**")
        st.caption(
            "For reviewers only. See exactly what a team lead sees, without their password. "
            "Read-only: nothing can be changed or submitted from here."
        )
        picked = st.selectbox(
            "Team lead",
            [NOT_VIEWING] + lead_names,
            key="tl_view_as_name",
            on_change=_switched_team_lead,
        )
    viewing_as = next((t for t in leads if t.get("name") == picked), None)
else:
    ss.pop("tl_view_as_name", None)

if viewing_as:
    lead = {"id": viewing_as["id"], "name": viewing_as["name"]}
    st.info(f"You are viewing as **{lead['name']}**. This is a read-only view for reviewers.")
elif not team_lead_auth.is_signed_in():
    st.caption("Sign in to see a rollup of your team, and drill into any one agent's own dashboard.")
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        with st.container(border=True):
            team_lead_auth.render_sign_in()
    st.stop()
else:
    lead = team_lead_auth.current_team_lead()

# The drill-down below st.stop()s before the period pickers are drawn, and
# Streamlit drops a widget's state on any run where it isn't drawn — so carry
# both the rollup's picker and the per-agent picker across (lib/period_picker).
period_picker.keep_state("tl_period", "agent_dash")

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
    agent_dashboard.render(agent, submitted_by=lead["name"], show_dispute_form=not viewing_as)
    st.stop()

# ---------- team rollup ----------
top_l, top_r = st.columns([3, 1])
with top_l:
    if viewing_as:
        st.caption(f"Viewing the team of **{lead['name']}**.")
    else:
        st.caption(f"Viewing your team, **{lead['name']}**.")
with top_r:
    if not viewing_as:
        team_lead_auth.render_sign_out()

all_agents = db.list_agents()
my_agents = sorted(
    [a for a in all_agents if a.get("team_lead_id") == lead["id"]],
    key=lambda a: (a.get("name") or "").lower(),
)

if not my_agents:
    if viewing_as:
        st.info(f"No agents are assigned to {lead['name']} yet. Assign some on the QA Log page (Manage agents).")
    else:
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

# ---------- period picker ----------
# Every figure below (headline tiles, Pass/Coaching/Fail, the vs.-company
# comparison, and the per-agent Audits/Avg Score/Status columns) is computed
# from the entries inside the chosen window. "To date" is the old all-time view.
period = period_picker.pick(metric_entries, key_prefix="tl_period")
period_phrase = period.phrase
period_entries = period.filter(metric_entries)


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
    week_count = sum(1 for e in _entries_for(a, metric_entries) if weeks.in_week(e.get("qa_date"), today))
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

if not viewing_as:
    st.divider()
    team_lead_auth.render_change_password()
