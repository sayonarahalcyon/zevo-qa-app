"""QA Log — dashboard, per-agent rollup, filterable audit log, scoring guide."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import auth, db
from lib.constants import CRITICAL_ERRORS, DISPUTE_FORM_URL, RUBRIC, RUBRIC_GUIDE
from lib.intercom_client import IntercomError, conversation_url, get_conversation
from lib.ticket_view import render_ticket

st.set_page_config(page_title="QA Log — Ticket QA Sampler", page_icon="🎫", layout="wide")

st.sidebar.title("🎫 Ticket Selection")
auth.render_sidebar_auth()

ss = st.session_state
ss.setdefault("log_open_ticket_id", None)

entries = db.list_qa_entries()
agents = db.list_agents()
agents_by_id = {a["id"]: a["name"] for a in agents}

if ss.get("log_open_ticket_id"):
    open_id = ss["log_open_ticket_id"]
    if st.button("← Back to QA Log"):
        ss["log_open_ticket_id"] = None
        st.rerun()
    try:
        with st.spinner(f"Loading conversation #{open_id}…"):
            convo = get_conversation(open_id)
        render_ticket(convo, conversation_url(open_id))
    except IntercomError as e:
        st.error(f"Could not load conversation #{open_id}: {e}")
    st.stop()

st.title("QA Log")

# ---------- dashboard ----------
total = len(entries)
counts = {"PASS": 0, "COACHING": 0, "FAIL": 0, "AUTO FAIL": 0}
score_sum = 0
for e in entries:
    if e.get("result") in counts:
        counts[e["result"]] += 1
    score_sum += e.get("total_score") or 0
avg_score = round(score_sum / total, 1) if total else None
pass_rate = round(counts["PASS"] / total * 100, 1) if total else None

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Audits", total)
c2.metric("Pass", counts["PASS"])
c3.metric("Coaching", counts["COACHING"])
c4.metric("Fail", counts["FAIL"] + counts["AUTO FAIL"])
c5.metric("Avg Score", f"{avg_score}" if avg_score is not None else "—")
c6.metric("Pass Rate", f"{pass_rate}%" if pass_rate is not None else "—")

st.divider()

# ---------- per-agent rollup ----------
st.subheader("Per-agent rollup")
today = date.today()
week_monday = today - timedelta(days=today.weekday())
week_sunday = week_monday + timedelta(days=6)

rollup_rows = []
for aid, name in sorted(agents_by_id.items(), key=lambda kv: kv[1].lower()):
    mine = [e for e in entries if e.get("agent_id") == aid or (e.get("agent_name") or "").lower() == name.lower()]
    avg = round(sum(e.get("total_score") or 0 for e in mine) / len(mine), 1) if mine else None
    week_count = sum(
        1 for e in mine if e.get("qa_date") and week_monday.isoformat() <= e["qa_date"] <= week_sunday.isoformat()
    )
    rollup_rows.append(
        {
            "Agent": name,
            "Audits": len(mine),
            "Avg Score": avg if avg is not None else "—",
            "Status": ("Pass" if (avg or 0) >= 85 else "Fail") if avg is not None else "—",
            "This week (of 3)": f"{week_count} / 3",
        }
    )

if rollup_rows:
    st.dataframe(pd.DataFrame(rollup_rows), use_container_width=True, hide_index=True)
else:
    st.caption("No agents in the directory yet — they're learned automatically as tickets are opened.")

st.divider()

# ---------- filterable audit log ----------
st.subheader("Audit log")
f1, f2, f3 = st.columns(3)
agent_filter = f1.selectbox("Agent", ["All agents"] + sorted(agents_by_id.values()))
result_filter = f2.selectbox("Result", ["All results", "PASS", "COACHING", "FAIL", "AUTO FAIL"])
q_filter = f3.text_input("Search concern / comments…")

filtered = []
for e in entries:
    if agent_filter != "All agents" and e.get("agent_name") != agent_filter:
        continue
    if result_filter != "All results" and e.get("result") != result_filter:
        continue
    if q_filter:
        hay = f"{e.get('agent_name','')} {' '.join(e.get('concern_types') or [])} {e.get('overall_comments','')}".lower()
        if q_filter.lower() not in hay:
            continue
    filtered.append(e)
filtered.sort(key=lambda e: (e.get("qa_date") or "", e.get("updated_at") or ""), reverse=True)

if filtered:
    table_rows = [
        {
            "Date": e.get("qa_date", ""),
            "Agent": e.get("agent_name", ""),
            "Concern": ", ".join(e.get("concern_types") or []),
            "Total": e.get("total_score"),
            "Result": e.get("result", ""),
            "Reviewer": e.get("qa_reviewer", ""),
            "_ticket_id": e.get("ticket_id") or e.get("id"),
        }
        for e in filtered[:300]
    ]
    df = pd.DataFrame(table_rows)
    event = st.dataframe(
        df.drop(columns=["_ticket_id"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    if len(filtered) > 300:
        st.caption(f"Showing the most recent 300 of {len(filtered)} matching audits.")
    selected = event.selection.rows if hasattr(event, "selection") else []
    if selected:
        ss["log_open_ticket_id"] = table_rows[selected[0]]["_ticket_id"]
        st.rerun()
else:
    st.caption("No audits match these filters yet.")

st.divider()

# ---------- scoring guide ----------
st.subheader("Scoring guide")
with st.expander("Scoring rubric (5 categories, 100 points)"):
    for r in RUBRIC:
        st.markdown(f"**{r['name']}** (max {r['max']})")
        st.caption(RUBRIC_GUIDE[r["key"]])

with st.expander('Critical errors (any = automatic FAIL)'):
    for c in CRITICAL_ERRORS:
        st.markdown(f"**{c['label']}**")
        st.caption(c["desc"])

with st.expander("Result thresholds"):
    st.markdown(
        "**PASS** — total score 85 or higher, no critical errors.  \n"
        "**COACHING** — total score 70–84, no critical errors.  \n"
        "**FAIL** — total score below 70.  \n"
        "**AUTO FAIL** — any critical error, regardless of total score."
    )

with st.expander("Dispute a score"):
    st.markdown(f"Agents can dispute a QA score using the [QA Audit Dispute Form]({DISPUTE_FORM_URL}).")
