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


# ---------- app-wide look ("Charge Point": bright card-grid, green accent) ----------
# Streamlit's own [theme] section in .streamlit/config.toml sets the base
# colors (background/surface/text/accent) so they're consistent even before
# the page finishes loading; this CSS layers on the parts config.toml can't
# reach — rounded stat-tile cards, the sidebar's active-page rail, and the
# pill-shaped result badges used by result_badge_md() below. Fonts are left
# at Streamlit's default. Call inject_style() once near the top of every
# page, right after st.set_page_config().
_STYLE_BLOCK = """
<style>
:root {
    --qa-accent: #14a173;
    --qa-accent-soft: #e4f6ee;
    --qa-coach: #d69a34;
    --qa-coach-soft: #fbf0dd;
    --qa-fail: #cf4a5c;
    --qa-fail-soft: #fbe6e8;
    --qa-muted: #5c6f66;
}

/* ---- stat tiles (st.metric) ---- */
div[data-testid="stMetric"] {
    background-color: #ffffff;
    border: 1px solid rgba(20, 32, 27, 0.12);
    border-radius: 14px;
    padding: 14px 18px 12px 18px;
}
div[data-testid="stMetricLabel"] p {
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--qa-muted);
}
div[data-testid="stMetricValue"] p {
    font-variant-numeric: tabular-nums;
}

/* ---- sidebar: highlight the current page with a green rail ---- */
[data-testid="stSidebarNavLink"] {
    border-radius: 8px;
}
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background-color: var(--qa-accent-soft) !important;
    position: relative;
}
[data-testid="stSidebarNavLink"][aria-current="page"]::before {
    content: "";
    position: absolute;
    left: -8px;
    top: 6px;
    bottom: 6px;
    width: 3px;
    border-radius: 2px;
    background: var(--qa-accent);
}
[data-testid="stSidebarNavLink"][aria-current="page"] span,
[data-testid="stSidebarNavLink"][aria-current="page"] p {
    color: var(--qa-accent) !important;
}

/* ---- result pills — see result_badge_md() ---- */
.qa-chip {
    display: inline-block;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 3px 11px;
    border-radius: 999px;
    line-height: 1.6;
    white-space: nowrap;
}
.qa-chip-pass { background: var(--qa-accent-soft); color: var(--qa-accent); }
.qa-chip-coaching { background: var(--qa-coach-soft); color: var(--qa-coach); }
.qa-chip-fail { background: var(--qa-fail-soft); color: var(--qa-fail); }
</style>
"""


def inject_style() -> None:
    """Applies the app's look — stat-tile cards, sidebar active-page rail,
    result pills. Call once near the top of every page, right after
    st.set_page_config()."""
    st.markdown(_STYLE_BLOCK, unsafe_allow_html=True)


# Tickets in this app are always Intercom conversations, so the Intercom
# mark stands in for the old ticket emoji — as the browser-tab favicon
# (page_icon=ui.LOGO_URL) and inline in page headings via page_heading()
# below. Streamlit's sidebar nav icons only accept an emoji or a built-in
# Material icon, not an arbitrary image, so app.py keeps a plain emoji
# there instead.
LOGO_URL = "https://cdn.simpleicons.org/intercom"


def page_heading(text: str) -> None:
    """Renders a page's <h1> heading with the Intercom logo inline in place
    of the old ticket emoji."""
    st.markdown(
        f'<h1 style="display:flex;align-items:center;gap:0.35em;">'
        f'<img src="{LOGO_URL}" alt="Intercom" style="height:1em;width:1em;border-radius:0.2em;">'
        f"{text}</h1>",
        unsafe_allow_html=True,
    )


_RESULT_CHIP_CLASS = {
    "PASS": "qa-chip-pass",
    "COACHING": "qa-chip-coaching",
    "FAIL": "qa-chip-fail",
    "AUTO FAIL": "qa-chip-fail",
}


def result_badge_md(result: str) -> str:
    """Returns an HTML pill for a QA result — pass unsafe_allow_html=True to
    whichever st.markdown() call renders it."""
    css_class = _RESULT_CHIP_CLASS.get(result, "qa-chip-coaching")
    return f'<span class="qa-chip {css_class}">{result or "—"}</span>'


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
