"""Weekly QA batch — pulls 3 topic-diverse tickets per agent per week."""

from datetime import date, timedelta

import streamlit as st

from lib import auth, db, sampling
from lib.intercom_client import IntercomError, conversation_url, get_conversation, search_conversations
from lib.ticket_view import render_ticket

st.set_page_config(page_title="Weekly QA Batch — Ticket QA Sampler", page_icon="🎫", layout="wide")

st.sidebar.title("🎫 Ticket QA Sampler")
auth.render_sidebar_auth()
st.sidebar.divider()
st.sidebar.subheader("Weekly QA batch")


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


ss = st.session_state
ss.setdefault("batch_week_monday", monday_of(date.today()))
ss.setdefault("batch_agent_name", "")
ss.setdefault("batch_open_ticket_id", None)

agent_roster = {a["name"].lower(): a for a in db.list_agents()}
agent_names = sorted({a["name"] for a in db.list_agents() if a.get("name")})

agent_input = st.sidebar.text_input(
    "Agent", value=ss["batch_agent_name"], key="batch_agent_input", placeholder="Type an agent name"
)
if agent_names:
    st.sidebar.caption("Known agents: " + ", ".join(agent_names))

agent_id = None
agent_ok = True
if agent_input.strip():
    if agent_input.strip().isdigit():
        agent_id = agent_input.strip()
    else:
        hit = agent_roster.get(agent_input.strip().lower())
        if hit:
            agent_id = hit["id"]
        else:
            agent_ok = False

if not agent_input.strip():
    st.sidebar.caption("Pick or type an agent to begin.")
elif not agent_ok:
    st.sidebar.error(f'No agent named "{agent_input}" yet — pick a suggestion or use their numeric admin ID.')

ss["batch_agent_name"] = agent_input
week_monday = ss["batch_week_monday"]
week_sunday = week_monday + timedelta(days=6)
is_current_week = week_monday == monday_of(date.today())

wc1, wc2, wc3 = st.sidebar.columns([1, 3, 1])
if wc1.button("‹", key="week_prev"):
    ss["batch_week_monday"] = week_monday - timedelta(days=7)
    st.rerun()
wc2.markdown(
    f"<div style='text-align:center;font-family:monospace;font-size:12px;padding-top:6px;'>"
    f"Week of {week_monday.strftime('%b %-d')}–{week_sunday.strftime('%b %-d, %Y')}</div>",
    unsafe_allow_html=True,
)
if wc3.button("›", key="week_next", disabled=is_current_week):
    ss["batch_week_monday"] = week_monday + timedelta(days=7)
    st.rerun()
if is_current_week:
    st.sidebar.caption("📍 Week in progress")

exclude_fin = st.sidebar.checkbox("Exclude Fin AI-handled tickets", value=True, key="batch_exclude_fin")

picks_row = db.get_weekly_picks(agent_id, week_monday.isoformat()) if agent_id else None
tickets = (picks_row or {}).get("tickets") or []

st.sidebar.markdown("**Progress this week**")
slot_cols = st.sidebar.columns(3)
for i in range(3):
    with slot_cols[i]:
        if i < len(tickets):
            t = tickets[i]
            state = "✅ Reviewed" if t.get("reviewed") else "Pulled"
            if st.button(t.get("topic") or f"#{t['id']}", key=f"slot_{i}", use_container_width=True):
                ss["batch_open_ticket_id"] = t["id"]
                st.rerun()
            st.caption(state)
        else:
            st.caption(f"Slot {i+1}\n\n_empty_")

remaining = 3 - len(tickets)
if not agent_id:
    pull_label, pull_disabled = "Pick or type an agent", True
elif remaining <= 0:
    pull_label, pull_disabled = "Quota met (3 of 3)", True
elif is_current_week:
    pull_label, pull_disabled = f"Pull today's ticket (#{len(tickets)+1} of 3)", False
else:
    pull_label, pull_disabled = f"Pick remaining {remaining} ticket{'s' if remaining != 1 else ''}", False

batch_status = st.sidebar.empty()

if st.sidebar.button(pull_label, type="primary", disabled=pull_disabled, use_container_width=True):
    have_ids = {t["id"] for t in tickets}
    have_topics = [t.get("topic") for t in tickets if t.get("topic")]
    reviewed_map = db.list_reviewed()
    needed_now = 1 if is_current_week else remaining
    week_end_effective = min(week_sunday, date.today())

    with st.spinner("Searching Intercom…"):
        try:
            results, _total, _fin = search_conversations(week_monday, week_end_effective, exclude_fin, agent_id)
        except IntercomError as e:
            batch_status.error(str(e))
            results = None

    if results is not None:
        candidates = []
        for r in results:
            rid = str(r.get("id", "")).replace("conversation_", "")
            if rid and rid not in have_ids and rid not in reviewed_map:
                candidates.append({"id": rid, "text": r.get("source", {}).get("body", "") or r.get("text", ""), "title": r.get("title", ""), "url": r.get("url") or conversation_url(rid)})

        if not candidates:
            batch_status.info(
                f"No new closed, unreviewed tickets from {agent_input} yet this week. Check back later."
                if is_current_week
                else f"No closed, unreviewed tickets found for {agent_input} in this week."
            )
        else:
            batch_status.info(f"Reading {min(len(candidates), 40)} ticket(s) to find different concerns…")
            picks = sampling.pick_diverse(candidates, needed_now, have_topics, agent_input)
            new_tickets = [
                {
                    "id": p["id"],
                    "topic": p.get("topic", ""),
                    "reason": p.get("reason", ""),
                    "subject": p.get("subject", ""),
                    "url": p.get("url") or conversation_url(p["id"]),
                    "reviewed": False,
                }
                for p in picks
            ]
            merged = (tickets + new_tickets)[:3]
            db.save_weekly_picks(agent_id, agent_input, week_monday.isoformat(), merged)
            batch_status.empty()
            if new_tickets:
                ss["batch_open_ticket_id"] = new_tickets[0]["id"]
            st.rerun()

# ---------- main stage ----------
open_id = ss.get("batch_open_ticket_id")
if not open_id:
    st.info("Pick or type an agent in the sidebar, then pull this week's QA batch — 3 topic-diverse tickets per agent per week.")
else:
    ticket_url = next((t["url"] for t in tickets if t["id"] == open_id), conversation_url(open_id))
    try:
        with st.spinner(f"Loading conversation #{open_id}…"):
            convo = get_conversation(open_id)
        render_ticket(convo, ticket_url)
    except IntercomError as e:
        st.error(f"Could not load conversation #{open_id}: {e}")
