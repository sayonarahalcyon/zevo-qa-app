"""Supabase (Postgres) access layer.

Replaces the Claude artifact's `db` capability (a small NoSQL-style document
store). Tables mirror the original collections 1:1 — see sql/schema.sql:
  agents                 -- learned frontline-agent directory (id = Intercom admin id)
  reviewed                -- tickets marked "reviewed" (id = Intercom conversation id)
  weekly_picks             -- Weekly QA batch state (id = "<agent_id>__<week_start>")
  qa_entries               -- one row per scored QA audit (id = Intercom conversation id)
  historical_qa_entries    -- one-time read-only import from the retired QA Tracker sheet
  disputes                 -- agent-submitted questions/disputes from My Dashboard (id = uuid4)
  login_events             -- one row per successful agent / team lead sign-in
  evaluation_signoffs      -- agent sign-off on each evaluation (id = qa_entries.id)
  evaluators               -- phone-only evaluators (Phone Queue sign-in)
  phone_queue              -- phone tickets loaded for evaluation (id = Intercom conversation id)
  calibration_sessions     -- calibration: one phone ticket scored by several evaluators
  calibration_scores       -- each evaluator's calibration score (never counted in stats)
"""

import re
import uuid
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client, Client

from lib.constants import REVIEWER_NAMES as REVIEWER_NAMES_FOR_DB


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


def set_agent_password(agent_id: str, password_hash: str | None) -> str | None:
    """Sets (or, passing None, clears) one agent's My Dashboard password
    hash. Returns None on success, or an error message. Called from the QA
    Log's "Manage agents" panel (a reviewer setting/resetting it) and from
    lib.agent_auth.render_change_password() (an agent changing their own)."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("agents").update({"password_hash": password_hash}).eq("id", str(agent_id)).execute()
        list_agents.clear()
        return None
    except Exception as e:
        return str(e)


def set_agent_team_lead(agent_id: str, team_lead_id: str | None) -> str | None:
    """Assigns (or, passing None, clears) one agent's team lead. Returns None
    on success, or an error message. Called from the QA Log's "Manage
    agents" panel — team_lead_id is the source of truth for which agents
    show up on a given team lead's Team Lead Dashboard rollup."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("agents").update({"team_lead_id": team_lead_id}).eq("id", str(agent_id)).execute()
        list_agents.clear()
        return None
    except Exception as e:
        return str(e)


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


# ---------- team_leads ----------
# Seeded with 3 real team leads (sql/schema.sql / the 2026-10-03 migration),
# but not fixed at 3 — a reviewer can add or remove one from QA Log →
# Manage team leads. Each has their own Team Lead Dashboard sign-in, same
# resettable-bcrypt-password pattern as agents.password_hash. Which agents a
# team lead sees is agents.team_lead_id (see set_agent_team_lead above), not
# anything stored here.

@st.cache_data(ttl=30, show_spinner=False)
def list_team_leads() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("team_leads").select("*").limit(50).execute()
        return res.data or []
    except Exception:
        return []


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "team-lead"


def create_team_lead(name: str) -> tuple[str | None, str | None]:
    """Creates a new team lead row, deriving its id from the name (slugified,
    with a numeric suffix added if that slug is already taken). Returns
    (new_id, None) on success, or (None, error_message) on failure. Called
    from the QA Log's "Manage team leads" panel — a reviewer adding a 4th
    (or more) team lead beyond the 3 seeded ones. No password is set here;
    that's a separate step in the same panel, same as adding an agent."""
    db = get_client()
    if not db:
        return None, "Database is not connected — check the Supabase URL/key in Secrets."
    if not name.strip():
        return None, "Name is required."
    base_slug = _slugify(name)
    existing_ids = {t["id"] for t in list_team_leads()}
    slug = base_slug
    n = 2
    while slug in existing_ids:
        slug = f"{base_slug}-{n}"
        n += 1
    try:
        db.table("team_leads").insert({"id": slug, "name": name.strip()}).execute()
        list_team_leads.clear()
        return slug, None
    except Exception as e:
        return None, str(e)


def delete_team_lead(team_lead_id: str) -> str | None:
    """Deletes one team lead. Returns None on success, or an error message.
    Any agent assigned to them is automatically unassigned rather than
    blocking the delete — agents.team_lead_id's foreign key is ON DELETE SET
    NULL (see sql/schema.sql / the 2026-10-03 migration) — so this also
    clears list_agents' cache, not just list_team_leads'."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("team_leads").delete().eq("id", str(team_lead_id)).execute()
        list_team_leads.clear()
        list_agents.clear()
        return None
    except Exception as e:
        return str(e)


def set_team_lead_password(team_lead_id: str, password_hash: str | None) -> str | None:
    """Sets (or, passing None, clears) one team lead's dashboard password
    hash. Returns None on success, or an error message. Called from the QA
    Log's "Manage team leads" panel (a reviewer setting/resetting it) and
    from lib.team_lead_auth.render_change_password() (a team lead changing
    their own)."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("team_leads").update({"password_hash": password_hash}).eq("id", str(team_lead_id)).execute()
        list_team_leads.clear()
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
    try:
        db.table("qa_entries").upsert(row).execute()
    except Exception as exc:
        # The phone audit's "recording_link" column comes from a SQL migration
        # (sql/migrations/2026_10_19_add_recording_link.sql). If the app is
        # updated before that has been run, still save the audit itself instead
        # of failing; the link is simply not stored until the column exists.
        if "recording_link" in row and "recording_link" in str(exc):
            row.pop("recording_link")
            db.table("qa_entries").upsert(row).execute()
        else:
            raise


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


# ---------- disputes ----------
# Agent-submitted questions/disputes from My Dashboard's inline "Question or
# dispute about this audit?" form (lib/disputes.py) — always tied to one
# qa_entries row via entry_id, so the agent never re-types who they are,
# which ticket it was, or what the score was.

def create_dispute(
    entry_id: str,
    agent_id: str,
    agent_name: str,
    request_type: str,  # "question" | "dispute"
    message: str,
    categories: list[str] | None = None,
    supporting_evidence: str = "",
    is_test: bool = False,
    submitted_by: str | None = None,
) -> str | None:
    """Returns None on success, or an error message on failure. `is_test`
    mirrors qa_entries.is_test — it isn't exposed as a checkbox on the agent
    form (agents never intentionally submit a test dispute), but lets test
    rows created directly (e.g. for demoing the feature) be excluded from
    the Questions & Disputes open/resolved counts, same as test audits are
    excluded from the QA Log's dashboard totals. `submitted_by` (added
    2026-10-03) names whoever actually filed this, when that isn't the
    agent themselves — e.g. a team lead submitting from the Team Lead
    Dashboard's drill-down on the agent's behalf. NULL means the agent
    submitted it themselves, same as before this field existed."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("disputes").insert(
            {
                "id": str(uuid.uuid4()),
                "entry_id": str(entry_id),
                "agent_id": str(agent_id) if agent_id else None,
                "agent_name": agent_name,
                "request_type": request_type,
                "categories": categories or [],
                "message": message,
                "supporting_evidence": supporting_evidence or "",
                "status": "open",
                "is_test": is_test,
                "submitted_by": submitted_by,
            }
        ).execute()
        list_disputes.clear()
        return None
    except Exception as e:
        return str(e)


@st.cache_data(ttl=15, show_spinner=False)
def list_disputes() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("disputes").select("*").order("created_at", desc=True).limit(1000).execute()
        return res.data or []
    except Exception:
        return []


def resolve_dispute(dispute_id: str, reviewer_response: str, resolved_by: str) -> str | None:
    """Marks a question/dispute resolved with the reviewer's written response,
    which the agent then sees on My Dashboard. Returns None on success, or an
    error message."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("disputes").update(
            {
                "status": "resolved",
                "reviewer_response": reviewer_response,
                "resolved_by": resolved_by,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", str(dispute_id)).execute()
        list_disputes.clear()
        return None
    except Exception as e:
        return str(e)


def reopen_dispute(dispute_id: str) -> str | None:
    """Reverts a resolved question/dispute back to open, e.g. if the agent
    isn't satisfied with the response. Returns None on success, or an error
    message."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("disputes").update(
            {"status": "open", "reviewer_response": None, "resolved_by": None, "resolved_at": None}
        ).eq("id", str(dispute_id)).execute()
        list_disputes.clear()
        return None
    except Exception as e:
        return str(e)


# ---------- agent sign-off ----------

@st.cache_data(ttl=15, show_spinner=False)
def list_signoffs() -> list[dict] | None:
    """All sign-off rows, or None when the table can't be read (most likely the
    sign-off SQL hasn't been run yet). None, not [], so lib.signoff can tell
    "feature not switched on" apart from "nobody has signed anything yet" and
    never flags every evaluation as pending by mistake."""
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("evaluation_signoffs").select("*").limit(5000).execute()
        return res.data or []
    except Exception:
        return None


def sign_off(entry_id: str, agent_id: str | None, agent_name: str, comment: str = "") -> str | None:
    """Records (or, after a reviewer edited the evaluation, renews) an agent's
    sign-off. Returns None on success, or an error message."""
    db = get_client()
    if not db:
        return "Database is not connected. Check the Supabase URL/key in Secrets."
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.table("evaluation_signoffs").upsert(
            {
                "entry_id": str(entry_id),
                "agent_id": str(agent_id) if agent_id else None,
                "agent_name": agent_name,
                "status": "signed",
                "signed_at": now,
                "comment": comment or None,
                "updated_at": now,
            }
        ).execute()
        list_signoffs.clear()
        return None
    except Exception as e:
        return str(e)


# ---------- sign-in activity ----------

def record_login(
    role: str,
    person_id: str,
    person_name: str,
    by_reviewer: str | None = None,
    kind: str = "sign_in",
    detail: str = "",
) -> None:
    """Logs one event to login_events: a sign-in, a reviewer's "View as team
    lead", or something a person did afterward (lib/activity.py: page opened,
    period changed, dispute filed, ...). `kind` says which; `detail` is the
    page title, agent name and so on; `by_reviewer` names the reviewer who was
    signed in on that browser session (or who is viewing as the team lead),
    None if no reviewer was. Best-effort and silent: a missing table or column
    (migration not run yet) or a database hiccup must never get in the way of
    someone using the app. If the newer columns don't exist yet, a plain
    sign-in is still recorded without them; other events wait for the SQL."""
    try:
        db = get_client()
        if not db:
            return
        row = {"role": role, "person_id": str(person_id), "person_name": person_name}
        tiers = [
            {**row, "by_reviewer": by_reviewer, "kind": kind, "detail": detail or ""},
            {**row, "by_reviewer": by_reviewer, "kind": kind},
        ]
        done = False
        for attempt in tiers:
            try:
                db.table("login_events").insert(attempt).execute()
                done = True
                break
            except Exception:
                continue
        if not done:
            if kind != "sign_in":
                return
            db.table("login_events").insert(row).execute()
        list_login_events.clear()
    except Exception:
        pass


@st.cache_data(ttl=30, show_spinner=False)
def list_login_events() -> list[dict]:
    """Every recorded sign-in, newest first. Returns [] if the table doesn't
    exist yet. Paged so the 1000-row default API cap can't silently
    undercount."""
    db = get_client()
    if not db:
        return []
    rows: list[dict] = []
    try:
        start = 0
        while True:
            res = (
                db.table("login_events")
                .select("*")
                .order("signed_in_at", desc=True)
                .range(start, start + 999)
                .execute()
            )
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < 1000 or start >= 49000:
                break
            start += 1000
        return rows
    except Exception:
        return rows


# ---------- evaluators (phone-only) ----------
# People who audit phone tickets only, from the Phone Queue page (e.g. a
# third-party evaluator with no Intercom access). Managed by Weng in QA Log ->
# Manage phone evaluators; same resettable bcrypt password pattern as team
# leads. See sql/migrations/2026_11_07_phone_queue_and_evaluators.sql.

@st.cache_data(ttl=30, show_spinner=False)
def list_evaluators() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("evaluators").select("*").limit(50).execute()
        return res.data or []
    except Exception:
        return []


def create_evaluator(name: str) -> tuple[str | None, str | None]:
    """Adds a phone evaluator. Returns (new_id, None) or (None, error)."""
    db = get_client()
    if not db:
        return None, "Database is not connected — check the Supabase URL/key in Secrets."
    if not name.strip():
        return None, "Name is required."
    if name.strip() in REVIEWER_NAMES_FOR_DB:
        return None, "That name is already a reviewer."
    base_slug = _slugify(name)
    existing_ids = {e["id"] for e in list_evaluators()}
    slug = base_slug
    n = 2
    while slug in existing_ids:
        slug = f"{base_slug}-{n}"
        n += 1
    try:
        db.table("evaluators").insert({"id": slug, "name": name.strip()}).execute()
        list_evaluators.clear()
        return slug, None
    except Exception as e:
        return None, str(e)


def delete_evaluator(evaluator_id: str) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("evaluators").delete().eq("id", str(evaluator_id)).execute()
        list_evaluators.clear()
        return None
    except Exception as e:
        return str(e)


def set_evaluator_password(evaluator_id: str, password_hash: str | None) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("evaluators").update({"password_hash": password_hash}).eq("id", str(evaluator_id)).execute()
        list_evaluators.clear()
        return None
    except Exception as e:
        return str(e)


# ---------- phone_queue ----------
# Phone tickets a reviewer loaded for evaluation. Claiming is a conditional
# update (only succeeds while claimed_by is still empty), so two people
# clicking Claim at the same moment can't both get the same ticket.

@st.cache_data(ttl=15, show_spinner=False)
def list_phone_queue() -> list[dict] | None:
    """All queued tickets, or None if the table doesn't exist yet (the SQL
    migration hasn't been run), so the page can say so instead of looking empty."""
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("phone_queue").select("*").limit(2000).execute()
        return res.data or []
    except Exception:
        return None


def add_to_phone_queue(rows: list[dict]) -> str | None:
    """Inserts tickets; a ticket already in the queue is left as it is (its
    claim and notified state are kept). Returns None or an error message."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    if not rows:
        return None
    try:
        db.table("phone_queue").upsert(rows, on_conflict="ticket_id", ignore_duplicates=True).execute()
        list_phone_queue.clear()
        return None
    except Exception as e:
        return str(e)


def remove_from_phone_queue(ticket_id: str) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("phone_queue").delete().eq("ticket_id", str(ticket_id)).execute()
        list_phone_queue.clear()
        return None
    except Exception as e:
        return str(e)


def claim_phone_ticket(ticket_id: str, who: str) -> str | None:
    """Claims a ticket for `who`. Returns None on success, or a message
    (including "already claimed by X") if someone got there first."""
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        res = (
            db.table("phone_queue")
            .update({"claimed_by": who, "claimed_at": datetime.now(timezone.utc).isoformat()})
            .eq("ticket_id", str(ticket_id))
            .is_("claimed_by", "null")
            .execute()
        )
        list_phone_queue.clear()
        if res.data:
            return None
        current = db.table("phone_queue").select("claimed_by").eq("ticket_id", str(ticket_id)).limit(1).execute()
        holder = ((current.data or [{}])[0]).get("claimed_by")
        return f"Already claimed by {holder}." if holder else "This ticket is no longer in the queue."
    except Exception as e:
        return str(e)


def release_phone_ticket(ticket_id: str) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    try:
        db.table("phone_queue").update({"claimed_by": None, "claimed_at": None}).eq("ticket_id", str(ticket_id)).execute()
        list_phone_queue.clear()
        return None
    except Exception as e:
        return str(e)


def mark_phone_tickets_notified(ticket_ids: list[str]) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected — check the Supabase URL/key in Secrets."
    if not ticket_ids:
        return None
    try:
        db.table("phone_queue").update({"notified_at": datetime.now(timezone.utc).isoformat()}).in_(
            "ticket_id", [str(t) for t in ticket_ids]
        ).execute()
        list_phone_queue.clear()
        return None
    except Exception as e:
        return str(e)


# ---------- calibration ----------
# One phone ticket scored independently by several chosen evaluators, to check
# they score consistently. Kept apart from qa_entries on purpose: calibration
# scores never count toward any dashboard, rollup, pass rate or agent view.
# See sql/migrations/2026_11_07b_calibration.sql.

@st.cache_data(ttl=15, show_spinner=False)
def list_calibration_sessions() -> list[dict] | None:
    """All sessions, or None if the tables don't exist yet."""
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("calibration_sessions").select("*").limit(500).execute()
        return res.data or []
    except Exception:
        return None


@st.cache_data(ttl=15, show_spinner=False)
def list_calibration_scores() -> list[dict]:
    db = get_client()
    if not db:
        return []
    try:
        res = db.table("calibration_scores").select("*").limit(5000).execute()
        return res.data or []
    except Exception:
        return []


def create_calibration_session(ticket_id: str, ticket_url: str, agent_name: str, participants: list[str], created_by: str) -> tuple[str | None, str | None]:
    db = get_client()
    if not db:
        return None, "Database is not connected \u2014 check the Supabase URL/key in Secrets."
    sid = str(uuid.uuid4())
    try:
        db.table("calibration_sessions").insert(
            {
                "id": sid,
                "ticket_id": str(ticket_id),
                "ticket_url": ticket_url,
                "agent_name": agent_name,
                "participants": participants,
                "created_by": created_by,
            }
        ).execute()
        list_calibration_sessions.clear()
        return sid, None
    except Exception as e:
        return None, str(e)


def save_calibration_score(session_id: str, evaluator: str, row: dict) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected \u2014 check the Supabase URL/key in Secrets."
    full = {**row, "session_id": session_id, "evaluator": evaluator, "submitted_at": datetime.now(timezone.utc).isoformat()}
    try:
        try:
            db.table("calibration_scores").upsert(full, on_conflict="session_id,evaluator").execute()
        except Exception as exc:
            # "zomp_link" comes from sql/migrations/2026_11_12_calibration_zomp_link.sql.
            # Until that has been run, still save the score, just without the link.
            if "zomp_link" in full and "zomp_link" in str(exc):
                full.pop("zomp_link")
                db.table("calibration_scores").upsert(full, on_conflict="session_id,evaluator").execute()
            else:
                raise
        list_calibration_scores.clear()
        return None
    except Exception as e:
        return str(e)


def close_calibration_session(session_id: str, reopen: bool = False) -> str | None:
    db = get_client()
    if not db:
        return "Database is not connected \u2014 check the Supabase URL/key in Secrets."
    try:
        db.table("calibration_sessions").update(
            {"closed_at": None if reopen else datetime.now(timezone.utc).isoformat()}
        ).eq("id", str(session_id)).execute()
        list_calibration_sessions.clear()
        return None
    except Exception as e:
        return str(e)


def reset_calibration_scores(session_id: str) -> str | None:
    """Clears every score in a session but keeps the session itself, so its
    participants can score the call again."""
    db = get_client()
    if not db:
        return "Database is not connected \u2014 check the Supabase URL/key in Secrets."
    try:
        db.table("calibration_scores").delete().eq("session_id", str(session_id)).execute()
        list_calibration_scores.clear()
        return None
    except Exception as e:
        return str(e)


def delete_calibration_session(session_id: str) -> str | None:
    """Deletes a session and (by cascade) its scores."""
    db = get_client()
    if not db:
        return "Database is not connected \u2014 check the Supabase URL/key in Secrets."
    try:
        db.table("calibration_sessions").delete().eq("id", str(session_id)).execute()
        list_calibration_sessions.clear()
        list_calibration_scores.clear()
        return None
    except Exception as e:
        return str(e)


def clear_cache() -> None:
    """Call after any write so the next read reflects it immediately."""
    list_agents.clear()
    list_team_leads.clear()
    list_reviewed.clear()
    list_qa_entries.clear()
    list_disputes.clear()
    list_login_events.clear()
    list_signoffs.clear()
    list_evaluators.clear()
    list_phone_queue.clear()
    list_calibration_sessions.clear()
    list_calibration_scores.clear()
