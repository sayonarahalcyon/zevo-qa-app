"""Ticket QA Sampler — entrypoint / page router.

The actual "Quick Sample" page lives in pages/0_Home.py; this file just
declares the pages and their sidebar titles (via st.navigation) so the
nav labels aren't tied to file names. See README.md for setup, and
sql/schema.sql for the Supabase tables this app expects.
"""

from urllib.parse import urlparse

import streamlit as st

from lib import agent_auth, auth, team_lead_auth

home = st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True)
weekly = st.Page("pages/1_Weekly_QA_Batch.py", title="Weekly QA Batch", icon="📅")
qa_log = st.Page("pages/2_QA_Log.py", title="QA Log", icon="📋")
historical = st.Page("pages/3_Historical_Log.py", title="Historical Log", icon="🗄️")
my_dashboard = st.Page("pages/4_My_Dashboard.py", title="My Dashboard", icon="🙋")
questions_disputes = st.Page("pages/5_Questions_Disputes.py", title="Questions & Disputes", icon="❓")
team_lead_dashboard = st.Page("pages/6_Team_Lead_Dashboard.py", title="Team Lead Dashboard", icon="🧑‍💼")

TEAM_LEAD_LINK_PATH = "Team_Lead_Dashboard"  # the dashboard's own address, shared with team leads
AGENT_LINK_PATH = "My_Dashboard"  # My Dashboard's own address, shared with agents


def opened_from_link(path_name: str) -> bool:
    """True for the whole session if it began at that page's own address
    (e.g. .../Team_Lead_Dashboard or .../My_Dashboard). The address is read once,
    on the first run, because the address in the browser changes as the page
    changes. If this Streamlit version can't report the address, this is simply
    False and the sidebar behaves as before."""
    ss = st.session_state
    if "opened_path" not in ss:
        path = ""
        try:
            path = urlparse(st.context.url or "").path
        except Exception:
            pass
        ss["opened_path"] = path.rstrip("/").split("/")[-1]
    return ss["opened_path"] == path_name


def dashboard_only_pages(file: str, title: str, icon: str, url_path: str) -> list:
    """Keep one dashboard at its own address, with the default page ("/") just
    forwarding to it, so the sidebar can be hidden completely."""
    dashboard = st.Page(file, title=title, icon=icon, url_path=url_path)

    def forward_to_dashboard():
        st.switch_page(dashboard)

    return [st.Page(forward_to_dashboard, title=title, url_path="start", default=True), dashboard]


# Team leads and agents each get a dashboard-only app, in two cases:
#   1. They opened their dashboard's own link (.../Team_Lead_Dashboard or
#      .../My_Dashboard): they see only that page, signed in or not, and signing
#      out keeps it that way.
#   2. They signed in to their dashboard from the normal app: from then on the
#      sidebar shows only their dashboard until they sign out.
# The other pages simply aren't registered for them, so they can't be opened
# from the sidebar. A person who is also signed in as a reviewer (Kristine is
# both) keeps the full list, since the reviewer pages are theirs to use.
st.session_state["app_entry_ran"] = True  # lets the dashboard pages tell they were opened through this file

all_pages = [home, weekly, qa_log, questions_disputes, historical, my_dashboard, team_lead_dashboard]
kwargs = {}

if auth.is_signed_in():
    pages = all_pages
elif opened_from_link(TEAM_LEAD_LINK_PATH):
    pages = dashboard_only_pages(
        "pages/6_Team_Lead_Dashboard.py", "Team Lead Dashboard", "🧑‍💼", TEAM_LEAD_LINK_PATH
    )
    kwargs = {"position": "hidden"}
elif opened_from_link(AGENT_LINK_PATH):
    pages = dashboard_only_pages("pages/4_My_Dashboard.py", "My Dashboard", "🙋", AGENT_LINK_PATH)
    kwargs = {"position": "hidden"}
elif team_lead_auth.is_signed_in() or agent_auth.is_signed_in():
    # Whichever of the two is signed in; if someone is signed in to both
    # (a team lead who also handles tickets), they get both dashboards.
    signed_in = []
    if team_lead_auth.is_signed_in():
        signed_in.append(("pages/6_Team_Lead_Dashboard.py", "Team Lead Dashboard", "🧑‍💼"))
    if agent_auth.is_signed_in():
        signed_in.append(("pages/4_My_Dashboard.py", "My Dashboard", "🙋"))
    pages = [st.Page(f, title=t, icon=i, default=(n == 0)) for n, (f, t, i) in enumerate(signed_in)]
else:
    pages = all_pages

try:
    pg = st.navigation(pages, **kwargs)
except TypeError:  # an older Streamlit without position="hidden": fall back to a one-item sidebar
    pg = st.navigation(pages)
pg.run()
