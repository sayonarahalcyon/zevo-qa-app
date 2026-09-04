"""The QA audit form/summary, mounted below any opened ticket.

One audit per ticket; editable afterward by a signed-in reviewer. Mirrors
the original Claude artifact's form field-for-field.
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from lib import auth, db
from lib.constants import (
    CONCERN_TYPES,
    CRITICAL_ERRORS,
    RENTER_HOST_OPTIONS,
    RUBRIC,
    compute_result,
    compute_total,
)
from lib.ui import result_badge_md


def _agent_options() -> list[str]:
    return sorted({a["name"] for a in db.list_agents() if a.get("name")})


def render(convo: dict, ticket_url: str, guessed_agent_name: str) -> None:
    ticket_id = str(convo["id"])
    existing = db.get_qa_entry(ticket_id)
    editing_key = f"qa_editing_{ticket_id}"

    if existing and not st.session_state.get(editing_key):
        _render_summary(ticket_id, existing, editing_key)
        return

    _render_form(ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key)


def _render_summary(ticket_id: str, qa: dict, editing_key: str) -> None:
    st.divider()
    st.subheader("QA Audit")
    cols = st.columns([2, 2, 3, 1])
    cols[0].markdown(result_badge_md(qa.get("result", "")))
    cols[1].markdown(f"**{qa.get('total_score', '—')} / 100**")
    cols[2].caption(
        f"{qa.get('agent_name', '')} · reviewed by {qa.get('qa_reviewer', '—')} · {qa.get('qa_date', '')}"
    )
    if auth.is_signed_in():
        if cols[3].button("Edit score", key=f"edit_{ticket_id}"):
            st.session_state[editing_key] = True
            st.rerun()
    else:
        cols[3].caption("Sign in to edit")


def _render_form(ticket_id, convo, ticket_url, guessed_agent_name, existing, editing_key) -> None:
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

    st.markdown("**Scoring rubric**")
    scores = {}
    remarks = {}
    existing_scores = (existing or {}).get("scores") or {}
    existing_remarks = (existing or {}).get("remarks") or {}
    for r in RUBRIC:
        rc1, rc2 = st.columns([1, 2])
        with rc1:
            st.caption(f"{r['name']} (max {r['max']})")
            default_val = existing_scores.get(r["key"])
            idx = r["options"].index(default_val) if default_val in r["options"] else 0
            scores[r["key"]] = st.radio(
                r["key"],
                r["options"],
                index=idx,
                key=f"score_{r['key']}_{ticket_id}",
                horizontal=True,
                disabled=not signed_in,
                label_visibility="collapsed",
            )
        with rc2:
            remarks[r["key"]] = st.text_input(
                f"Remarks — {r['name']}",
                value=existing_remarks.get(r["key"], ""),
                key=f"remark_{r['key']}_{ticket_id}",
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
    crit_cols = st.columns(len(CRITICAL_ERRORS))
    for i, c in enumerate(CRITICAL_ERRORS):
        with crit_cols[i]:
            crit[c["key"]] = st.checkbox(
                c["label"], value=bool(existing_crit.get(c["key"])), key=f"crit_{c['key']}_{ticket_id}", disabled=not signed_in, help=c["desc"]
            )

    total = compute_total(scores)
    result = compute_result(total, crit)
    st.markdown(f"### Total: {total} / 100 &nbsp;&nbsp; {result_badge_md(result)}", unsafe_allow_html=True)

    if not signed_in:
        st.caption("Only Erwin, Weng, and Kristine can save changes here — everyone else can view read-only.")
        return

    if st.button("Save changes" if existing else "Submit audit", key=f"submit_{ticket_id}", type="primary"):
        if not agent_name.strip():
            st.error("Agent Name is required.")
            return
        now = datetime.utcnow().isoformat()
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
            "updated_at": now,
            "created_at": (existing or {}).get("created_at") or now,
        }
        try:
            db.save_qa_entry(ticket_id, entry)
            db.clear_cache()
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


def _safe_index(options: list, value) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0
