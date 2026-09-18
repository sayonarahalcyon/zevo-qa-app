"""The in-app "Question or dispute about this audit?" form and its
reviewer-facing inbox.

Replaces the old external QA Audit Question & Dispute Form (Google Form) for
agent-initiated submissions. Because it's mounted inside My Dashboard, the
agent is already signed in and already looking at a specific audit, so —
unlike the old form — nothing here asks them to re-type their name, the
ticket, the reviewer, or the original score; a submission is always created
via db.create_dispute(entry_id=..., ...) and everything else is looked up.

A submitted "dispute" is the intake record of the agent's disagreement, not
the score correction itself — a reviewer who agrees still makes the actual
change the way they already do (QA Log → open the audit → "Edit score" →
reason "Dispute"), which keeps logging to qa_entries.edit_log exactly as
before. render_reviewer_panel() links straight into that existing flow.
"""

from datetime import date, datetime, timedelta

import streamlit as st

from lib import auth, db
from lib.constants import DISPUTE_CATEGORIES


def render_agent_form(entry: dict, agent: dict) -> None:
    """Mounted inside one audit's expander on My Dashboard. `entry` is the
    qa_entries row being viewed; `agent` is agent_auth.current_agent()."""
    entry_id = entry["id"]

    existing = [d for d in db.list_disputes() if d.get("entry_id") == entry_id]
    if existing:
        st.markdown("**Your questions/disputes on this audit**")
        for d in sorted(existing, key=lambda r: r.get("created_at") or "", reverse=True):
            _render_existing(d)
        st.write("")

    with st.expander("❓ Question or dispute about this audit?"):
        kind = st.radio(
            "What's this about?",
            ["Ask a question", "Dispute the score"],
            key=f"dispute_kind_{entry_id}",
            horizontal=True,
        )
        request_type = "question" if kind == "Ask a question" else "dispute"

        categories: list[str] = []
        if request_type == "dispute":
            categories = st.multiselect(
                "Which QA category is this related to?",
                DISPUTE_CATEGORIES,
                key=f"dispute_categories_{entry_id}",
            )

        message_label = "What is your question?" if request_type == "question" else "Reason for dispute"
        message = st.text_area(message_label, key=f"dispute_message_{entry_id}")

        evidence = ""
        if request_type == "dispute":
            evidence = st.text_area(
                "Supporting evidence (optional)",
                key=f"dispute_evidence_{entry_id}",
                help="Describe anything supporting your case — a specific message in the "
                "ticket, a policy reference, or where a screenshot can be found.",
            )

        if st.button("Submit", key=f"dispute_submit_{entry_id}"):
            if request_type == "dispute" and not categories:
                st.error("Select at least one QA category.")
            elif not message.strip():
                st.error("This field is required.")
            else:
                err = db.create_dispute(
                    entry_id=entry_id,
                    agent_id=agent["id"],
                    agent_name=agent["name"],
                    request_type=request_type,
                    message=message.strip(),
                    categories=categories,
                    supporting_evidence=evidence.strip(),
                )
                if err:
                    st.error(f"Couldn't submit: {err}")
                else:
                    st.success("Submitted — a reviewer will follow up here.")
                    st.rerun()


def _render_existing(d: dict) -> None:
    kind_label = "Question" if d.get("request_type") == "question" else "Dispute"
    resolved = d.get("status") == "resolved"
    badge = "🟢 Resolved" if resolved else "🟡 Open — awaiting reviewer"
    st.caption(f"**{kind_label}** · {badge} · submitted {(d.get('created_at') or '')[:10]}")
    st.write(d.get("message", ""))
    if d.get("categories"):
        st.caption("Categories: " + ", ".join(d["categories"]))
    if resolved:
        st.info(f"**Reviewer response ({d.get('resolved_by') or '—'}):** {d.get('reviewer_response') or ''}")


def _week_start(created_at: str | None) -> date | None:
    """Monday of the week `created_at` falls in, or None if unparseable."""
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.date() - timedelta(days=dt.weekday())


def _group_by_week(disputes: list[dict]) -> list[tuple[date | None, list[dict]]]:
    """Groups (already newest-first) disputes by the Monday of their week,
    most recent week first. Each group keeps the incoming (newest-first)
    order. Undated rows land in their own group, sorted last."""
    groups: dict[date | None, list[dict]] = {}
    for d in disputes:
        groups.setdefault(_week_start(d.get("created_at")), []).append(d)
    return sorted(groups.items(), key=lambda kv: kv[0] or date.min, reverse=True)


def _render_dispute_row(d: dict, entries_by_id: dict, ss) -> None:
    entry = entries_by_id.get(d.get("entry_id")) or {}
    kind_label = "❓ Question" if d.get("request_type") == "question" else "⚖️ Dispute"
    resolved = d.get("status") == "resolved"
    badge = "🟢 Resolved" if resolved else "🟡 Open"
    ticket_id = entry.get("ticket_id") or "—"
    label = f"{kind_label} · {d.get('agent_name') or '—'} · Ticket {ticket_id} · {badge}"
    if d.get("is_test"):
        label += " · 🧪 TEST"

    with st.expander(label):
        st.caption(
            f"Audit: {entry.get('qa_date', '—')} · {entry.get('result', '—')} · "
            f"{entry.get('total_score', '—')}/100 · reviewed by {entry.get('qa_reviewer', '—')}"
            if entry
            else "The audit this was submitted about could not be found."
        )
        if entry.get("ticket_link"):
            st.markdown(f"[Open ticket]({entry['ticket_link']})")
        st.write(d.get("message", ""))
        if d.get("categories"):
            st.caption("Categories: " + ", ".join(d["categories"]))
        if d.get("supporting_evidence"):
            st.markdown(f"**Supporting evidence:** {d['supporting_evidence']}")

        if entry.get("ticket_id") and d.get("request_type") == "dispute":
            if st.button("Open this audit to edit the score", key=f"dispute_edit_{d['id']}"):
                ss["log_open_ticket_id"] = entry["ticket_id"]
                ss["log_open_audit_key"] = None
                ss[f"qa_editing_{entry['ticket_id']}"] = True
                st.switch_page("pages/2_QA_Log.py")
            st.caption('Choose "Dispute" as the edit reason there to log it on the audit itself.')

        if resolved:
            st.success(f"Resolved by {d.get('resolved_by') or '—'} on {(d.get('resolved_at') or '')[:10]}")
            st.write(d.get("reviewer_response") or "")
            if st.button("Reopen", key=f"dispute_reopen_{d['id']}"):
                err = db.reopen_dispute(d["id"])
                if err:
                    st.error(err)
                else:
                    st.rerun()
        else:
            response = st.text_area("Response to agent", key=f"dispute_response_{d['id']}")
            if st.button("Mark resolved", key=f"dispute_resolve_{d['id']}"):
                if not response.strip():
                    st.error("Write a response before marking this resolved — the agent will see it.")
                else:
                    err = db.resolve_dispute(d["id"], response.strip(), auth.current_reviewer())
                    if err:
                        st.error(err)
                    else:
                        st.success("Marked resolved.")
                        st.rerun()


def render_reviewer_panel() -> None:
    """Mounted on the Questions & Disputes page. Reviewer-only (same page
    gate — lib.auth), visible to any signed-in reviewer, not just Weng.
    Submissions are grouped by the week they came in (most recent first),
    with an optional agent filter above the groups."""
    disputes = db.list_disputes()
    if not disputes:
        st.caption("No questions or disputes submitted yet.")
        return

    entries_by_id = {e["id"]: e for e in db.list_qa_entries()}
    real_disputes = [d for d in disputes if not d.get("is_test")]
    test_count = len(disputes) - len(real_disputes)
    open_count = sum(1 for d in real_disputes if d.get("status") != "resolved")
    caption = f"{open_count} open · {len(real_disputes) - open_count} resolved"
    if test_count:
        caption += f" · {test_count} test"
    st.caption(caption)

    agent_names = sorted({d.get("agent_name") for d in disputes if d.get("agent_name")})
    agent_filter = st.selectbox(
        "Filter by agent", ["All agents"] + agent_names, key="dispute_agent_filter"
    )
    filtered = (
        disputes if agent_filter == "All agents"
        else [d for d in disputes if d.get("agent_name") == agent_filter]
    )
    if not filtered:
        st.caption(f"No questions or disputes from {agent_filter}.")
        return

    ss = st.session_state
    for week_start, week_disputes in _group_by_week(filtered):
        label = "Date unknown" if week_start is None else f"Week of {week_start.strftime('%b %-d, %Y')}"
        st.markdown(f"**{label}**")
        for d in week_disputes:
            _render_dispute_row(d, entries_by_id, ss)
        st.write("")
