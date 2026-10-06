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

from lib import agent_auth, agent_dashboard, ui

st.set_page_config(page_title="My Dashboard — Ticket QA Sampler", page_icon=ui.LOGO_URL, layout="wide")
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

agent_dashboard.render(agent)

st.divider()
agent_auth.render_change_password()
