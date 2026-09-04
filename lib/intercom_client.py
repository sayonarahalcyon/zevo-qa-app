"""Direct Intercom REST API client.

Replaces the Claude artifact's `mcp` capability (which talked to Intercom
through an MCP connector's own `search` / `get_conversation` tools). This
version calls Intercom's public API directly with a Bearer access token.

UNVERIFIED AGAINST A LIVE WORKSPACE — written from Intercom's public API
docs only. Before relying on this in production, run one Quick Sample pull
and check:
  - that the "Exclude Fin AI-handled tickets" filter actually excludes
    anything (the `ai_agent_participated` field may not be filterable via
    the Search API in every workspace; this client falls back to an
    unfiltered search and flags it in the UI rather than erroring out)
  - that convo["custom_attributes"]["AI Title"] is the right key for your
    workspace's Fin-generated title attribute
"""

from __future__ import annotations

import time
from datetime import date, datetime

import requests
import streamlit as st

API_BASE = "https://api.intercom.io"
INTERCOM_VERSION = "2.11"


class IntercomError(Exception):
    def __init__(self, message: str, code: str = "tool_error"):
        super().__init__(message)
        self.code = code


def _token() -> str | None:
    try:
        return st.secrets["intercom"]["access_token"]
    except Exception:
        return None


def _headers() -> dict:
    token = _token()
    if not token:
        raise IntercomError("Intercom is not connected — add the access token in Secrets.", "server_not_connected")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": INTERCOM_VERSION,
    }


def _to_epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day).timestamp())


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        resp = requests.request(method, f"{API_BASE}{path}", headers=_headers(), timeout=30, **kwargs)
    except requests.RequestException as e:
        raise IntercomError(f"Could not reach Intercom: {e}", "server_unavailable")
    if resp.status_code == 401:
        raise IntercomError("Intercom access token is invalid or expired.", "needs_reauth")
    if resp.status_code == 429:
        raise IntercomError("Intercom rate limit hit — try again shortly.", "server_unavailable")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("errors", [{}])[0].get("message", "")
        except Exception:
            detail = resp.text[:300]
        raise IntercomError(detail or f"Intercom returned HTTP {resp.status_code}.", "tool_error")
    return resp.json()


def search_conversations(
    start_date: date | None,
    end_date: date | None,
    exclude_fin: bool = True,
    admin_id: str | None = None,
    per_page: int = 150,
) -> tuple[list[dict], int, bool]:
    """Returns (results, total_count, fin_filter_applied)."""
    clauses = [{"field": "state", "operator": "=", "value": "closed"}]
    if start_date:
        clauses.append({"field": "created_at", "operator": ">", "value": _to_epoch(start_date)})
    if end_date:
        clauses.append({"field": "created_at", "operator": "<", "value": _to_epoch(end_date) + 86400})
    if admin_id:
        clauses.append({"field": "admin_assignee_id", "operator": "=", "value": str(admin_id)})

    def run(with_fin_clause: bool) -> dict:
        value = list(clauses)
        if with_fin_clause and exclude_fin:
            value.append({"field": "ai_agent_participated", "operator": "=", "value": False})
        body = {
            "query": {"operator": "AND", "value": value},
            "pagination": {"per_page": per_page},
        }
        return _request("POST", "/conversations/search", json=body)

    fin_filter_applied = False
    try:
        payload = run(with_fin_clause=True)
        fin_filter_applied = exclude_fin
    except IntercomError:
        # ai_agent_participated may not be a searchable field in this workspace —
        # fall back to an unfiltered search rather than failing the whole pull.
        payload = run(with_fin_clause=False)
        fin_filter_applied = False

    results = payload.get("conversations", []) or payload.get("results", [])
    total = (payload.get("total_count") or (payload.get("pages") or {}).get("total_count") or len(results))

    if exclude_fin and not fin_filter_applied:
        results = [r for r in results if not r.get("ai_agent_participated")]

    return results, total, fin_filter_applied


def get_conversation(conversation_id: str) -> dict:
    return _request("GET", f"/conversations/{conversation_id}")


@st.cache_data(ttl=300, show_spinner=False)
def list_admins() -> list[dict]:
    """Optional roster helper (the app primarily learns agents organically
    from conversations as they're opened, per the original design)."""
    try:
        payload = _request("GET", "/admins")
        return payload.get("admins", [])
    except IntercomError:
        return []


def channel_label(source_type: str | None) -> str:
    mapping = {
        "conversation": "Chat",
        "email": "Email",
        "sms": "SMS",
        "phone_call": "Phone",
        "phone_switch": "Phone",
        "push": "Push",
        "facebook": "Facebook",
        "instagram": "Instagram",
        "twitter": "Twitter",
        "whatsapp": "WhatsApp",
    }
    return mapping.get(source_type or "", source_type or "Conversation")


def conversation_url(conversation_id: str) -> str:
    return f"https://app.intercom.com/a/inbox/_/inbox/conversation/{conversation_id}"


def part_role(author: dict | None) -> str:
    if not author:
        return "admin"
    if author.get("type") in ("user", "lead", "contact"):
        return "customer"
    if author.get("from_ai_agent") or author.get("type") == "bot":
        return "fin"
    return "admin"


def build_transcript(convo: dict) -> list[dict]:
    """Flattened, time-sorted list of {kind, role, body, author, created_at, is_note}."""
    entries = []
    src = convo.get("source") or {}
    entries.append(
        {
            "kind": "msg",
            "role": "customer" if src.get("delivered_as") == "customer_initiated" else "admin",
            "body": src.get("body"),
            "author": src.get("author"),
            "created_at": convo.get("created_at"),
            "is_note": False,
        }
    )
    parts = ((convo.get("conversation_parts") or {}).get("conversation_parts")) or []
    for p in parts:
        if p.get("part_type") in ("comment", "note"):
            entries.append(
                {
                    "kind": "msg",
                    "role": "note" if p.get("part_type") == "note" else part_role(p.get("author")),
                    "body": p.get("body"),
                    "author": p.get("author"),
                    "created_at": p.get("created_at"),
                    "is_note": p.get("part_type") == "note",
                }
            )
        else:
            who = (p.get("author") or {}).get("name") or "System"
            label = (p.get("part_type") or "event").replace("_", " ")
            entries.append({"kind": "event", "text": f"{who} · {label}", "created_at": p.get("created_at")})
    entries.sort(key=lambda e: e.get("created_at") or 0)
    return entries
