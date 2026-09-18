"""Questions & Disputes — reviewer inbox for agent-submitted questions and
disputes, submitted inline per-audit on My Dashboard (lib/disputes.py).

Its own page (split out from QA Log on 2026-09-18) so it's easy to find
without competing for space with the rest of QA Log. Visible to any
signed-in reviewer, not just Weng, since responding to these is routine
reviewer work — same gate as QA Log (lib.auth).
"""

import streamlit as st

from lib import auth, disputes, ui

st.set_page_config(page_title="Questions & Disputes — Ticket QA Sampler", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

if not auth.is_signed_in():
    st.title("Questions & Disputes")
    st.warning("Sign in to view questions and disputes. Head to Home and sign in as one of the three reviewers.")
    st.page_link("pages/0_Home.py", label="🏠 Go to Home to sign in", use_container_width=False)
    st.stop()

st.title("Questions & Disputes")
st.caption("Submitted by agents from My Dashboard, on the audit itself.")

disputes.render_reviewer_panel()
