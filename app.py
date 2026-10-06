"""Ticket QA Sampler — entrypoint / page router.

The actual "Quick Sample" page lives in pages/0_Home.py; this file just
declares the pages and their sidebar titles (via st.navigation) so the
nav labels aren't tied to file names. See README.md for setup, and
sql/schema.sql for the Supabase tables this app expects.
"""

from urllib.parse import urlparse

import streamlit as st

from lib import auth, team_lead_auth

home = st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True)
weekly = st.Page("pages/1_Weekly_QA_Batch.py", title="Weekly QA Batch", icon="📅")
qa_log = st.Page("pages/2_QA_Log.py", title="QA Log", icon="📋")
historical = st.Page("pages/3_Historical_Log.py", title="Historical Log", icon="🗄️")
my_dashboard = st.Page("pages/4_My_Dashboard.py", title="My Dashboard", icon="🙋")
questions_disputes = st.Page("pages/5_Questions_Disputes.py", title="Questions & Disputes", icon="❓")
team_lead_dashboard = st.Page("pages/6_Team_Lead_Dashboard.py", title="Team Lead Dashboard", icon="🧑‍💼")

TEAM_LEAD_LINK_PATH = "Team_Lead_Dashboard"  # the dashboard's own address, shared with team leads


def opened_from_team_lead_link() -> bool:
    """True for the whole session if it began at the Team Lead Dashboard's own
    address (.../Team_Lead_Dashboard). Read once, on the first run, because the
    address in the browser changes as the page changes. If this Streamlit
    version can't report the address, this is simply False and the sidebar
    behaves as before."""
    ss = st.session_state
    if "opened_from_tl_link" not in ss:
        path = ""
        try:
            path = urlparse(st.context.url or "").path
        except Exception:
            pass
        ss["opened_from_tl_link"] = path.rstrip("/").split("/")[-1] == TEAM_LEAD_LINK_PATH
    return ss["opened_from_tl_link"]


# Team leads get a dashboard-only app, in two cases:
#   1. They opened the dashboard's own link (.../Team_Lead_Dashboard): they see
#      only that page, signed in or not, and signing out keeps it that way.
#   2. They signed in to the dashboard from the normal app: from then on the
#      sidebar shows only the dashboard until they sign out.
# The other pages simply aren't registered for them, so they can't be opened
# from the sidebar. A person who is also signed in as a reviewer (Kristine is
# both) keeps the full list, since the reviewer pages are theirs to use.
st.session_state["app_entry_ran"] = True  # lets the dashboard page tell it was opened through this file

all_pages = [home, weekly, qa_log, questions_disputes, historical, my_dashboard, team_lead_dashboard]
kwargs = {}

if auth.is_signed_in():
    pages = all_pages
elif opened_from_team_lead_link():
    # Keep the dashboard at its own address and hide the sidebar completely.
    # The default page ("/") just forwards to it.
    dashboard_only = st.Page(
        "pages/6_Team_Lead_Dashboard.py", title="Team Lead Dashboard", icon="🧑‍💼", url_path=TEAM_LEAD_LINK_PATH
    )

    def forward_to_dashboard():
        st.switch_page(dashboard_only)

    pages = [st.Page(forward_to_dashboard, title="Team Lead Dashboard", url_path="start", default=True), dashboard_only]
    kwargs = {"position": "hidden"}
elif team_lead_auth.is_signed_in():
    pages = [st.Page("pages/6_Team_Lead_Dashboard.py", title="Team Lead Dashboard", icon="🧑‍💼", default=True)]
else:
    pages = all_pages

try:
    pg = st.navigation(pages, **kwargs)
except TypeError:  # an older Streamlit without position="hidden": fall back to a one-item sidebar
    pg = st.navigation(pages)
pg.run()
