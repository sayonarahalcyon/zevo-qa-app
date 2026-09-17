"""My Dashboard — each agent's own read-only view of their QA evaluations.

Sign-in here is lib.agent_auth, not lib.auth (the reviewer gate) — an agent
signs in with their name and a password a reviewer set for them (QA Log →
Manage agents → "Set/reset agent password"). Nothing on this page writes to
qa_entries; it only reads the signed-in agent's own rows.
"""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from lib import agent_auth, db, ui
from lib.constants import CRITICAL_ERRORS, RUBRIC
from lib.intercom_client import conversation_url
from lib.ui import result_badge_md

st.set_page_config(page_title="My Dashboard — Ticket QA Sampler", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

# Reuses the app's existing accent/status colors (lib/ui.py's --qa-accent /
# --qa-coach / --qa-fail) rather than introducing a new palette, so the
# charts on this page read as the same product as the result pills elsewhere.
_ACCENT = "#14a173"
_COACH = "#d69a34"
_FAIL = "#cf4a5c"
_MUTED = "#5c6f66"

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

entries = [
    e
    for e in db.list_qa_entries()
    if e.get("agent_id") == agent["id"] or (e.get("agent_name") or "").lower() == agent["name"].lower()
]
# Same rule as the QA Log dashboard and Home: test audits never count toward
# an agent's own numbers, though they still show up (marked) in the list below.
real_entries = [e for e in entries if not e.get("is_test")]
test_count = len(entries) - len(real_entries)

if not real_entries:
    st.info("No QA evaluations on file for you yet.")
    st.divider()
    agent_auth.render_change_password()
    st.stop()

# ---------- summary ----------
total = len(real_entries)
score_sum = sum(e.get("total_score") or 0 for e in real_entries)
avg_score = round(score_sum / total, 1)
pass_count = sum(1 for e in real_entries if e.get("result") == "PASS")
pass_rate = round(pass_count / total * 100, 1)

today = date.today()
week_monday = today - timedelta(days=today.weekday())
week_sunday = week_monday + timedelta(days=6)
week_count = sum(
    1
    for e in real_entries
    if e.get("qa_date") and week_monday.isoformat() <= e["qa_date"] <= week_sunday.isoformat()
)

if test_count:
    st.caption(f"🧪 {test_count} test audit{'s' if test_count != 1 else ''} excluded from these numbers.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Evaluations", total)
c2.metric("Avg Score", avg_score)
c3.metric("Pass Rate", f"{pass_rate}%")
c4.metric("This Week (of 3)", f"{week_count} / 3")

st.divider()

# ---------- score trend ----------
st.subheader("Score trend")
trend_rows = sorted(
    (
        {"Date": e["qa_date"], "Score": e.get("total_score") or 0}
        for e in real_entries
        if e.get("qa_date")
    ),
    key=lambda r: r["Date"],
)

if len(trend_rows) >= 2:
    trend_df = pd.DataFrame(trend_rows)
    trend_df["Date"] = pd.to_datetime(trend_df["Date"])

    line = (
        alt.Chart(trend_df)
        .mark_line(color=_ACCENT, strokeWidth=2, point=alt.OverlayMarkDef(size=50, color=_ACCENT))
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("Score:Q", title="Total score", scale=alt.Scale(domain=[0, 100])),
            tooltip=[alt.Tooltip("Date:T", title="Date"), alt.Tooltip("Score:Q", title="Score")],
        )
    )
    # Dashed reference lines at the same PASS/COACHING thresholds used
    # everywhere else in the app (see lib/constants.compute_result) — status
    # color, not a third data series, so no legend entry is needed for them.
    pass_rule = alt.Chart(pd.DataFrame({"y": [85]})).mark_rule(strokeDash=[4, 4], color=_ACCENT, opacity=0.6).encode(y="y:Q")
    coach_rule = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(strokeDash=[4, 4], color=_COACH, opacity=0.6).encode(y="y:Q")

    st.altair_chart((pass_rule + coach_rule + line).properties(height=280), use_container_width=True)
    st.caption("Dashed lines mark the PASS (85) and COACHING (70) thresholds.")
else:
    st.caption("Not enough scored evaluations yet to show a trend — check back after your next one.")

st.divider()

# ---------- rubric category breakdown ----------
st.subheader("Category breakdown")
st.caption("Your average score in each rubric category, as a share of that category's max points.")

cat_rows = []
for r in RUBRIC:
    vals = [
        (e.get("scores") or {}).get(r["key"])
        for e in real_entries
        if (e.get("scores") or {}).get(r["key"]) is not None
    ]
    if vals:
        avg = sum(vals) / len(vals)
        pct = round(avg / r["max"] * 100, 1)
    else:
        avg = pct = None
    cat_rows.append({"Category": r["name"], "Avg": avg, "Max": r["max"], "Pct": pct})

scored_cats = [row for row in cat_rows if row["Pct"] is not None]
if scored_cats:
    def _status_color(pct: float) -> str:
        if pct >= 85:
            return _ACCENT
        if pct >= 60:
            return _COACH
        return _FAIL

    chart_df = pd.DataFrame(
        [{"Category": row["Category"], "Pct": row["Pct"], "Color": _status_color(row["Pct"])} for row in scored_cats]
    )
    bars = (
        alt.Chart(chart_df)
        .mark_bar(size=26, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X("Pct:Q", title="% of category max", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("Category:N", sort=None, title=None),
            color=alt.Color("Color:N", scale=None, legend=None),
            tooltip=[alt.Tooltip("Category:N", title="Category"), alt.Tooltip("Pct:Q", title="% of max")],
        )
    )
    labels = bars.mark_text(align="left", dx=4, color=_MUTED).encode(text=alt.Text("Pct:Q", format=".0f"))
    st.altair_chart((bars + labels).properties(height=36 * len(scored_cats) + 40), use_container_width=True)

    table_rows = [
        {
            "Category": row["Category"],
            "Avg score": f'{row["Avg"]:.1f} / {row["Max"]}' if row["Avg"] is not None else "—",
            "% of max": f'{row["Pct"]}%' if row["Pct"] is not None else "—",
        }
        for row in cat_rows
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
else:
    st.caption("No scored evaluations yet.")

st.divider()

# ---------- full list with remarks ----------
st.subheader("All your evaluations")
st.caption("Most recent first. Expand one to see the full scoring breakdown, reviewer remarks, and comments.")

sorted_entries = sorted(entries, key=lambda e: (e.get("qa_date") or "", e.get("updated_at") or ""), reverse=True)

for e in sorted_entries:
    ticket_id = e.get("ticket_id") or ""
    ticket_url = e.get("ticket_link") or (conversation_url(ticket_id) if ticket_id else "")
    label = (
        f"{e.get('qa_date') or '—'} · {e.get('result') or '—'} · {e.get('total_score', '—')}/100"
        + (" · 🧪 TEST" if e.get("is_test") else "")
    )
    with st.expander(label):
        h1, h2, h3 = st.columns([2, 2, 3])
        h1.markdown(result_badge_md(e.get("result", "")), unsafe_allow_html=True)
        h2.markdown(f"**{e.get('total_score', '—')} / 100**")
        h3.caption(f"Reviewed by {e.get('qa_reviewer') or '—'} on {e.get('qa_date') or '—'}")

        if ticket_url:
            st.markdown(f"**Ticket:** [{ticket_id}]({ticket_url})")
        st.markdown(
            f"**Renter/Host:** {e.get('renter_host') or '—'} &nbsp;·&nbsp; "
            f"**Concern type:** {', '.join(e.get('concern_types') or []) or '—'}"
        )

        scores = e.get("scores") or {}
        remarks = e.get("remarks") or {}
        breakdown_rows = [
            {
                "Category": r["name"],
                "Score": scores.get(r["key"], "—"),
                "Max": r["max"],
                "Remarks": remarks.get(r["key"]) or "",
            }
            for r in RUBRIC
        ]
        st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)

        crit = e.get("critical_errors") or {}
        flagged = [c["label"] for c in CRITICAL_ERRORS if crit.get(c["key"])]
        if flagged:
            for lbl in flagged:
                st.error(f"🚫 {lbl}")

        if e.get("overall_comments"):
            st.markdown("**Overall comments**")
            st.write(e["overall_comments"])

        if e.get("is_escalated"):
            st.caption("🚩 Escalated")

st.divider()
agent_auth.render_change_password()
