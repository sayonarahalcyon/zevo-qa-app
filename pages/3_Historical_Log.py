"""Historical Log — read-only archive of evaluations from the retired
"2026 - ZEVO QA Tracker v2" Google Sheet.

This is reference-only: it is NOT part of the live QA Log's dashboard,
pass rate, or per-agent rollup, so old sheet data never mixes with or
skews current metrics. New audits are logged in the QA Log page, not here.
"""

import pandas as pd
import streamlit as st

from lib import auth, db
from lib.constants import RUBRIC

st.set_page_config(page_title="Historical Log — Ticket QA Sampler", page_icon="🗄️", layout="wide")

if not auth.is_signed_in():
    st.title("Historical Log")
    st.warning("Sign in to view the Historical Log. Head to Home and sign in as one of the three reviewers.")
    st.page_link("pages/0_Home.py", label="🏠 Go to Home to sign in", use_container_width=False)
    st.stop()

ss = st.session_state
ss.setdefault("hist_open_id", None)

entries = db.list_historical_entries()

st.title("Historical Log")
st.caption(
    "Imported from the retired \"2026 - ZEVO QA Tracker v2\" Google Sheet. "
    "Read-only — not counted in the QA Log's live dashboard or per-agent rollup."
)

if not entries:
    st.info(
        "No historical entries yet. This page reads from the `historical_qa_entries` table "
        "in Supabase, imported once from the old QA Tracker sheet."
    )
    st.stop()

if ss.get("hist_open_id"):
    open_id = ss["hist_open_id"]
    entry = next((e for e in entries if e["id"] == open_id), None)
    if st.button("← Back to Historical Log"):
        ss["hist_open_id"] = None
        st.rerun()
    if not entry:
        st.error("That entry couldn't be found.")
    else:
        st.subheader(f"{entry.get('agent_name', '')} — {entry.get('qa_date', '')}")
        badge = {"PASS": "\U0001F7E2", "COACHING": "\U0001F7E1", "FAIL": "\U0001F534", "AUTO FAIL": "⛔"}.get(entry.get("result"), "")
        st.markdown(f"{badge} **{entry.get('result', '')}** · {entry.get('total_score', '—')} pts · reviewed by {entry.get('qa_reviewer') or '—'}")
        st.caption(f"Source: {entry.get('source_tab', '')} tab · Concern: {', '.join(entry.get('concern_types') or []) or '—'} · Renter/Host: {entry.get('renter_host') or '—'}")

        link_cols = st.columns(2)
        if entry.get("ticket_link"):
            link_cols[0].link_button("Open ticket in Intercom ↗", entry["ticket_link"], use_container_width=True)
        if entry.get("zomp_link"):
            link_cols[1].link_button("Open in ZOMP ↗", entry["zomp_link"], use_container_width=True)

        st.divider()
        scores = entry.get("scores") or {}
        remarks = entry.get("remarks") or {}
        for r in RUBRIC:
            key = r["key"]
            score = scores.get(key)
            st.markdown(f"**{r['name']}** — {score if score is not None else '—'} / {r['max']}")
            note = (remarks.get(key) or "").strip()
            if note:
                st.caption(note)

        if entry.get("overall_comments"):
            st.divider()
            st.markdown("**Overall comments**")
            st.write(entry["overall_comments"])

        critical = entry.get("critical_errors") or {}
        if any(critical.values()):
            st.divider()
            flagged = [k for k, v in critical.items() if v]
            st.error(f"Critical error(s) flagged: {', '.join(flagged)}")
    st.stop()

# ---------- filters ----------
agent_names = sorted({e["agent_name"] for e in entries if e.get("agent_name")})
f1, f2, f3 = st.columns(3)
agent_filter = f1.selectbox("Agent", ["All agents"] + agent_names)
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
filtered.sort(key=lambda e: e.get("qa_date") or "", reverse=True)

# ---------- historical totals (separate from the live QA Log dashboard) ----------
total = len(filtered)
counts = {"PASS": 0, "COACHING": 0, "FAIL": 0, "AUTO FAIL": 0}
score_sum = 0
for e in filtered:
    if e.get("result") in counts:
        counts[e["result"]] += 1
    score_sum += e.get("total_score") or 0
avg_score = round(score_sum / total, 1) if total else None

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Historical Audits", total)
c2.metric("Pass", counts["PASS"])
c3.metric("Coaching", counts["COACHING"])
c4.metric("Fail", counts["FAIL"] + counts["AUTO FAIL"])
c5.metric("Avg Score", f"{avg_score}" if avg_score is not None else "—")

st.divider()

if not filtered:
    st.caption("No historical entries match these filters.")
else:
    table_rows = [
        {
            "Date": e.get("qa_date", ""),
            "Agent": e.get("agent_name", ""),
            "Concern": ", ".join(e.get("concern_types") or []),
            "Total": e.get("total_score"),
            "Result": e.get("result", ""),
            "Reviewer": e.get("qa_reviewer", ""),
            "_id": e["id"],
        }
        for e in filtered[:300]
    ]
    df = pd.DataFrame(table_rows)
    event = st.dataframe(
        df.drop(columns=["_id"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )
    if len(filtered) > 300:
        st.caption(f"Showing the most recent 300 of {len(filtered)} matching entries.")
    selected = event.selection.rows if hasattr(event, "selection") else []
    if selected:
        ss["hist_open_id"] = table_rows[selected[0]]["_id"]
        st.rerun()
