"""Ticket QA Sampler — Home (landing dashboard).

Pulling and scoring a ticket happens on the Weekly QA Batch page (both the
weekly batch pull and the Quick Sample single-random-ticket tool live there,
right below the sign-in widget) — Home stays a pure landing page with a
snapshot of QA activity, sign-in, and links to the other pages. Home has no
sidebar content of its own; the page nav is all that shows there.
"""

from datetime import date, timedelta

import streamlit as st

from lib import auth, db

st.set_page_config(page_title="ZEVO Quality Evaluation", page_icon="🎫", layout="wide")

# ---------- main stage ----------
st.title("🎫 ZEVO Quality Evaluation")
st.caption("Random sampling and scoring of closed Intercom conversations against ZEVO Support's QA Rubric.")

entries = db.list_qa_entries()
total = len(entries)
if total:
    score_sum = sum(e.get("total_score") or 0 for e in entries)
    avg_score = round(score_sum / total, 1)
    pass_count = sum(1 for e in entries if e.get("result") == "PASS")
    pass_rate = round(pass_count / total * 100, 1)
    week_start_iso = (date.today() - timedelta(days=7)).isoformat()
    this_week = sum(1 for e in entries if (e.get("qa_date") or "") >= week_start_iso)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Audits Logged", total)
    c2.metric("Pass Rate", f"{pass_rate}%")
    c3.metric("Avg Score", avg_score)
    c4.metric("Logged This Week", this_week)
else:
    st.info("No QA audits logged yet. Sign in below and head to Weekly QA Batch to pull your first ticket.")

st.divider()

if auth.is_signed_in():
    st.success(f"Signed in as {auth.current_reviewer()} — head to **Weekly QA Batch** to pull a ticket.")
else:
    st.info(
        "Sign in below to pull and score a ticket — signing in takes you straight to Weekly QA Batch. "
        "Browsing the Weekly QA Batch, QA Log, and Historical Log pages doesn't require signing in."
    )

st.divider()

jump_col, auth_col = st.columns([2, 1])

with jump_col:
    st.subheader("Jump to")
    l1, l2, l3 = st.columns(3)
    l1.page_link("pages/1_Weekly_QA_Batch.py", label="📅 Weekly QA Batch")
    l2.page_link("pages/2_QA_Log.py", label="📋 QA Log")
    l3.page_link("pages/3_Historical_Log.py", label="🗄️ Historical Log")

with auth_col:
    auth.render_auth(auth_col.container(border=True))
