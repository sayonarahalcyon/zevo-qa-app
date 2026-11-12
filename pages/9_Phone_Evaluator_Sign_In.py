"""Phone evaluators' own sign-in page, at .../Phone_Evaluator.

Shared with phone evaluators (e.g. the third-party evaluator) as their link.
Opened from that address, the app shows only this page, with no sidebar.
After signing in, they land on the Phone Queue, with Calibration as the only
other page (see app.py). Signing out brings them back here.
"""

from __future__ import annotations

import streamlit as st

from lib import evaluator_auth, ui

ui.page_heading("Phone Evaluator Sign-in")
st.caption("ZEVO QA App for phone evaluators. Sign in to open the Phone Queue.")
evaluator_auth.render_sign_in()
