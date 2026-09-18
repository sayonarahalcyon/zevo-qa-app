"""Ticket QA Sampler — entrypoint / page router.

The actual "Quick Sample" page lives in pages/0_Home.py; this file just
declares the pages and their sidebar titles (via st.navigation) so the
nav labels aren't tied to file names. See README.md for setup, and
sql/schema.sql for the Supabase tables this app expects.
"""

import streamlit as st

home = st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True)
weekly = st.Page("pages/1_Weekly_QA_Batch.py", title="Weekly QA Batch", icon="📅")
qa_log = st.Page("pages/2_QA_Log.py", title="QA Log", icon="📋")
historical = st.Page("pages/3_Historical_Log.py", title="Historical Log", icon="🗄️")
my_dashboard = st.Page("pages/4_My_Dashboard.py", title="My Dashboard", icon="🙋")
questions_disputes = st.Page("pages/5_Questions_Disputes.py", title="Questions & Disputes", icon="❓")

pg = st.navigation([home, weekly, qa_log, questions_disputes, historical, my_dashboard])
pg.run()
