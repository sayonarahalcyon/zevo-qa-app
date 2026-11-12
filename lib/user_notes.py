"""The guest's Intercom "User notes" (the notes on the contact in Intercom's
sidebar), shown next to a ticket so Documentation can be scored without
opening Intercom. Agents usually write a dated note with the ticket's link,
so a note counts as this ticket's when it links to (or mentions) this
conversation id, or when the ticket's own agent wrote it while the ticket was
being handled (from 1 hour before it opened to 2 days after it was last
updated).

This ticket's notes are shown first; the guest's other notes (every other
booking and ticket) are in a collapsed list below. Everyone who can open the
ticket sees both, phone evaluators included (Weng, 2026-11-12).
"""

from __future__ import annotations

import streamlit as st

from lib.intercom_client import IntercomError, list_contact_notes
from lib.ui import fmt_datetime, html_to_markdown

BEFORE_SECONDS = 3600
AFTER_SECONDS = 2 * 86400


def _ticket_agent_ids(convo: dict) -> set[str]:
    ids = set()
    if convo.get("admin_assignee_id"):
        ids.add(str(convo["admin_assignee_id"]))
    for p in ((convo.get("conversation_parts") or {}).get("conversation_parts")) or []:
        a = p.get("author") or {}
        if a.get("type") == "admin" and p.get("part_type") in ("comment", "note", "phone_call", "call_summary"):
            ids.add(str(a.get("id")))
    return ids


def split_notes(notes: list[dict], convo: dict) -> tuple[list[dict], list[dict]]:
    """(this ticket's notes, the user's other notes), each newest first."""
    cid = str(convo.get("id") or "")
    agents = _ticket_agent_ids(convo)
    start = (convo.get("created_at") or 0) - BEFORE_SECONDS
    end = (convo.get("updated_at") or convo.get("created_at") or 0) + AFTER_SECONDS
    mine, other = [], []
    for n in notes:
        body = n.get("body") or ""
        author_id = str((n.get("author") or {}).get("id") or "")
        when = n.get("created_at") or 0
        if (cid and cid in body) or (author_id in agents and start <= when <= end):
            mine.append(n)
        else:
            other.append(n)
    return mine, other


def _contact_ids(convo: dict) -> list[str]:
    return [c["id"] for c in ((convo.get("contacts") or {}).get("contacts") or []) if c.get("id")]


def _note_box(n: dict) -> None:
    who = (n.get("author") or {}).get("name") or "Unknown"
    st.warning(
        f"**{who}** &nbsp;·&nbsp; {fmt_datetime(n.get('created_at'))}\n\n{html_to_markdown(n.get('body')) or '*(empty note)*'}",
        icon="👤",
    )


def render_user_notes(convo: dict, evaluator_mode: bool = False) -> None:
    contact_ids = _contact_ids(convo)
    st.markdown("#### 👤 User notes")
    if not contact_ids:
        st.caption("This ticket has no user attached, so there are no user notes to show.")
        return
    notes = []
    try:
        for cid in contact_ids:
            notes.extend(list_contact_notes(cid))
    except IntercomError as e:
        st.warning(f"Couldn't load the user notes from Intercom: {e}")
        return
    mine, other = split_notes(notes, convo)
    st.caption(
        "Notes on the guest's Intercom profile that link to this ticket, or that the ticket's agent wrote "
        "while handling it. Use these with the call to score Documentation."
    )
    if mine:
        for n in mine:
            _note_box(n)
    else:
        st.info("No user notes for this ticket. The agent left no note on the guest's profile linking to it.")
    if other:
        with st.expander(f"The guest's other user notes ({len(other)})"):
            for n in other:
                _note_box(n)
