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
# The Calls API (call details, recording, transcript) and the call id on a
# conversation's call_summary part are only in newer API versions (2.17 per
# Intercom's changelog), so call-related requests send this version instead.
# Everything else stays on INTERCOM_VERSION, which is what the rest of the app
# was written and checked against.
CALLS_API_VERSION = "2.17"


class IntercomError(Exception):
    def __init__(self, message: str, code: str = "tool_error"):
        super().__init__(message)
        self.code = code


def _token() -> str | None:
    try:
        return st.secrets["intercom"]["access_token"]
    except Exception:
        return None


def _headers(version: str = INTERCOM_VERSION) -> dict:
    token = _token()
    if not token:
        raise IntercomError("Intercom is not connected — add the access token in Secrets.", "server_not_connected")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": version,
    }


def _to_epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day).timestamp())


def _raise_for_status(resp) -> None:
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


def _send(method: str, path: str, version: str = INTERCOM_VERSION, **kwargs):
    try:
        return requests.request(method, f"{API_BASE}{path}", headers=_headers(version), timeout=30, **kwargs)
    except requests.RequestException as e:
        raise IntercomError(f"Could not reach Intercom: {e}", "server_unavailable")


def _request(method: str, path: str, version: str = INTERCOM_VERSION, **kwargs) -> dict:
    resp = _send(method, path, version, **kwargs)
    _raise_for_status(resp)
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
    # Filtered on when the conversation was actually closed (statistics.last_close_at),
    # not when it was first created — a ticket a customer opens on Monday but an
    # agent doesn't close until Wednesday should count in a Wed-only range.
    if start_date:
        clauses.append({"field": "statistics.last_close_at", "operator": ">", "value": _to_epoch(start_date)})
    if end_date:
        clauses.append({"field": "statistics.last_close_at", "operator": "<", "value": _to_epoch(end_date) + 86400})
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
def list_contact_notes(contact_id: str, max_pages: int = 5) -> list[dict]:
    """The "User notes" on a contact (the notes in the Intercom sidebar, not
    internal notes inside a conversation), newest first. Each note is
    {id, created_at, body (HTML), author {id, name, ...}}."""
    notes, page = [], 1
    while page <= max_pages:
        payload = _request("GET", f"/contacts/{contact_id}/notes", params={"per_page": 50, "page": page})
        notes.extend(payload.get("data") or [])
        pages = payload.get("pages") or {}
        if not pages.get("next") or page >= int(pages.get("total_pages") or page):
            break
        page += 1
    notes.sort(key=lambda n: n.get("created_at") or 0, reverse=True)
    return notes


@st.cache_data(ttl=300, show_spinner=False)
def list_admins() -> list[dict]:
    """Optional roster helper (the app primarily learns agents organically
    from conversations as they're opened, per the original design)."""
    payload = _request("GET", "/admins")
    return payload.get("admins", [])


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


# ---------- phone calls ----------
# A phone ticket's call shows up in the conversation as a "call_summary" part
# whose event_details.call_id is the id the Calls API uses. From that id the
# app can get the recording (Intercom answers with a redirect to a signed,
# short-lived audio URL) and the transcript, using the app's own access token.
# That is what lets someone with no Intercom login (a third-party evaluator)
# listen to the call inside the QA App.

def find_call_ids(convo: dict) -> list[str]:
    """Call ids found on a conversation's parts, oldest first, no duplicates."""
    ids = []
    parts = ((convo.get("conversation_parts") or {}).get("conversation_parts")) or []
    for p in parts:
        details = p.get("event_details") or {}
        cid = details.get("call_id")
        if cid and str(cid) not in ids:
            ids.append(str(cid))
    return ids


@st.cache_data(ttl=600, show_spinner=False)
def get_call_ids(conversation_id: str) -> list[str]:
    """Fetches the conversation with the newer API version (the one that
    includes call ids on call_summary parts) and returns its call ids."""
    convo = _request("GET", f"/conversations/{conversation_id}", version=CALLS_API_VERSION)
    return find_call_ids(convo)


@st.cache_data(ttl=600, show_spinner=False)
def get_call(call_id: str) -> dict:
    return _request("GET", f"/calls/{call_id}", version=CALLS_API_VERSION)


@st.cache_data(ttl=240, show_spinner=False)
def get_call_recording_url(call_id: str) -> str | None:
    """The signed URL of the call's recording, or None if the call has none.
    Intercom answers GET /calls/{id}/recording with a 302 to a signed URL; it
    is short-lived, so it is cached for a few minutes only."""
    resp = _send("GET", f"/calls/{call_id}/recording", version=CALLS_API_VERSION, allow_redirects=False)
    if resp.status_code == 404:
        return None
    if resp.status_code in (301, 302, 303, 307, 308):
        return resp.headers.get("Location") or None
    _raise_for_status(resp)
    # Not a redirect but a success: a newer API might return JSON with the URL.
    try:
        data = resp.json()
        return data.get("url") or data.get("recording_url")
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def get_call_recording_bytes(call_id: str) -> tuple[bytes, str] | None:
    """Fallback when the browser can't play the signed URL directly: the app
    downloads the audio itself and hands the bytes to the player."""
    url = get_call_recording_url(call_id)
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=60)
    except requests.RequestException as e:
        raise IntercomError(f"Could not download the recording: {e}", "server_unavailable")
    if resp.status_code >= 400:
        raise IntercomError(f"Recording download returned HTTP {resp.status_code}.", "tool_error")
    return resp.content, (resp.headers.get("Content-Type") or "audio/mpeg").split(";")[0]


@st.cache_data(ttl=600, show_spinner=False)
def get_call_transcript(call_id: str) -> str | list | None:
    """The call's transcript: plain text, or a list of turns if Intercom
    answers with JSON. None if the call has no transcript. Redirects (to a
    signed file URL) are followed; requests drops the Authorization header
    when a redirect goes to another host."""
    resp = _send("GET", f"/calls/{call_id}/transcript", version=CALLS_API_VERSION)
    if resp.status_code == 404:
        return None
    _raise_for_status(resp)
    ctype = resp.headers.get("Content-Type") or ""
    if "json" in ctype:
        try:
            data = resp.json()
        except Exception:
            return resp.text
        if isinstance(data, dict):
            for key in ("transcript", "turns", "data", "entries"):
                if isinstance(data.get(key), (list, str)):
                    return data[key]
        return data
    return resp.text
