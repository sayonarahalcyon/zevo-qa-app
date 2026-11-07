"""Posts the "phone tickets ready to audit" message to the phone QA Slack
channel, from the Phone Queue page's Notify channel button.

Uses a Slack incoming webhook, set in Streamlit secrets:

    [slack]
    phone_qa_webhook_url = "https://hooks.slack.com/services/..."
    app_url = "https://zevo-quality-audit-app.streamlit.app"   # optional

Until the webhook is added the button stays disabled, so nothing can be posted
by accident while the feature is being set up.
"""

from __future__ import annotations

import requests
import streamlit as st

DEFAULT_APP_URL = "https://zevo-quality-audit-app.streamlit.app"
MAX_LISTED = 20


def webhook_url() -> str | None:
    try:
        url = st.secrets["slack"]["phone_qa_webhook_url"]
    except Exception:
        return None
    return url or None


def queue_url() -> str:
    try:
        base = st.secrets["slack"].get("app_url") or DEFAULT_APP_URL
    except Exception:
        base = DEFAULT_APP_URL
    return base.rstrip("/") + "/Phone_Queue"


def build_message(tickets: list[dict], total_waiting: int | None = None) -> str:
    """The Slack text for a batch. `tickets` are the newly loaded queue rows."""
    n = len(tickets)
    lines = [f":telephone_receiver: *{n} phone ticket{'s' if n != 1 else ''} ready to audit* in the QA App."]
    for t in tickets[:MAX_LISTED]:
        agent = t.get("agent_name") or "Unknown agent"
        lines.append(f"• #{t.get('ticket_id')} · {agent}")
    if n > MAX_LISTED:
        lines.append(f"…and {n - MAX_LISTED} more.")
    if total_waiting is not None and total_waiting > n:
        lines.append(f"{total_waiting} tickets are waiting in the queue in total.")
    lines.append(f"Claim one in the Phone Queue: {queue_url()}")
    return "\n".join(lines)


def post(text: str) -> str | None:
    """Posts to the channel. Returns None on success, or an error message."""
    url = webhook_url()
    if not url:
        return "Slack isn't connected yet (no webhook in Secrets)."
    try:
        resp = requests.post(url, json={"text": text}, timeout=15)
    except requests.RequestException as e:
        return f"Could not reach Slack: {e}"
    if resp.status_code >= 400:
        return f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}"
    return None
