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

from lib import auth, db, evaluator_auth, phone_rubric_ui, sheets_backup
from lib.constants import (
    CHANNEL_OPTIONS,
    CONCERN_TYPES,
    RENTER_HOST_OPTIONS,
    compute_result,
    compute_total,
    critical_errors_for,
    phone_level_label,
    rubric_channel,
    rubric_for,
)
from lib.ui import result_badge_md

EDIT_REASONS = [
    "Dispute — agent or TL disagreed with the score",
    "Reviewer correction (no dispute)",
    "Other",
]


def _auditor_name() -> str | None:
    """Who is saving: a signed-in reviewer, or else a signed-in phone evaluator."""
    return auth.current_reviewer() or evaluator_auth.current_name()


def _evaluator_only() -> bool:
    """A phone evaluator is signed in and no reviewer is: phone audits only,
    no test or escalated flags."""
    return evaluator_auth.is_signed_in() and not auth.is_signed_in()


def _can_edit(qa: dict) -> bool:
    if auth.is_signed_in():
        return True
    # A phone evaluator can reopen only a phone audit they saved themselves.
    return (
        evaluator_auth.is_signed_in()
        and (qa.get("channel") or "Chat") == "Phone"
        and qa.get("qa_reviewer") == evaluator_auth.current_name()
    )


def _agent_options() -> list[str]:
    return sorted({a["name"] for a in db.list_agents() if a.get("name")})


def render(
    convo: dict,
    ticket_url: str,
    guessed_agent_name: str,
    default_escalated: bool = False,
    force_phone: bool = False,
) -> None:
    """force_phone: the ticket came from the Phone Queue, so the form is locked
    to the phone rubric for everyone. A signed-in phone evaluator always gets
    the phone rubric, wherever the ticket was opened."""
    ticket_id = str(convo["id"])
    existing = db.get_qa_entry(ticket_id)
    editing_key = f"qa_editing_{ticket_id}"
    phone_only = force_phone or _evaluator_only()

    if existing and (not st.session_state.get(editing_key) or not _can_edit(existing)):
        _render_summary(ticket_id, existing, editing_key)
        return

    _render_form(ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key, default_escalated, phone_only)


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
    if auth.is_signed_in() or evaluator_auth.is_signed_in():
        _render_breakdown(qa)
    if _can_edit(qa):
        if cols[3].button("Edit score", key=f"edit_{ticket_id}"):
            st.session_state[editing_key] = True
            st.rerun()
    elif evaluator_auth.is_signed_in():
        cols[3].caption("View only")
    else:
        cols[3].caption("Sign in to edit")


def _render_breakdown(qa: dict) -> None:
    """The saved audit in full, read-only: each category's score (with its
    level name on a phone audit) and remarks, critical errors, overall
    comments and links. Shown to reviewers and phone evaluators, so an
    evaluator can see how someone else scored a ticket once it's submitted."""
    channel = rubric_channel(qa)
    scores = qa.get("scores") or {}
    remarks = qa.get("remarks") or {}
    with st.expander("Full breakdown", expanded=False):
        lines = []
        for r in rubric_for(channel):
            v = scores.get(r["key"])
            if v is None:
                shown = "—"
            elif channel == "Phone" and r.get("levels"):
                shown = phone_level_label(r, v)
            else:
                shown = str(v)
            line = f"- **{r['name']}** (max {r['max']}): {shown}"
            if remarks.get(r["key"]):
                line += f"  \n  _{remarks[r['key']]}_"
            lines.append(line)
        st.markdown("\n".join(lines))
        crit = qa.get("critical_errors") or {}
        flagged = [c["label"] for c in critical_errors_for(channel) if crit.get(c["key"])]
        st.markdown("**Critical errors:** " + ("; ".join(flagged) if flagged else "None"))
        if qa.get("overall_comments"):
            st.markdown(f"**Overall comments:** {qa['overall_comments']}")
        extra = []
        if qa.get("concern_types"):
            extra.append("Concern: " + ", ".join(qa["concern_types"]))
        if qa.get("renter_host"):
            extra.append(f"Renter/Host: {qa['renter_host']}")
        if extra:
            st.caption(" · ".join(extra))
        if qa.get("zomp_link"):
            st.markdown(f"**ZOMP:** [{qa['zomp_link']}]({qa['zomp_link']})")


def _render_form(
    ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key, default_escalated: bool = False, phone_only: bool = False
) -> None:
    st.divider()
    header_cols = st.columns([4, 1])
    header_cols[0].subheader("QA Audit" + (" — editing" if existing else ""))
    if existing and header_cols[1].button("Cancel", key=f"cancel_{ticket_id}"):
        # Cancelling an edit also throws away its autosaved draft.
        db.delete_audit_draft(ticket_id, _auditor_name())
        _forget_form(ticket_id)
        st.session_state[editing_key] = False
        st.rerun()

    signed_in = auth.is_signed_in() or evaluator_auth.is_signed_in()
    is_reviewer = auth.is_signed_in()
    if not signed_in:
        st.info('Sign in as Erwin, Weng, or Kristine in the sidebar to submit or edit a QA audit.')

    # Autosave: an unsubmitted draft of this form (saved as the person fills it
    # in) pre-fills it, so a dropped session doesn't lose their work. `seed`
    # is where every field's starting value comes from: the saved audit, with
    # the draft on top.
    author = _auditor_name() if signed_in else None
    draft = _load_draft(ticket_id, author)
    seed = {**(existing or {}), **((draft or {}).get("data") or {})}
    if draft:
        dc1, dc2 = st.columns([4, 1])
        dc1.info(f"Restored your unsaved draft from {_fmt_draft_time(draft.get('updated_at'))}. Submit to save it as an audit.")
        if dc2.button("Discard draft", key=f"discard_draft_{ticket_id}"):
            db.delete_audit_draft(ticket_id, author)
            _forget_form(ticket_id)
            st.rerun()

    agent_roster = _agent_options()
    default_agent = seed.get("agent_name") or guessed_agent_name or ""

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
            value=_parse_date(seed.get("qa_date")) or date.today(),
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
        if phone_only:
            # Phone Queue tickets and phone evaluators: always the phone rubric.
            channel = "Phone"
            st.selectbox(
                "Channel",
                ["Phone"],
                key=f"channel_locked_{ticket_id}",
                help="Locked to Phone: this ticket came from the Phone Queue.",
                disabled=True,
            )
        else:
            channel = st.selectbox(
                "Channel",
                CHANNEL_OPTIONS,
                index=_safe_index(CHANNEL_OPTIONS, seed.get("channel") or "Chat"),
                key=f"channel_{ticket_id}",
                help="Which support channel this audit came from. It decides which scoring rubric is used, shows as a tag, and is filterable in the Audit log.",
                disabled=not signed_in,
            )
    with ch2:
        recording_link = ""
        if channel == "Phone":
            recording_link = st.text_input(
                "Call recording link",
                value=seed.get("recording_link") or "",
                key=f"recording_{ticket_id}",
                help="Optional. The recording also plays above, from Intercom, for anyone signed in to this app. Phone audits are scored from the recording, not a transcript, because tone, pace and silence do not show in writing.",
                disabled=not signed_in,
            )
    rubric = rubric_for(channel)

    ticket_link = st.text_input(
        "Ticket Link", value=seed.get("ticket_link") or ticket_url, key=f"link_{ticket_id}", disabled=not signed_in
    )
    c3, c4 = st.columns(2)
    with c3:
        zomp_link = st.text_input(
            "ZOMP Link", value=seed.get("zomp_link") or "", key=f"zomp_{ticket_id}", disabled=not signed_in
        )
    with c4:
        renter_host = st.selectbox(
            "Renter / Host",
            RENTER_HOST_OPTIONS,
            index=_safe_index(RENTER_HOST_OPTIONS, seed.get("renter_host")),
            key=f"rh_{ticket_id}",
            disabled=not signed_in,
        )

    concern_types = st.multiselect(
        "Concern Type (select all that apply)",
        CONCERN_TYPES,
        default=[c for c in (seed.get("concern_types") or []) if c in CONCERN_TYPES],
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
    existing_scores = seed.get("scores") or {}
    existing_remarks = seed.get("remarks") or {}
    for r in rubric:
        if channel == "Phone":
            # Phone: the guide's fixed levels, each with its description, and the
            # category's Critical Note; remarks go underneath.
            st.markdown(f"**{r['name']}** ({r['max']} points)")
            scores[r["key"]] = phone_rubric_ui.level_picker(
                r,
                key=f"score_{channel}_{r['key']}_{ticket_id}",
                current=existing_scores.get(r["key"]),
                disabled=not signed_in,
            )
            remarks[r["key"]] = st.text_input(
                f"Remarks — {r['name']}",
                value=existing_remarks.get(r["key"], ""),
                key=f"remark_{channel}_{r['key']}_{ticket_id}",
                disabled=not signed_in,
                label_visibility="collapsed",
                placeholder="Remarks (optional)",
            )
            continue
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
        value=seed.get("overall_comments") or "",
        key=f"comments_{ticket_id}",
        disabled=not signed_in,
    )

    st.markdown("**Critical Errors** (any \"Yes\" = automatic FAIL)")
    existing_crit = seed.get("critical_errors") or {}
    crit = {}
    critical_errors = critical_errors_for(channel)
    per_row = min(len(critical_errors), 4)
    for i, c in enumerate(critical_errors):
        if i % per_row == 0:
            crit_cols = st.columns(per_row)
        with crit_cols[i % per_row]:
            crit[c["key"]] = st.checkbox(
                c["label"], value=bool(existing_crit.get(c["key"])), key=f"crit_{channel}_{c['key']}_{ticket_id}", disabled=not signed_in, help=c["desc"]
            )

    total = compute_total(scores, channel)
    result = compute_result(total, crit, channel)
    st.markdown(f"### Total: {total} / 100 &nbsp;&nbsp; {result_badge_md(result)}", unsafe_allow_html=True)

    if not signed_in:
        st.caption("Only Erwin, Weng, and Kristine can save changes here — everyone else can view read-only.")
        return

    _autosave(
        ticket_id,
        author,
        {
            "agent_name": agent_name,
            "qa_date": qa_date.isoformat() if qa_date else None,
            "channel": channel,
            "recording_link": recording_link,
            "ticket_link": ticket_link,
            "zomp_link": zomp_link,
            "renter_host": renter_host,
            "concern_types": concern_types,
            "scores": scores,
            "remarks": remarks,
            "overall_comments": overall_comments,
            "critical_errors": crit,
        },
        restored=bool(draft),
    )

    if is_reviewer:
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
    else:
        # Phone evaluators don't set these; an edit keeps whatever a reviewer set.
        is_test = bool((existing or {}).get("is_test", False))
        is_escalated = bool((existing or {}).get("is_escalated", default_escalated))

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
            index=None,
            placeholder="Choose why",
            key=f"edit_reason_{ticket_id}",
        )
        # Nothing is preselected, so a correction or a test-audit change is
        # never logged as a dispute by accident.
        if (edit_reason or "").startswith("Dispute"):
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
        if channel == "Phone" and phone_rubric_ui.missing_levels(scores):
            st.error("Pick a level for every category: " + ", ".join(phone_rubric_ui.missing_levels(scores)) + ".")
            return
        if existing and not edit_reason:
            st.error("Choose why this score is being edited.")
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
                    "edited_by": _auditor_name(),
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
            "qa_reviewer": _auditor_name(),
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
            db.delete_audit_draft(ticket_id, author)
            _forget_form(ticket_id, keep_widgets=True)
            db.clear_cache()
            sheets_backup.backup_qa_entry(ticket_id, entry)
            st.session_state[editing_key] = False
            st.success("Saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not save — {e}")


def _load_draft(ticket_id: str, author: str | None) -> dict | None:
    """This person's saved draft for this ticket, read once per session (the
    form's own widget state takes over after that)."""
    if not author:
        return None
    key = f"_draft_row_{ticket_id}"
    if key not in st.session_state:
        st.session_state[key] = db.get_audit_draft(ticket_id, author)
    return st.session_state[key]


def _autosave(ticket_id: str, author: str | None, data: dict, restored: bool) -> None:
    """Saves the form as a draft whenever it differs from what it was when
    first opened (or from the last save). Opening a ticket and looking around
    saves nothing."""
    if not author:
        return
    ss = st.session_state
    base_key, last_key = f"_draft_base_{ticket_id}", f"_draft_last_{ticket_id}"
    if base_key not in ss:
        ss[base_key] = None if restored else data
        ss[last_key] = data if restored else None
        return
    if data == ss[base_key] or data == ss[last_key]:
        return
    if db.save_audit_draft(ticket_id, author, data):
        ss[last_key] = data


def _forget_form(ticket_id: str, keep_widgets: bool = False) -> None:
    """Drops this ticket's draft bookkeeping (and, unless keep_widgets, the
    form's widget values, so the form redraws from the saved audit)."""
    ss = st.session_state
    for k in [k for k in list(ss.keys()) if isinstance(k, str) and k.endswith(f"_{ticket_id}")]:
        if k.startswith(("_draft_",)) or not keep_widgets:
            if k.startswith(("qa_editing_",)):
                continue
            ss.pop(k, None)


def _fmt_draft_time(iso_value) -> str:
    if not iso_value:
        return "earlier"
    try:
        return datetime.fromisoformat(str(iso_value).replace("Z", "+00:00")).strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return str(iso_value)[:16]


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
