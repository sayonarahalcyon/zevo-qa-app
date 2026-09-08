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

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background-color: rgba(151, 166, 195, 0.08);
        border: 1px solid rgba(151, 166, 195, 0.2);
        border-radius: 10px;
        padding: 14px 18px 12px 18px;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem;
        opacity: 0.85;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- hero ----------
st.title("🎫 ZEVO Quality Evaluation")
st.caption("Random sampling and scoring of closed Intercom conversations against ZEVO Support's QA Rubric.")

st.write("")

# ---------- stats ----------
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
    st.info("No QA audits logged yet. Sign in on the right and head to Weekly QA Batch to pull your first ticket.")

st.write("")
st.write("")

# ---------- get started ----------
jump_col, auth_col = st.columns([2, 1], gap="large")

with jump_col:
    with st.container(border=True):
        st.subheader("Jump to")
        if auth.is_signed_in():
            st.caption(f"Signed in as **{auth.current_reviewer()}** — head to Weekly QA Batch to pull a ticket.")
        else:
            st.caption("Open to everyone to browse. Sign in on the right to pull and score a ticket.")

        st.write("")
        l1, l2, l3 = st.columns(3)
        l1.page_link("pages/1_Weekly_QA_Batch.py", label="📅 Weekly QA Batch", use_container_width=True)
        l2.page_link("pages/2_QA_Log.py", label="📋 QA Log", use_container_width=True)
        l3.page_link("pages/3_Historical_Log.py", label="🗄️ Historical Log", use_container_width=True)

with auth_col:
    with st.container(border=True):
        auth.render_auth(st)
