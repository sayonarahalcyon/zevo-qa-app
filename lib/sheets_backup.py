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
    the next call instead of being stuck as a cached None forever."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa_info = dict(st.secrets["gcp_service_account"])
    sheet_id = st.secrets["qa_backup_sheet_id"]
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(sheet_id).sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(HEADER)
    elif values[0] != HEADER:
        # Layout changed (e.g. rubric columns added) — fix the header row in
        # place. Rows already appended under the old header are left as-is;
        # only new saves after this point fill the new columns.
        ws.update("A1", [HEADER])
    return ws


def _get_worksheet():
    try:
        return _connect_worksheet()
    except Exception:
        return None


def backup_qa_entry(ticket_id: str, entry: dict) -> None:
    """Appends one row mirroring a saved QA audit. Never raises — a backup
    failure must not block or roll back the real save to Supabase."""
    ws = _get_worksheet()
    if not ws:
        return
    try:
        entry_scores = entry.get("scores") or {}
        entry_remarks = entry.get("remarks") or {}
        row = [
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
        ws.append_row(row)
    except Exception:
        pass
