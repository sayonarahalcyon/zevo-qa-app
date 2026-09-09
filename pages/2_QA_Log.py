"""QA Log — dashboard, per-agent rollup, filterable audit log, scoring guide."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import auth, db, sheets_backup, ui
from lib.constants import CRITICAL_ERRORS, DISPUTE_FORM_URL, RUBRIC, RUBRIC_GUIDE, is_excluded_agent_name
from lib.intercom_client import IntercomError, conversation_url, get_conversation, list_admins
from lib.ticket_view import render_ticket
from lib.ui import result_badge_md

st.set_page_config(page_title="QA Log — Ticket QA Sampler", page_icon="🎫", layout="wide")
ui.inject_style()

if not auth.is_signed_in():
    st.title("QA Log")
    st.warning("Sign in to view the QA Log. Head to Home and sign in as one of the three reviewers.")
    st.page_link("pages/0_Home.py", label="🏠 Go to Home to sign in", use_container_width=False)
    st.stop()

ss = st.session_state
ss.setdefault("log_open_ticket_id", None)  # full Intercom conversation transcript
ss.setdefault("log_open_audit_key", None)  # QA scorecard for one audit

entries = db.list_qa_entries()
agents = db.list_agents()
agents_by_id = {a["id"]: a["name"] for a in agents}


def _entry_key(e: dict):
    return e.get("ticket_id") or e.get("id")


if ss.get("log_open_ticket_id"):
    open_id = ss["log_open_ticket_id"]
    if st.button("← Back to QA Log"):
        ss["log_open_ticket_id"] = None
        st.rerun()
    try:
        with st.spinner(f"Loading conversation #{open_id}…"):
            convo = get_conversation(open_id)
        render_ticket(convo, conversation_url(open_id))
    except IntercomError as e:
        st.error(f"Could not load conversation #{open_id}: {e}")
    st.stop()

if ss.get("log_open_audit_key"):
    key = ss["log_open_audit_key"]
    entry = next((e for e in entries if _entry_key(e) == key), None)

    if st.button("← Back to QA Log"):
        ss["log_open_audit_key"] = None
        st.rerun()

    if not entry:
        st.warning("That audit couldn't be found — it may have changed since this list loaded. Go back and try again.")
        st.stop()

    ticket_id = entry.get("ticket_id") or ""
    ticket_url = entry.get("ticket_link") or (conversation_url(ticket_id) if ticket_id else "")

    st.title(f"QA Audit — {entry.get('agent_name') or 'Unknown agent'}")
    b1, b2, b3 = st.columns([2, 2, 3])
    b1.markdown(result_badge_md(entry.get("result", "")), unsafe_allow_html=True)
    b2.markdown(f"**{entry.get('total_score', '—')} / 100**")
    b3.caption(
        f"Reviewed by {entry.get('qa_reviewer') or '—'} · {entry.get('qa_date') or '—'}"
        + (" · 🧪 TEST" if entry.get("is_test") else "")
        + (" · 🚩 ESCALATED" if entry.get("is_escalated") else "")
    )

    m1, m2, m3 = st.columns(3)
    m1.markdown(f"**Ticket:** [{ticket_id or '—'}]({ticket_url})" if ticket_url else f"**Ticket:** {ticket_id or '—'}")
    m2.markdown(f"**Renter/Host:** {entry.get('renter_host') or '—'}")
    m3.markdown(f"**Concern type:** {', '.join(entry.get('concern_types') or []) or '—'}")

    b_cols = st.columns([1, 1, 3])
    if ticket_id and b_cols[0].button("View full ticket conversation"):
        ss["log_open_ticket_id"] = ticket_id
        ss["log_open_audit_key"] = None
        st.rerun()
    if ticket_id and auth.is_signed_in():
        if b_cols[1].button("Edit score", type="primary"):
            # Jumps straight to the ticket's QA form in edit mode (skipping
            # its own read-only summary step) — this is the shortcut so
            # editing a score doesn't require clicking through the full
            # ticket first.
            ss["log_open_ticket_id"] = ticket_id
            ss["log_open_audit_key"] = None
            ss[f"qa_editing_{ticket_id}"] = True
            st.rerun()

    st.divider()
    st.subheader("Scoring breakdown")
    scores = entry.get("scores") or {}
    remarks = entry.get("remarks") or {}
    breakdown_rows = [
        {
            "Category": r["name"],
            "Score": scores.get(r["key"], "—"),
            "Max": r["max"],
            "Remarks": remarks.get(r["key"]) or "",
        }
        for r in RUBRIC
    ]
    st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)

    st.subheader("Critical errors")
    crit = entry.get("critical_errors") or {}
    flagged = [c["label"] for c in CRITICAL_ERRORS if crit.get(c["key"])]
    if flagged:
        for label in flagged:
            st.error(f"🚫 {label}")
    else:
        st.caption("None flagged.")

    st.subheader("Overall comments")
    st.write(entry.get("overall_comments") or "—")

    edit_log = entry.get("edit_log") or []
    if edit_log:
        st.divider()
        st.subheader(f"Edit / dispute history ({len(edit_log)})")
        for i in range(len(edit_log) - 1, -1, -1):
            rev = edit_log[i]
            reason = rev.get("reason") or "—"
            icon = "⚖️" if reason == "Dispute" else "✏️"
            edited_date = (rev.get("edited_at") or "")[:10] or "—"
            prev_score = rev.get("previous_score")
            prev_result = rev.get("previous_result") or "—"
            # The score/result this edit resulted in — either the next edit's
            # "before" snapshot, or (for the most recent edit) the audit's
            # current, live score.
            if i + 1 < len(edit_log):
                after_score = edit_log[i + 1].get("previous_score")
                after_result = edit_log[i + 1].get("previous_result") or "—"
            else:
                after_score = entry.get("total_score")
                after_result = entry.get("result") or "—"
            unchanged = prev_score == after_score and prev_result == after_result
            with st.expander(
                f"{icon} {reason} — edited by {rev.get('edited_by') or '—'} on {edited_date}",
                expanded=(i == len(edit_log) - 1),
            ):
                if reason == "Dispute":
                    st.markdown(f"**Dispute reason:** {rev.get('dispute_reason') or '—'}")
                    st.markdown(f"**Dispute conclusion:** {rev.get('dispute_conclusion') or 'Not yet resolved'}")
                    if unchanged:
                        st.info(
                            f"Dispute reviewed — conclusion: {rev.get('dispute_conclusion') or 'not yet recorded'}. "
                            f"Original score remains the same: "
                            f"{prev_score if prev_score is not None else '—'} / 100 ({prev_result})."
                        )
                    else:
                        st.markdown(
                            f"**Score:** {prev_score if prev_score is not None else '—'} / 100 ({prev_result}) "
                            f"→ {after_score if after_score is not None else '—'} / 100 ({after_result})"
                        )
                else:
                    st.markdown(
                        f"**Score:** {prev_score if prev_score is not None else '—'} / 100 ({prev_result}) "
                        f"→ {after_score if after_score is not None else '—'} / 100 ({after_result})"
                    )
                if rev.get("previous_qa_reviewer") or rev.get("previous_qa_date"):
                    st.caption(
                        f"Originally reviewed by {rev.get('previous_qa_reviewer') or '—'} "
                        f"on {rev.get('previous_qa_date') or '—'}"
                    )
                if rev.get("previous_overall_comments"):
                    st.caption(f"Previous overall comments: {rev['previous_overall_comments']}")

    st.stop()

st.title("QA Log")
st.caption(f"Reviewing as **{auth.current_reviewer()}**")

# ---------- manage agents ----------
# Visible only to Weng — the roster shouldn't be editable by every reviewer,
# same reasoning as the Backup sheet section below.
if auth.current_reviewer() == "Weng Yee":
    # st.rerun() right after a st.success()/st.error() call can wipe the
    # message before it's visible (the rerun starts a fresh script run
    # almost instantly). Stash the outcome in session_state instead and
    # show it on the run right after, above the expander so it can't be
    # missed even if the expander itself collapses on rerun.
    sync_msg = ss.pop("_agent_sync_msg", None)
    if sync_msg:
        kind, text = sync_msg
        (st.success if kind == "ok" else st.error)(text)

    with st.expander("Manage agents"):
        st.caption(
            "Agents are normally added automatically the first time one of their tickets is opened. "
            "Use this only to add someone before that happens, or to bulk-sync the roster from Intercom."
        )

        if st.button("Sync roster from Intercom", use_container_width=True):
            try:
                admins = list_admins()
            except IntercomError as e:
                st.error(f"Could not reach Intercom: {e}")
            else:
                if not admins:
                    st.warning("No admins came back from Intercom — check the access token in Secrets.")
                else:
                    synced = 0
                    failed = []
                    for a in admins:
                        aid, name = a.get("id"), (a.get("name") or "").strip()
                        if aid and name and not is_excluded_agent_name(name):
                            err = db.upsert_agent(aid, name, a.get("email", ""))
                            if err:
                                failed.append(f"{name} ({err})")
                            else:
                                synced += 1
                    db.clear_cache()
                    if failed:
                        detail = "; ".join(failed[:5])
                        if len(failed) > 5:
                            detail += f"; and {len(failed) - 5} more"
                        ss["_agent_sync_msg"] = (
                            "error",
                            f"Synced {synced} agent(s), but {len(failed)} failed to save: {detail}",
                        )
                    else:
                        ss["_agent_sync_msg"] = ("ok", f"Synced {synced} agent(s) from Intercom.")
                    st.rerun()

        st.markdown("**Add one manually**")
        with st.form("add_agent_form", clear_on_submit=True):
            new_name = st.text_input("Name")
            new_id = st.text_input("Intercom admin ID (numeric — find it under Settings → Teammates)")
            new_email = st.text_input("Email (optional)")
            submitted = st.form_submit_button("Add agent")
        if submitted:
            if not new_name.strip() or not new_id.strip():
                st.error("Name and Intercom admin ID are both required.")
            elif not new_id.strip().isdigit():
                st.error("Intercom admin ID should be numeric.")
            else:
                err = db.upsert_agent(new_id.strip(), new_name.strip(), new_email.strip())
                if err:
                    st.error(f"Could not save {new_name.strip()}: {err}")
                else:
                    db.clear_cache()
                    ss["_agent_sync_msg"] = ("ok", f"Added {new_name.strip()}.")
                    st.rerun()

# ---------- backup sheet ----------
# Visible only to Weng — the other reviewers don't need this control, and a
# full sheet wipe/rewrite is destructive enough that it shouldn't be one
# click away for everyone with edit access.
if auth.current_reviewer() == "Weng Yee":
    backup_msg = ss.pop("_backup_sync_msg", None)
    if backup_msg:
        kind, text = backup_msg
        (st.success if kind == "ok" else st.error)(text)

    with st.expander("Backup sheet"):
        st.caption(
            "New audits are mirrored to the Google Sheet backup automatically. Use this to "
            "rebuild the whole sheet from Supabase — for entries saved while the backup "
            "sheet's layout was out of date, or before it was configured. It also turns on "
            "column filters (Result, Escalated, Agent, Date, etc.) on the sheet."
        )
        if st.button("Resync all audits to backup sheet", use_container_width=True):
            count, err = sheets_backup.resync_all_entries(entries)
            if err:
                ss["_backup_sync_msg"] = ("error", f"Could not resync the backup sheet: {err}")
            else:
                ss["_backup_sync_msg"] = (
                    "ok",
                    f"Resynced {count} audit(s) to the backup sheet and turned on column filters.",
                )
            st.rerun()

# ---------- dashboard ----------
# Entries flagged "🧪 Mark as a test audit" in the form are excluded from
# these totals and the per-agent rollup below, so a test submission never
# skews real numbers — they still show up in the Audit log table further
# down (with a Test marker) so they stay inspectable.
metric_entries = [e for e in entries if not e.get("is_test")]
test_count = len(entries) - len(metric_entries)

total = len(metric_entries)
counts = {"PASS": 0, "COACHING": 0, "FAIL": 0, "AUTO FAIL": 0}
score_sum = 0
for e in metric_entries:
    if e.get("result") in counts:
        counts[e["result"]] += 1
    score_sum += e.get("total_score") or 0
avg_score = round(score_sum / total, 1) if total else None
pass_rate = round(counts["PASS"] / total * 100, 1) if total else None

if test_count:
    st.caption(f"🧪 {test_count} test audit{'s' if test_count != 1 else ''} excluded from the totals below.")

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Audits", total)
c2.metric("Pass", counts["PASS"])
c3.metric("Coaching", counts["COACHING"])
c4.metric("Fail", counts["FAIL"] + counts["AUTO FAIL"])
c5.metric("Avg Score", f"{avg_score}" if avg_score is not None else "—")
c6.metric("Pass Rate", f"{pass_rate}%" if pass_rate is not None else "—")

st.divider()

# ---------- per-agent rollup ----------
st.subheader("Per-agent rollup")
today = date.today()
week_monday = today - timedelta(days=today.weekday())
week_sunday = week_monday + timedelta(days=6)

rollup_rows = []
for aid, name in sorted(agents_by_id.items(), key=lambda kv: kv[1].lower()):
    mine = [e for e in metric_entries if e.get("agent_id") == aid or (e.get("agent_name") or "").lower() == name.lower()]
    avg = round(sum(e.get("total_score") or 0 for e in mine) / len(mine), 1) if mine else None
    week_count = sum(
        1 for e in mine if e.get("qa_date") and week_monday.isoformat() <= e["qa_date"] <= week_sunday.isoformat()
    )
    rollup_rows.append(
        {
            "Agent": name,
            "Audits": len(mine),
            "Avg Score": avg if avg is not None else "—",
            "Status": ("Pass" if (avg or 0) >= 85 else "Fail") if avg is not None else "—",
            "This week (of 3)": f"{week_count} / 3",
        }
    )

if rollup_rows:
    st.dataframe(pd.DataFrame(rollup_rows), use_container_width=True, hide_index=True)
else:
    st.caption("No agents in the directory yet — they're learned automatically as tickets are opened.")

st.divider()

# ---------- filterable audit log ----------
st.subheader("Audit log")
f1, f2, f3, f4 = st.columns([1, 1, 1.3, 1.6])
agent_filter = f1.selectbox("Agent", ["All agents"] + sorted(agents_by_id.values()))
result_filter = f2.selectbox("Result", ["All results", "PASS", "COACHING", "FAIL", "AUTO FAIL"])
q_filter = f3.text_input("Search concern / comments…")
date_range = f4.date_input("Date range", value=(), format="YYYY-MM-DD")

filtered = []
for e in entries:
    if agent_filter != "All agents" and e.get("agent_name") != agent_filter:
        continue
    if result_filter != "All results" and e.get("result") != result_filter:
        continue
    if q_filter:
        hay = f"{e.get('agent_name','')} {' '.join(e.get('concern_types') or [])} {e.get('overall_comments','')}".lower()
        if q_filter.lower() not in hay:
            continue
    if len(date_range) == 2:
        qa_date = e.get("qa_date") or ""
        if not (date_range[0].isoformat() <= qa_date <= date_range[1].isoformat()):
            continue
    filtered.append(e)
filtered.sort(key=lambda e: (e.get("qa_date") or "", e.get("updated_at") or ""), reverse=True)

if filtered:
    st.caption("Click View to see an audit's scores and feedback. Click the ticket number to open it in Intercom.")

    # Built as manual rows (not st.dataframe row-selection) on purpose: the
    # dataframe's built-in row selection only fires when the tiny checkbox
    # in the leftmost column is clicked, not when clicking the row's text —
    # confusing since nothing here looks like a checkbox column. A plain
    # button per row is unambiguous and always clickable.
    row_widths = [1, 1.6, 1.3, 1.4, 0.6, 1, 1.1, 0.5, 0.6, 0.7, 0.8]
    h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11 = st.columns(row_widths)
    for h, label in zip(
        (h1, h2, h3, h4, h5, h6, h7, h8, h9, h10),
        ("Date", "Agent", "Ticket", "Concern", "Total", "Result", "Reviewer", "Test", "Escalated", "Disputed"),
    ):
        h.markdown(f"**{label}**")

    shown = filtered[:300]
    for e in shown:
        ticket_id = e.get("ticket_id") or ""
        ticket_url = e.get("ticket_link") or (conversation_url(ticket_id) if ticket_id else "")
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11 = st.columns(row_widths)
        c1.write(e.get("qa_date", "") or "—")
        c2.write(e.get("agent_name", "") or "—")
        c3.markdown(f"[{ticket_id}]({ticket_url})" if ticket_url else (ticket_id or "—"))
        c4.write(", ".join(e.get("concern_types") or []) or "—")
        c5.write(e.get("total_score") if e.get("total_score") is not None else "—")
        c6.markdown(result_badge_md(e.get("result", "")), unsafe_allow_html=True)
        c7.write(e.get("qa_reviewer", "") or "—")
        c8.write("🧪" if e.get("is_test") else "")
        c9.write("🚩" if e.get("is_escalated") else "")
        c10.write("⚖️" if any((h.get("reason") or "") == "Dispute" for h in (e.get("edit_log") or [])) else "")
        if c11.button("View", key=f"view_audit_{_entry_key(e)}", use_container_width=True):
            ss["log_open_audit_key"] = _entry_key(e)
            st.rerun()

    if len(filtered) > 300:
        st.caption(f"Showing the most recent 300 of {len(filtered)} matching audits.")
else:
    st.caption("No audits match these filters yet.")

st.divider()

# ---------- scoring guide ----------
st.subheader("Scoring guide")
with st.expander("Scoring rubric (5 categories, 100 points)"):
    for r in RUBRIC:
        st.markdown(f"**{r['name']}** (max {r['max']})")
        st.caption(RUBRIC_GUIDE[r["key"]])

with st.expander('Critical errors (any = automatic FAIL)'):
    for c in CRITICAL_ERRORS:
        st.markdown(f"**{c['label']}**")
        st.caption(c["desc"])

with st.expander("Result thresholds"):
    st.markdown(
        "**PASS** — total score 85 or higher, no critical errors.  \n"
        "**COACHING** — total score 70–84, no critical errors.  \n"
        "**FAIL** — total score below 70.  \n"
        "**AUTO FAIL** — any critical error, regardless of total score."
    )

with st.expander("Dispute a score"):
    st.markdown(f"Agents can dispute a QA score using the [QA Audit Dispute Form]({DISPUTE_FORM_URL}).")
