"""The QA audit form/summary, mounted below any opened ticket.

One audit per ticket; editable afterward by a signed-in reviewer. Mirrors
the original Claude artifact's form field-for-field.

Editing an already-saved audit is treated as a distinct, logged event —
see the "edit_log" handling in _render_form()/render() below — because in
practice a score only gets reopened after it's been saved for one of two
reasons: the agent or host disputed it, or a reviewer is correcting a
mistake. Either way that's worth a durable trail: who changed it, when,
why, and what it looked like before.
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from lib import auth, db, sheets_backup
from lib.constants import (
    CHANNEL_OPTIONS,
    CONCERN_TYPES,
    RENTER_HOST_OPTIONS,
    compute_result,
    compute_total,
    critical_errors_for,
    rubric_for,
)
from lib.ui import result_badge_md

EDIT_REASONS = [
    "Dispute — agent or TL disagreed with the score",
    "Reviewer correction (no dispute)",
    "Other",
]


def _agent_options() -> list[str]:
    return sorted({a["name"] for a in db.list_agents() if a.get("name")})


def render(convo: dict, ticket_url: str, guessed_agent_name: str, default_escalated: bool = False) -> None:
    ticket_id = str(convo["id"])
    existing = db.get_qa_entry(ticket_id)
    editing_key = f"qa_editing_{ticket_id}"

    if existing and not st.session_state.get(editing_key):
        _render_summary(ticket_id, existing, editing_key)
        return

    _render_form(ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key, default_escalated)


def _render_summary(ticket_id: str, qa: dict, editing_key: str) -> None:
    st.divider()
    st.subheader("QA Audit")
    cols = st.columns([2, 2, 3, 1])
    cols[0].markdown(result_badge_md(qa.get("result", "")), unsafe_allow_html=True)
    cols[1].markdown(f"**{qa.get('total_score', '—')} / 100**")
    cols[2].caption(
        f"{qa.get('agent_name', '')} · reviewed by {qa.get('qa_reviewer', '—')} · {qa.get('qa_date', '')}"
        + (" · 🧪 TEST" if qa.get("is_test") else "")
        + (" · 🚩 ESCALATED" if qa.get("is_escalated") else "")
        + (" · 📞 PHONE" if (qa.get("channel") or "Chat") == "Phone" else "")
    )
    edit_log = qa.get("edit_log") or []
    if edit_log:
        last = edit_log[-1]
        disputed = any((e.get("reason") or "") == "Dispute" for e in edit_log)
        prev_score = last.get("previous_score")
        cur_score = qa.get("total_score")
        if prev_score is not None and cur_score is not None:
            score_note = (
                f" · score unchanged at {cur_score}/100"
                if prev_score == cur_score
                else f" · {prev_score} → {cur_score}/100"
            )
        else:
            score_note = ""
        st.caption(
            (f"⚖️ Disputed — e" if disputed else "✏️ E")
            + f"dited {len(edit_log)}x · last by {last.get('edited_by') or '—'} "
            f"on {_fmt_date(last.get('edited_at'))} ({last.get('reason', '—')}){score_note}"
        )
    if auth.is_signed_in():
        if cols[3].button("Edit score", key=f"edit_{ticket_id}"):
            st.session_state[editing_key] = True
            st.rerun()
    else:
        cols[3].caption("Sign in to edit")


def _render_form(ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key, default_escalated: bool = False) -> None:
    st.divider()
    header_cols = st.columns([4, 1])
    header_cols[0].subheader("QA Audit" + (" — editing" if existing else ""))
    if existing and header_cols[1].button("Cancel", key=f"cancel_{ticket_id}"):
        st.session_state[editing_key] = False
        st.rerun()

    signed_in = auth.is_signed_in()
    if not signed_in:
        st.info('Sign in as Erwin, Weng, or Kristine in the sidebar to submit or edit a QA audit.')

    agent_roster = _agent_options()
    default_agent = (existing or {}).get("agent_name") or guessed_agent_name or ""

    c1, c2 = st.columns(2)
    with c1:
        agent_name = st.text_input(
            "Agent Name",
            value=default_agent,
            key=f"agent_{ticket_id}",
            help=f"Known agents: {', '.join(agent_roster)}" if agent_roster else None,
            disabled=not signed_in,
        )
    with c2:
        qa_date = st.date_input(
            "QA Date",
            value=_parse_date((existing or {}).get("qa_date")) or date.today(),
            key=f"date_{ticket_id}",
            disabled=not signed_in,
        )

    # Channel comes first because it decides which rubric and which critical
    # errors the rest of the form shows: Chat audits use the five-category
    # chat rubric, Phone audits the six-category phone rubric. Both are scored
    # out of 100 with the same result thresholds.
    #
    # (An audit tagged Phone before the phone rubric existed carries chat-rubric
    # scores. Opening it for edit shows the phone rubric, since it is a phone
    # call, starting from the lowest level in each category; what it was scored
    # on before is kept in the edit history.)
    ch1, ch2 = st.columns(2)
    with ch1:
        channel = st.selectbox(
            "Channel",
            CHANNEL_OPTIONS,
            index=_safe_index(CHANNEL_OPTIONS, (existing or {}).get("channel") or "Chat"),
            key=f"channel_{ticket_id}",
            help="Which support channel this audit came from. It decides which scoring rubric is used, shows as a tag, and is filterable in the Audit log.",
            disabled=not signed_in,
        )
    with ch2:
        recording_link = ""
        if channel == "Phone":
            recording_link = st.text_input(
                "Call recording link",
                value=(existing or {}).get("recording_link") or "",
                key=f"recording_{ticket_id}",
                help="Phone audits are scored from the call recording, not a transcript, because tone, pace and silence do not show in writing.",
                disabled=not signed_in,
            )
    rubric = rubric_for(channel)

    ticket_link = st.text_input(
        "Ticket Link", value=(existing or {}).get("ticket_link") or ticket_url, key=f"link_{ticket_id}", disabled=not signed_in
    )
    c3, c4 = st.columns(2)
    with c3:
        zomp_link = st.text_input(
            "ZOMP Link", value=(existing or {}).get("zomp_link") or "", key=f"zomp_{ticket_id}", disabled=not signed_in
        )
    with c4:
        renter_host = st.selectbox(
            "Renter / Host",
            RENTER_HOST_OPTIONS,
            index=_safe_index(RENTER_HOST_OPTIONS, (existing or {}).get("renter_host")),
            key=f"rh_{ticket_id}",
            disabled=not signed_in,
        )

    concern_types = st.multiselect(
        "Concern Type (select all that apply)",
        CONCERN_TYPES,
        default=(existing or {}).get("concern_types") or [],
        key=f"concern_{ticket_id}",
        disabled=not signed_in,
    )

    st.markdown("**Scoring rubric**" if channel != "Phone" else "**Scoring rubric (phone)**")
    if channel == "Phone":
        st.caption(
            "Score from the call recording. Check the call's Intercom/ZOMP notes when scoring Documentation."
        )
    scores = {}
    remarks = {}
    existing_scores = (existing or {}).get("scores") or {}
    existing_remarks = (existing or {}).get("remarks") or {}
    for r in rubric:
        rc1, rc2 = st.columns([1, 2])
        with rc1:
            st.caption(f"{r['name']} (max {r['max']})")
            default_val = existing_scores.get(r["key"])
            if r.get("options"):
                idx = r["options"].index(default_val) if default_val in r["options"] else 0
                scores[r["key"]] = st.radio(
                    r["key"],
                    r["options"],
                    index=idx,
                    key=f"score_{channel}_{r['key']}_{ticket_id}",
                    horizontal=True,
                    disabled=not signed_in,
                    label_visibility="collapsed",
                )
            else:
                try:
                    start = min(max(int(default_val), 0), r["max"])
                except (TypeError, ValueError):
                    start = 0
                scores[r["key"]] = st.number_input(
                    r["key"],
                    min_value=0,
                    max_value=r["max"],
                    value=start,
                    step=1,
                    key=f"score_{channel}_{r['key']}_{ticket_id}",
                    disabled=not signed_in,
                    label_visibility="collapsed",
                    help=f"Whole number from 0 to {r['max']}.",
                )
        with rc2:
            remarks[r["key"]] = st.text_input(
                f"Remarks — {r['name']}",
                value=existing_remarks.get(r["key"], ""),
                key=f"remark_{channel}_{r['key']}_{ticket_id}",
                disabled=not signed_in,
                label_visibility="collapsed",
                placeholder="Remarks (optional)",
            )

    overall_comments = st.text_area(
        "Overall Comments / Remarks",
        value=(existing or {}).get("overall_comments") or "",
        key=f"comments_{ticket_id}",
        disabled=not signed_in,
    )

    st.markdown("**Critical Errors** (any \"Yes\" = automatic FAIL)")
    existing_crit = (existing or {}).get("critical_errors") or {}
    crit = {}
    critical_errors = critical_errors_for(channel)
    crit_cols = st.columns(len(critical_errors))
    for i, c in enumerate(critical_errors):
        with crit_cols[i]:
            crit[c["key"]] = st.checkbox(
                c["label"], value=bool(existing_crit.get(c["key"])), key=f"crit_{channel}_{c['key']}_{ticket_id}", disabled=not signed_in, help=c["desc"]
            )

    total = compute_total(scores, channel)
    result = compute_result(total, crit, channel)
    st.markdown(f"### Total: {total} / 100 &nbsp;&nbsp; {result_badge_md(result)}", unsafe_allow_html=True)

    if not signed_in:
        st.caption("Only Erwin, Weng, and Kristine can save changes here — everyone else can view read-only.")
        return

    tc1, tc2 = st.columns(2)
    is_test = tc1.checkbox(
        "🧪 Mark as a test audit",
        value=bool((existing or {}).get("is_test", False)),
        key=f"is_test_{ticket_id}",
        help="Saved like any other audit, but excluded from the QA Log's dashboard totals and per-agent rollup.",
    )
    is_escalated = tc2.checkbox(
        "🚩 Escalated (manually added, not the random pull)",
        value=bool((existing or {}).get("is_escalated", default_escalated)),
        key=f"is_escalated_{ticket_id}",
        help="Auto-checked when this ticket came from 'Manually log a ticket' on Weekly QA Batch — toggle any time. Shows as a tag in the QA Log so it's easy to tell apart from the random pull.",
    )

    # A score only gets reopened after being saved for one of two reasons in
    # practice — a dispute, or a reviewer catching a mistake — so editing an
    # existing audit requires saying which, logged alongside what the score
    # used to look like. A brand-new audit has nothing to log yet.
    edit_reason = None
    dispute_reason = ""
    dispute_conclusion = ""
    if existing:
        st.markdown("**Why is this score being edited?**")
        edit_reason = st.selectbox(
            "Reason for this edit",
            EDIT_REASONS,
            key=f"edit_reason_{ticket_id}",
        )
        if edit_reason.startswith("Dispute"):
            dispute_reason = st.text_area(
                "Dispute reason — what was disputed, and why",
                key=f"dispute_reason_{ticket_id}",
            )
            dispute_conclusion = st.text_area(
                "Dispute conclusion — how it was resolved (leave blank if not decided yet)",
                key=f"dispute_conclusion_{ticket_id}",
            )

    if st.button("Save changes" if existing else "Submit audit", key=f"submit_{ticket_id}", type="primary"):
        if not agent_name.strip():
            st.error("Agent Name is required.")
            return
        if existing and edit_reason.startswith("Dispute") and not dispute_reason.strip():
            st.error("Dispute reason is required when editing a score because of a dispute.")
            return
        now = datetime.utcnow().isoformat()
        edit_log = list((existing or {}).get("edit_log") or [])
        if existing:
            edit_log.append(
                {
                    "edited_at": now,
                    "edited_by": auth.current_reviewer(),
                    "reason": (
                        "Dispute"
                        if edit_reason.startswith("Dispute")
                        else "Correction"
                        if edit_reason.startswith("Reviewer")
                        else "Other"
                    ),
                    "dispute_reason": dispute_reason.strip(),
                    "dispute_conclusion": dispute_conclusion.strip(),
                    "previous_score": existing.get("total_score"),
                    "previous_result": existing.get("result"),
                    "previous_scores": existing.get("scores"),
                    "previous_remarks": existing.get("remarks"),
                    "previous_overall_comments": existing.get("overall_comments"),
                    "previous_qa_reviewer": existing.get("qa_reviewer"),
                    "previous_qa_date": existing.get("qa_date"),
                }
            )
        entry = {
            "agent_id": (existing or {}).get("agent_id"),
            "agent_name": agent_name.strip(),
            "ticket_id": ticket_id,
            "ticket_link": ticket_link.strip() or ticket_url,
            "zomp_link": zomp_link.strip(),
            "renter_host": renter_host,
            "concern_types": concern_types,
            "scores": scores,
            "remarks": remarks,
            "overall_comments": overall_comments,
            "total_score": total,
            "result": result,
            "critical_errors": crit,
            "critical_error_status": "CRITICAL ERROR" if any(crit.values()) else "OK",
            "qa_reviewer": auth.current_reviewer(),
            "qa_date": qa_date.isoformat(),
            "is_test": is_test,
            "is_escalated": is_escalated,
            "channel": channel,
            "edit_log": edit_log,
            "updated_at": now,
            "created_at": (existing or {}).get("created_at") or now,
        }
        if channel == "Phone":
            # Only phone audits carry this field, so a chat save never touches
            # the column (and keeps working before the SQL migration is run).
            entry["recording_link"] = recording_link.strip()
        try:
            db.save_qa_entry(ticket_id, entry)
            db.clear_cache()
            sheets_backup.backup_qa_entry(ticket_id, entry)
            st.session_state[editing_key] = False
            st.success("Saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not save — {e}")


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def _fmt_date(iso_value) -> str:
    if not iso_value:
        return "—"
    try:
        return datetime.fromisoformat(str(iso_value)).strftime("%Y-%m-%d")
    except Exception:
        return str(iso_value)


def _safe_index(options: list, value) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0
