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

Besides the audits on the first tab, questions and disputes (the `disputes`
table, including ones a team lead files on an agent's behalf) are mirrored to
two more tabs of the same spreadsheet, kept separate: "Disputes" and
"Questions". Each submission becomes one row when it is filed and the same
row is updated when a reviewer resolves or reopens it (matched on the ID in
column A). The tabs are created automatically if they don't exist yet.
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
    "Channel",
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


@st.cache_resource(show_spinner=False)
def _connect_spreadsheet():
    """The whole backup spreadsheet (every tab), cached only on success like
    _connect_worksheet(). Used for the Disputes and Questions tabs."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa_info = dict(st.secrets["gcp_service_account"])
    sheet_id = st.secrets["qa_backup_sheet_id"]
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(sheet_id)


def _get_worksheet():
    try:
        return _connect_worksheet()
    except Exception:
        return None


def _ensure_header(ws, header=None) -> None:
    """Checked on every save, not cached — so a header missing or out of
    date (a manual edit to the sheet, or a layout change) gets repaired on
    the very next save rather than only once per app restart."""
    header = header or HEADER
    values = ws.get_all_values()
    if not values:
        ws.append_row(header)
        ws.set_basic_filter()
    elif values[0] != header:
        ws.update(values=[header], range_name="A1")
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
        entry.get("channel") or "Chat",
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


# ---------------------------------------------------------------------------
# Questions and disputes (the `disputes` table), one tab each.
# ---------------------------------------------------------------------------

DISPUTES_TAB = "Disputes"
QUESTIONS_TAB = "Questions"

_COMMON_HEAD = ["Submitted At", "Status", "Agent", "Filed By", "Filed By Role", "Ticket ID", "QA Date", "Audit Reviewer"]
_RESPONSE_TAIL = ["Reviewer Response", "Resolved By", "Resolved At", "Test"]

DISPUTE_HEADER = [
    "Dispute ID",
    *_COMMON_HEAD,
    "Original Score",
    "Original Result",
    "Categories",
    "Reason for Dispute",
    "Supporting Evidence",
    *_RESPONSE_TAIL,
]

QUESTION_HEADER = [
    "Question ID",
    *_COMMON_HEAD,
    "Score",
    "Result",
    "Question",
    *_RESPONSE_TAIL,
]


def _tab_for(request_type: str) -> tuple:
    """(tab title, header row) for a disputes-table row's request_type."""
    if request_type == "question":
        return QUESTIONS_TAB, QUESTION_HEADER
    return DISPUTES_TAB, DISPUTE_HEADER


def _dispute_to_row(d: dict, entry: dict | None) -> list:
    """One backup row for a disputes-table record. `entry` is the qa_entries
    row it is about (may be missing if that audit was deleted). Shared by the
    per-submission upsert and the full resync so they cannot drift apart."""
    entry = entry or {}
    filed_by = d.get("submitted_by")
    head = [
        d.get("id", ""),
        d.get("created_at", ""),
        "Resolved" if d.get("status") == "resolved" else "Open",
        d.get("agent_name", ""),
        filed_by or d.get("agent_name", ""),
        "Team lead" if filed_by else "Agent",
        entry.get("ticket_id") or entry.get("id") or d.get("entry_id", ""),
        entry.get("qa_date", ""),
        entry.get("qa_reviewer", ""),
        entry.get("total_score", ""),
        entry.get("result", ""),
    ]
    tail = [
        d.get("reviewer_response") or "",
        d.get("resolved_by") or "",
        d.get("resolved_at") or "",
        "TEST" if d.get("is_test") else "",
    ]
    if d.get("request_type") == "question":
        return [*head, d.get("message", ""), *tail]
    return [*head, ", ".join(d.get("categories") or []), d.get("message", ""), d.get("supporting_evidence") or "", *tail]


def _get_tab(title: str, header: list):
    """The named tab of the backup spreadsheet, created (with its header and
    filter) if it isn't there yet. None if the sheet isn't reachable."""
    try:
        sh = _connect_spreadsheet()
    except Exception:
        return None
    try:
        try:
            ws = sh.worksheet(title)
        except Exception:
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(header))
        _ensure_header(ws, header)
        return ws
    except Exception:
        return None


def upsert_dispute(d: dict, entry: dict | None) -> None:
    """Adds this question/dispute to its tab, or updates its row in place if
    it is already there (a reviewer resolving or reopening it). Never raises:
    a backup failure must not affect the real save to Supabase."""
    try:
        title, header = _tab_for(d.get("request_type"))
        ws = _get_tab(title, header)
        if not ws:
            return
        row = _dispute_to_row(d, entry)
        ids = ws.col_values(1)
        if d.get("id") in ids:
            ws.update(values=[row], range_name=f"A{ids.index(d['id']) + 1}")
        else:
            ws.append_row(row, table_range="A1")
    except Exception:
        pass


def resync_disputes(disputes: list, entries: list) -> tuple:
    """Rewrites both the Disputes and Questions tabs from scratch from the
    given Supabase `disputes` rows. Returns (disputes_written,
    questions_written, error_message); the error is None on success."""
    try:
        by_id = {e.get("id"): e for e in entries}
        ordered = sorted(disputes, key=lambda d: d.get("created_at") or "")
        counts = {}
        for title, header, kind in ((DISPUTES_TAB, DISPUTE_HEADER, "dispute"), (QUESTIONS_TAB, QUESTION_HEADER, "question")):
            ws = _get_tab(title, header)
            if not ws:
                return 0, 0, "Backup sheet isn't configured (missing secrets) or couldn't be reached."
            rows = [
                _dispute_to_row(d, by_id.get(d.get("entry_id")))
                for d in ordered
                if (d.get("request_type") == "question") == (kind == "question")
            ]
            ws.clear()
            ws.append_row(header)
            if rows:
                ws.append_rows(rows, table_range="A1")
            ws.set_basic_filter()
            counts[kind] = len(rows)
        return counts["dispute"], counts["question"], None
    except Exception as exc:
        return 0, 0, str(exc)
