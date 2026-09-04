"""Shared "open ticket" view: badges, transcript, actions, QA form.

Used by both the Quick Sample page and the Weekly QA Batch page so the two
stay in sync.
"""

from __future__ import annotations

import streamlit as st

from lib import db
from lib.constants import is_excluded_agent_name
from lib.intercom_client import build_transcript, conversation_url
from lib.qa_form import render as render_qa_form
from lib.ui import fmt_date_short, render_badges, render_transcript


def learn_agents_from_conversation(convo: dict) -> dict:
    """Upserts any admin authors into the agents table and returns {id: name}."""
    seen = {}
    src_author = (convo.get("source") or {}).get("author") or {}
    if src_author.get("type") == "admin" and src_author.get("id") and src_author.get("name"):
        seen[src_author["id"]] = src_author["name"]
    for p in ((convo.get("conversation_parts") or {}).get("conversation_parts")) or []:
        a = p.get("author") or {}
        if a.get("type") == "admin" and a.get("id") and a.get("name"):
            seen[a["id"]] = a["name"]
    for aid, name in seen.items():
        if not is_excluded_agent_name(name):
            db.upsert_agent(aid, name)
    return seen


def render_ticket(convo: dict, ticket_url: str, on_pick_another=None) -> None:
    ticket_id = str(convo["id"])
    reviewed_map = db.list_reviewed()
    is_reviewed = ticket_id in reviewed_map
    title = (convo.get("custom_attributes") or {}).get("AI Title") or convo.get("title") or f"Conversation #{ticket_id}"

    render_badges(convo, is_reviewed)
    st.header(title)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ticket", f"#{ticket_id}")
    m2.metric("Opened", fmt_date_short(convo.get("created_at")))
    m3.metric("Parts", (convo.get("statistics") or {}).get("count_conversation_parts", 0))
    m4.metric("Reopens", (convo.get("statistics") or {}).get("count_reopens", 0))

    a1, a2, a3 = st.columns([1, 1, 3])
    a1.link_button("Open in Intercom ↗", ticket_url or conversation_url(ticket_id))
    if on_pick_another and a2.button("Pick another", key=f"again_{ticket_id}"):
        on_pick_another()
        st.rerun()
    if is_reviewed:
        a3.button("Marked reviewed", disabled=True, key=f"reviewed_disabled_{ticket_id}")
    else:
        if a3.button("Mark reviewed", key=f"reviewed_{ticket_id}"):
            db.mark_reviewed(ticket_id, title, convo.get("state", ""), conversation_url(ticket_id))
            db.clear_cache()
            st.rerun()

    with st.container(border=True):
        render_transcript(build_transcript(convo))

    seen = learn_agents_from_conversation(convo)
    guessed_agent = next((n for aid, n in seen.items() if str(aid) == str(convo.get("admin_assignee_id"))), "")
    render_qa_form(convo, ticket_url or conversation_url(ticket_id), guessed_agent)
