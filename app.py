"""Ticket QA Sampler — Quick Sample.

Streamlit rebuild of the Claude-artifact "Ticket QA Sampler" so ZEVO CS can
run it from GitHub + Streamlit Community Cloud instead of an in-conversation
artifact. See README.md for setup, and sql/schema.sql for the Supabase
tables this app expects.
"""

import random
from datetime import date, timedelta

import streamlit as st

from lib import auth, db
from lib.intercom_client import IntercomError, conversation_url, get_conversation, search_conversations
from lib.ticket_view import render_ticket

st.set_page_config(page_title="Ticket QA Sampler", page_icon="🎫", layout="wide")

st.sidebar.title("🎫 Ticket QA Sampler")
st.sidebar.caption("ZEVO Support · Intercom")
auth.render_sidebar_auth()
st.sidebar.divider()

# ---------- session state ----------
ss = st.session_state
ss.setdefault("pool", [])
ss.setdefault("pool_total", 0)
ss.setdefault("used_ids", set())
ss.setdefault("current_ticket_id", None)
ss.setdefault("fin_filter_warning", False)

# ---------- sidebar filters ----------
st.sidebar.subheader("Sample filters")

preset_cols = st.sidebar.columns(3)
if preset_cols[0].button("7d", use_container_width=True):
    ss["start_date"] = date.today() - timedelta(days=7)
    ss["end_date"] = date.today()
if preset_cols[1].button("30d", use_container_width=True):
    ss["start_date"] = date.today() - timedelta(days=30)
    ss["end_date"] = date.today()
if preset_cols[2].button("This mo.", use_container_width=True):
    ss["start_date"] = date.today().replace(day=1)
    ss["end_date"] = date.today()

ss.setdefault("start_date", date.today() - timedelta(days=7))
ss.setdefault("end_date", date.today())

start_date = st.sidebar.date_input("From", key="start_date")
end_date = st.sidebar.date_input("To", key="end_date")
st.sidebar.caption("Only **closed** conversations are sampled.")

exclude_fin = st.sidebar.checkbox("Exclude Fin AI-handled tickets", value=True, key="exclude_fin")
agent_filter = st.sidebar.text_input("Agent (name or numeric admin ID)", key="agent_filter")
skip_reviewed = st.sidebar.checkbox("Skip already-reviewed tickets", value=True, key="skip_reviewed")

agent_roster = {a["name"].lower(): a for a in db.list_agents()}


def resolve_agent_id(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None, True
    if raw.isdigit():
        return raw, True
    hit = agent_roster.get(raw.lower())
    if hit:
        return hit["id"], True
    return None, False


def pull_pool():
    agent_id, ok = resolve_agent_id(agent_filter)
    if not ok:
        st.sidebar.error(f'No agent named "{agent_filter}" yet — use their numeric admin ID or clear this field.')
        return
    if start_date > end_date:
        st.error('Check your dates — "From" is after "To".')
        return
    with st.spinner("Pulling matching tickets from Intercom…"):
        try:
            results, total, fin_applied = search_conversations(start_date, end_date, exclude_fin, agent_id)
        except IntercomError as e:
            st.error(f"{e} ")
            return
    pool = []
    for r in results:
        rid = str(r.get("id", "")).replace("conversation_", "")
        if not rid:
            continue
        pool.append({"raw_id": rid, "title": r.get("title", ""), "text": r.get("source", {}).get("body", "") or r.get("text", ""), "url": r.get("url") or conversation_url(rid)})
    ss["pool"] = pool
    ss["pool_total"] = total
    ss["used_ids"] = set()
    ss["fin_filter_warning"] = exclude_fin and not fin_applied
    if pool:
        pick_random()
    else:
        ss["current_ticket_id"] = None


def eligible_pool():
    reviewed = db.list_reviewed() if skip_reviewed else {}
    return [t for t in ss["pool"] if not (skip_reviewed and t["raw_id"] in reviewed)]


def pick_random():
    candidates = [t for t in eligible_pool() if t["raw_id"] not in ss["used_ids"]]
    if not candidates:
        candidates = eligible_pool()
        if not candidates:
            ss["current_ticket_id"] = None
            return
        ss["used_ids"] = set()  # exhausted this pass, allow repeats
    pick = random.choice(candidates)
    ss["used_ids"].add(pick["raw_id"])
    ss["current_ticket_id"] = pick["raw_id"]
    ss["current_ticket_url"] = pick["url"]


if st.sidebar.button("Pull random ticket", type="primary", use_container_width=True):
    pull_pool()

if ss["pool"]:
    reviewed_map = db.list_reviewed() if skip_reviewed else {}
    eligible = len(eligible_pool())
    msg = f"**{ss['pool_total']:,}** tickets match · sampling from a pool of **{len(ss['pool'])}** (Intercom's 150-per-pull limit)"
    if skip_reviewed:
        msg += f", **{eligible}** not yet reviewed"
    st.sidebar.caption(msg)
else:
    st.sidebar.caption("Set a timeframe and pull a ticket to begin.")

if ss.get("fin_filter_warning"):
    st.sidebar.warning(
        "Couldn't filter Fin-handled tickets server-side in this workspace — showing all closed tickets instead. "
        "Double-check the Fin badge on what you review.",
        icon="⚠️",
    )

st.sidebar.divider()
st.sidebar.subheader("Recently reviewed")
reviewed_rows = sorted(db.list_reviewed().values(), key=lambda r: r.get("reviewed_at") or "", reverse=True)[:40]
if reviewed_rows:
    for r in reviewed_rows:
        st.sidebar.caption(f"{r.get('subject') or ('#' + r['id'])} — {r.get('reviewed_at', '')[:10]}")
else:
    st.sidebar.caption("No tickets marked reviewed yet.")

# ---------- main stage ----------
ticket_id = ss.get("current_ticket_id")

if not ticket_id:
    st.info("Set a timeframe in the sidebar and click **Pull random ticket** to begin.")
else:
    try:
        with st.spinner(f"Loading conversation #{ticket_id}…"):
            convo = get_conversation(ticket_id)
    except IntercomError as e:
        st.error(f"Could not load conversation #{ticket_id}: {e}")
        convo = None

    if convo:
        st.caption(f"Pool: {len(ss['pool'])} tickets in this timeframe · {ss['pool_total']:,} total match")
        render_ticket(convo, ss.get("current_ticket_url") or conversation_url(ticket_id), on_pick_another=pick_random)
