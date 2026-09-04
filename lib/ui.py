"""Shared rendering helpers used by every page."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

try:
    import bleach

    _ALLOWED_TAGS = ["p", "br", "a", "strong", "em", "b", "i", "ul", "ol", "li", "blockquote", "span"]
    _ALLOWED_ATTRS = {"a": ["href", "title"]}

    def sanitize_html(html: str | None) -> str:
        if not html:
            return ""
        cleaned = bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)
        return bleach.linkify(cleaned)

except Exception:  # bleach not installed — fall back to plain text
    import re

    def sanitize_html(html: str | None) -> str:
        if not html:
            return ""
        return re.sub("<[^<]+?>", " ", html)


def fmt_datetime(epoch_seconds) -> str:
    if not epoch_seconds:
        return "—"
    return datetime.fromtimestamp(epoch_seconds).strftime("%b %-d, %Y %-I:%M %p")


def fmt_date_short(epoch_seconds) -> str:
    if not epoch_seconds:
        return "—"
    return datetime.fromtimestamp(epoch_seconds).strftime("%b %-d, %Y")


RESULT_COLORS = {
    "PASS": "🟢",
    "COACHING": "🟡",
    "FAIL": "🔴",
    "AUTO FAIL": "⛔",
}


def result_badge_md(result: str) -> str:
    return f"{RESULT_COLORS.get(result, '')} **{result}**"


def render_transcript(entries: list[dict]) -> None:
    for e in entries:
        if e["kind"] == "event":
            st.caption(f"— {e['text']} · {fmt_datetime(e['created_at'])} —")
            continue
        author = e.get("author") or {}
        name = author.get("name") or ("Customer" if e["role"] == "customer" else "ZEVO Support")
        note_label = " · internal note" if e.get("is_note") else ""
        who_line = f"**{name}**{note_label} &nbsp;·&nbsp; {fmt_datetime(e['created_at'])}"
        body_html = sanitize_html(e.get("body")) or "*(no message body)*"

        if e["role"] == "customer":
            with st.chat_message("user"):
                st.markdown(who_line, unsafe_allow_html=True)
                st.markdown(body_html, unsafe_allow_html=True)
        elif e["role"] == "note":
            st.warning(f"{who_line}\n\n{body_html}", icon="📝")
        else:
            with st.chat_message("assistant"):
                st.markdown(who_line, unsafe_allow_html=True)
                st.markdown(body_html, unsafe_allow_html=True)


def render_badges(convo: dict, is_reviewed: bool) -> None:
    from lib.intercom_client import channel_label

    badges = [convo.get("state", "closed").upper(), channel_label((convo.get("source") or {}).get("type"))]
    if convo.get("ai_agent_participated"):
        state = (convo.get("ai_agent") or {}).get("resolution_state")
        badges.append(f"Fin AI Agent{' · ' + state if state else ''}")
    rating = (convo.get("conversation_rating") or {}).get("rating")
    if rating:
        badges.append(f"CSAT {rating}/5")
    if is_reviewed:
        badges.append("✅ Reviewed")
    st.caption(" &nbsp;·&nbsp; ".join(badges))
