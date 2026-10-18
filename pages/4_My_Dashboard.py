"""My Dashboard — each agent's own read-only view of their QA evaluations.

Sign-in here is lib.agent_auth, not lib.auth (the reviewer gate) — an agent
signs in with their name and a password a reviewer set for them (QA Log →
Manage agents → "Set/reset agent password"). Nothing on this page writes to
qa_entries; it only reads the signed-in agent's own rows.

The actual summary metrics / score trend / category breakdown / audit list
rendering lives in lib/agent_dashboard.py, shared with the Team Lead
Dashboard's drill-down into one of its agents — this page just owns the
agent's own sign-in, sign-out, and "change my password" controls around it.
"""

import streamlit as st

from lib import activity, agent_auth, agent_dashboard, auth, db, ui
from lib.constants import VIEW_AS_AGENT_REVIEWERS

st.set_page_config(page_title="My Dashboard — ZEVO Quality Evaluation", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

# This page is meant to be opened through app.py (which decides what the sidebar
# shows). On the rare cold start where Streamlit runs this file directly from its
# address, app.py never ran and the sidebar would list every page, so hide it.
if not st.session_state.get("app_entry_ran"):
    st.markdown(
        "<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] {display: none;}</style>",
        unsafe_allow_html=True,
    )

ui.page_heading("My Dashboard")

# ---------- View as agent (reviewers only) ----------
# Weng and Kristine can open any agent's dashboard exactly as the agent sees it,
# without their password. Read-only: no sign-off, no question or dispute, no
# sign out or password change, and nothing is written except the activity log
# (recorded under the agent, marked as the reviewer's, like View as team lead).
ss = st.session_state
viewing_as = None
if auth.current_reviewer() in VIEW_AS_AGENT_REVIEWERS:
    roster = sorted(
        [a for a in db.list_agents() if a.get("name")], key=lambda a: a["name"].lower()
    )
    NOT_VIEWING = "Not viewing as anyone"

    def _switched_agent() -> None:
        chosen = next((a for a in roster if a["name"] == ss.get("agent_view_as_name")), None)
        if chosen:
            db.record_login("agent", chosen["id"], chosen["name"], by_reviewer=auth.current_reviewer(), kind="view_as")

    with st.container(border=True):
        st.markdown("**View as agent**")
        st.caption(
            "For Weng and Kristine only. See exactly what an agent sees, without their password. "
            "Read-only: nothing can be signed, submitted or changed from here."
        )
        picked = st.selectbox(
            "Agent",
            [NOT_VIEWING] + [a["name"] for a in roster],
            key="agent_view_as_name",
            on_change=_switched_agent,
        )
    viewing_as = next((a for a in roster if a["name"] == picked), None)
else:
    ss.pop("agent_view_as_name", None)

activity.set_view_as_agent(viewing_as)
activity.page_view("My Dashboard", role="agent")

if viewing_as:
    st.info(f"You are viewing as **{viewing_as['name']}**. This is a read-only view for reviewers.")
    agent_dashboard.render(
        {"id": viewing_as["id"], "name": viewing_as["name"]},
        show_dispute_form=False,
        period_key="agent_view_as",
        preview_sign_off=True,
    )
    st.stop()

if not agent_auth.is_signed_in():
    st.caption("Sign in to see your own QA evaluations — your scores, how they're trending, and reviewer feedback.")
    left, mid, right = st.columns([1, 2, 1])
    with mid:
        with st.container(border=True):
            agent_auth.render_sign_in()
    st.stop()

agent = agent_auth.current_agent()

top_l, top_r = st.columns([3, 1])
with top_l:
    st.caption(f"Viewing your evaluations, **{agent['name']}**.")
with top_r:
    agent_auth.render_sign_out()

agent_dashboard.render(agent, can_sign_off=True)

st.divider()
agent_auth.render_change_password()
