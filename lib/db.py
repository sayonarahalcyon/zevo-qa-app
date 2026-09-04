"""Supabase (Postgres) access layer.

Replaces the Claude artifact's `db` capability (a small NoSQL-style document
store). Tables mirror the original collections 1:1 — see sql/schema.sql:
  agents        -- learned frontline-agent directory (id = Intercom admin id)
  reviewed      -- tickets marked "reviewed" (id = Intercom conversation id)
  weekly_picks  -- Weekly QA batch state (id = "<agent_id>__<week_start>")
  qa_entries    -- one row per scored QA audit (id = Intercom conversation id)
"""

import streamlit as st
from supabase import create_client, Client


@st.cache_resource(show_spinner=False)
def get_client() -> Client | None:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
    except Exception:
        return None
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# ---------- agents ----------

def upsert_agent(agent_id: str, name: str, email: str = "") -> None:
    db = get_client()
    if not db:
        return
    try:
        db.table("agents").upsert(
            {"id": str(agent_id), "name": name, "email": email or ""}
        ).execute()
    except Exception:
        pass  # best-effort, mirrors the original artifact's .catch(noop)


@st.cache_data(ttl=30, show_spinner=False)
def list_agents() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("agents").select("*").limit(500).execute()
        return res.data or []
    except Exception:
        return []


# ---------- reviewed ----------

def mark_reviewed(ticket_id: str, subject: str, state: str, url: str) -> None:
    db = get_client()
    if not db:
        return
    try:
        db.table("reviewed").upsert(
            {
                "id": str(ticket_id),
                "subject": subject,
                "state": state or "",
                "url": url,
            }
        ).execute()
    except Exception:
        pass


@st.cache_data(ttl=15, show_spinner=False)
def list_reviewed() -> dict:
    """Returns {ticket_id: row}."""
    db = get_client()
    if not db:
        return {}
    try:
        res = db.table("reviewed").select("*").order("reviewed_at", desc=True).limit(1000).execute()
        return {row["id"]: row for row in (res.data or [])}
    except Exception:
        return {}


# ---------- qa_entries ----------

def get_qa_entry(ticket_id: str) -> dict | None:
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("qa_entries").select("*").eq("id", str(ticket_id)).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def save_qa_entry(ticket_id: str, entry: dict) -> None:
    db = get_client()
    if not db:
        raise RuntimeError("QA log is unavailable right now — data can't be saved.")
    row = dict(entry)
    row["id"] = str(ticket_id)
    db.table("qa_entries").upsert(row).execute()


@st.cache_data(ttl=15, show_spinner=False)
def list_qa_entries() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("qa_entries").select("*").limit(2000).execute()
        return res.data or []
    except Exception:
        return []


# ---------- weekly_picks ----------

def week_doc_id(agent_id: str, week_start_iso: str) -> str:
    return f"{agent_id}__{week_start_iso}"


def get_weekly_picks(agent_id: str, week_start_iso: str) -> dict | None:
    db = get_client()
    if not db:
        return None
    try:
        res = (
            db.table("weekly_picks")
            .select("*")
            .eq("id", week_doc_id(agent_id, week_start_iso))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def save_weekly_picks(agent_id: str, agent_name: str, week_start_iso: str, tickets: list) -> None:
    db = get_client()
    if not db:
        return
    try:
        db.table("weekly_picks").upsert(
            {
                "id": week_doc_id(agent_id, week_start_iso),
                "agent_id": agent_id,
                "agent_name": agent_name,
                "week_start": week_start_iso,
                "tickets": tickets,
            }
        ).execute()
    except Exception:
        pass


def clear_cache() -> None:
    """Call after any write so the next read reflects it immediately."""
    list_agents.clear()
    list_reviewed.clear()
    list_qa_entries.clear()
