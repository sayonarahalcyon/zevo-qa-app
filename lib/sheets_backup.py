"""Best-effort mirror of every saved QA audit into a separate Google Sheet.

This is a fresh, live backup sheet — distinct from the retired "2026 - ZEVO
QA Tracker v2" sheet imported once into the Historical Log. Nothing reads
from this sheet; it exists purely as an off-Supabase copy of qa_entries,
appended to on every save.

Requires a Google Cloud service account with the Sheets API enabled, shared
as an Editor on the target spreadsheet, with its key and the spreadsheet id
in Streamlit secrets. qa_backup_sheet_id must be a top-level secret — in
TOML, a key only stays top-level if nothing above it is a [section] header
with no other top-level header in between, so the safest place for it is
the very first line of the secrets file, before any [section]:

    qa_backup_sheet_id = "the spreadsheet id from its URL"

    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "...@....iam.gserviceaccount.com"
    client_id = "..."
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url = "..."

Without those secrets configured, backup_qa_entry() silently no-ops — the
real save to Supabase (the source of truth) never depends on this.
"""

import streamlit as st

from lib.constants import RUBRIC

RUBRIC_HEADERS = [h for r in RUBRIC for h in (r["name"], f"{r['name']} Remarks")]

HEADER = [
    "Saved At",
    "Ticket ID",
    "Agent",
    "QA Date",
    "Reviewer",
    *RUBRIC_HEADERS,
    "Total Score",
    "Result",
    "Concern Types",
    "Renter/Host",
    "Critical Errors",
    "Overall Comments",
    "Ticket Link",
    "ZOMP Link",
    "Test",
    "Escalated",
]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@st.cache_resource(show_spinner=False)
def _connect_worksheet():
    """Cached only on success (same pattern as lib/db.py's Supabase client)
    so a transient failure — or secrets not filled in yet — gets retried on
    the next call instead of being stuck as a cached None forever.

    Deliberately does NOT check the header row — this connection is cached
    for the lifetime of the app process, so a check made only here would
    silently go stale the moment someone edits the sheet by hand (clearing
    rows, say) without the app also restarting. See _ensure_header(), which
    runs on every save instead."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa_info = dict(st.secrets["gcp_service_account"])
    sheet_id = st.secrets["qa_backup_sheet_id"]
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id).sheet1


def _get_worksheet():
    try:
        return _connect_worksheet()
    except Exception:
        return None


def _ensure_header(ws) -> None:
    """Checked on every save, not cached — so a header missing or out of
    date (a manual edit to the sheet, or a layout change) gets repaired on
    the very next save rather than only once per app restart."""
    values = ws.get_all_values()
    if not values:
        ws.append_row(HEADER)
        ws.set_basic_filter()
    elif values[0] != HEADER:
        ws.update("A1", [HEADER])
        ws.set_basic_filter()


def _entry_to_row(ticket_id: str, entry: dict) -> list:
    """Builds one backup-sheet row from a qa_entries record. Shared by
    backup_qa_entry() (one row per save) and resync_all_entries() (a full
    rebuild), so the two paths can never drift apart."""
    entry_scores = entry.get("scores") or {}
    entry_remarks = entry.get("remarks") or {}
    return [
        entry.get("updated_at", ""),
        str(ticket_id),
        entry.get("agent_name", ""),
        entry.get("qa_date", ""),
        entry.get("qa_reviewer", ""),
        *[v for r in RUBRIC for v in (entry_scores.get(r["key"], ""), entry_remarks.get(r["key"], ""))],
        entry.get("total_score", ""),
        entry.get("result", ""),
        ", ".join(entry.get("concern_types") or []),
        entry.get("renter_host", ""),
        ", ".join(k for k, v in (entry.get("critical_errors") or {}).items() if v),
        entry.get("overall_comments", ""),
        entry.get("ticket_link", ""),
        entry.get("zomp_link", ""),
        "TEST" if entry.get("is_test") else "",
        "ESCALATED" if entry.get("is_escalated") else "",
    ]


def backup_qa_entry(ticket_id: str, entry: dict) -> None:
    """Appends one row mirroring a saved QA audit. Never raises — a backup
    failure must not block or roll back the real save to Supabase."""
    ws = _get_worksheet()
    if not ws:
        return
    try:
        _ensure_header(ws)
        ws.append_row(_entry_to_row(ticket_id, entry), table_range="A1")
    except Exception:
        pass


def resync_all_entries(entries: list) -> tuple:
    """Wipes the backup sheet and rewrites it from scratch using the given
    Supabase qa_entries rows. This is how audits saved while the sheet's
    layout was out of date (or before it was configured at all) end up
    backed up too. Supabase remains the source of truth throughout — this
    only rebuilds the mirror. Returns (rows_written, error_message); the
    error is None on success."""
    ws = _get_worksheet()
    if not ws:
        return 0, "Backup sheet isn't configured (missing secrets)."
    try:
        ordered = sorted(entries, key=lambda e: e.get("updated_at") or e.get("created_at") or "")
        rows = [_entry_to_row(e.get("ticket_id") or e.get("id"), e) for e in ordered]
        ws.clear()
        ws.append_row(HEADER)
        if rows:
            ws.append_rows(rows, table_range="A1")
        ws.set_basic_filter()
        return len(rows), None
    except Exception as exc:
        return 0, str(exc)
