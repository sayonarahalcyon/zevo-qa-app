"""Supabase (Postgres) access layer.

Replaces the Claude artifact's `db` capability (a small NoSQL-style document
store). Tables mirror the original collections 1:1 — see sql/schema.sql:
  agents                 -- learned frontline-agent directory (id = Intercom admin id)
  reviewed                -- tickets marked "reviewed" (id = Intercom conversation id)
  weekly_picks             -- Weekly QA batch state (id = "<agent_id>__<week_start>")
  qa_entries               -- one row per scored QA audit (id = Intercom conversation id)
  historical_qa_entries    -- one-time read-only import from the retired QA Tracker sheet
"""

import streamlit as st
from supabase import create_client, Client


@st.cache_resource(show_spinner=False)
def _create_client() -> Client:
    """Cached only on success — st.cache_resource doesn't memoize a raised
    exception, so a transient failure here (e.g. Secrets not fully synced
    yet during a redeploy) gets retried on the next call instead of being
    stuck forever as a cached None."""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    if not url or not key:
        raise RuntimeError("Supabase URL/key missing in Secrets.")
    return create_client(url, key)


def get_client() -> Client | None:
    try:
        return _create_client()
    except Exception:
        return None


# ---------- agents ----------

def upsert_agent(agent_id: str, name: str, email: str = "") -> str | None:
    """Upserts one agent. Returns None on success, or an error message on
    failure. Callers that want best-effort behavior (e.g. the organic
    auto-learn-from-conversation path) can ignore the return value, same as
    the old .catch(noop) shape; callers that need to tell the user why a
    save didn't work (e.g. the Manage agents panel) should check it."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("agents").upsert(
            {"id": str(agent_id), "name": name, "email": email or ""}
        ).execute()
        return None
    except Exception as e:
        return str(e)


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


def delete_agent(agent_id: str) -> str | None:
    """Deletes one row from the agents directory. Returns None on success, or
    an error message. Used only by the QA Log's Weng-only "Manage agents"
    tool — e.g. removing someone who's left the team. qa_entries and
    weekly_picks store the agent's name directly rather than a live
    reference to this table, so past QA records are untouched."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("agents").delete().eq("id", str(agent_id)).execute()
        return None
    except Exception as e:
        return str(e)


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


def delete_reviewed(ticket_id: str) -> str | None:
    """Clears one ticket's reviewed flag. Returns None on success, or an
    error message. Used only by the QA Log's Weng-only "Delete a QA entry"
    tool, since a reviewed flag (set separately from scoring, via "Mark
    reviewed") is what actually keeps a ticket from being pulled again."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("reviewed").delete().eq("id", str(ticket_id)).execute()
        return None
    except Exception as e:
        return str(e)


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


def delete_qa_entry(ticket_id: str) -> str | None:
    """Deletes one qa_entries row. Returns None on success, or an error
    message. Used only by the QA Log's Weng-only "Delete a QA entry" tool —
    e.g. a test audit accidentally logged against a real ticket, so that
    ticket can be pulled and scored for real."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("qa_entries").delete().eq("id", str(ticket_id)).execute()
        return None
    except Exception as e:
        return str(e)


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
# "Weekly" picks are now keyed by an arbitrary user-chosen [start, end] date
# range rather than a fixed calendar week, but the underlying table/column
# names are unchanged (week_start still holds the range's start date — the
# range's end date is folded into the id instead of needing a schema change).

def week_doc_id(agent_id: str, range_start_iso: str, range_end_iso: str) -> str:
    return f"{agent_id}__{range_start_iso}__{range_end_iso}"


def get_weekly_picks(agent_id: str, range_start_iso: str, range_end_iso: str) -> dict | None:
    db = get_client()
    if not db:
        return None
    try:
        res = (
            db.table("weekly_picks")
            .select("*")
            .eq("id", week_doc_id(agent_id, range_start_iso, range_end_iso))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def save_weekly_picks(agent_id: str, agent_name: str, range_start_iso: str, range_end_iso: str, tickets: list) -> None:
    db = get_client()
    if not db:
        return
    try:
        db.table("weekly_picks").upsert(
            {
                "id": week_doc_id(agent_id, range_start_iso, range_end_iso),
                "agent_id": agent_id,
                "agent_name": agent_name,
                "week_start": range_start_iso,
                "tickets": tickets,
            }
        ).execute()
    except Exception:
        pass


# ---------- historical_qa_entries ----------
# Read-only: one-time import from the retired "2026 - ZEVO QA Tracker v2"
# Google Sheet. Nothing in the app writes to this table — it's a reference
# archive, kept deliberately separate from qa_entries so old sheet rows
# never mix into the live QA Log's dashboard, pass rate, or per-agent rollup.

@st.cache_data(ttl=300, show_spinner=False)
def list_historical_entries() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("historical_qa_entries").select("*").limit(1000).execute()
        return res.data or []
    except Exception:
        return []


def clear_cache() -> None:
    """Call after any write so the next read reflects it immediately."""
    list_agents.clear()
    list_reviewed.clear()
    list_qa_entries.clear()
