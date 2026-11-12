"""Phone evaluators' own sign-in page, at .../Phone_Evaluator.

Shared with phone evaluators (e.g. the third-party evaluator) as their link.
Opened from that address, the app shows only this page, with no sidebar.
After signing in, they land on the Phone Queue, with Calibration as the only
other page (see app.py). Signing out brings them back here.
"""

from __future__ import annotations

import streamlit as st

from lib import evaluator_auth, ui

# Already signed in (including straight after signing in here): go to the queue.
if evaluator_auth.is_signed_in():
    st.switch_page("pages/7_Phone_Queue.py")

# Right after the app restarts, the very first visitor can get this file run on
# its own (at .../Phone_Evaluator_Sign_In) instead of through app.py, with a
# sidebar listing every page. Hide that sidebar; signing in still works and
# goes to the Phone Queue.
if not st.session_state.get("app_entry_ran"):
    st.markdown(
        "<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] {display: none;}</style>",
        unsafe_allow_html=True,
    )

ui.page_heading("Phone Evaluator Sign-in")
st.caption("ZEVO QA App for phone evaluators. Sign in to open the Phone Queue.")
evaluator_auth.render_sign_in()
