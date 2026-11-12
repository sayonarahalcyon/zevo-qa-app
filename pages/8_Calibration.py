"""Calibration: several chosen evaluators each score the same phone ticket
independently, then compare scores side by side.

- Weng starts a session from an Intercom phone ticket link and picks who
  scores it (reviewers and/or phone evaluators).
- Each participant opens it, listens to the call (recording and transcript
  are fetched from Intercom by the app), and submits a score on the phone
  rubric. Scoring is blind: participants can't see anyone else's scores until
  everyone has submitted. Weng can see the comparison at any time.
- Once everyone has submitted, scores are locked and the comparison is shown
  to all participants: each person's points per category, total, result,
  critical errors and remarks, plus the spread per category.
- Calibration scores live in calibration_scores only. They never go into
  qa_entries, the backup sheet, or any dashboard, rollup, pass rate or agent
  view.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import streamlit as st

from lib import auth, db, evaluator_auth, phone_rubric_ui, ui
from lib.constants import (
    PHONE_RUBRIC_GUIDE,
    REVIEWER_NAMES,
    compute_result,
    compute_total,
    critical_errors_for,
    phone_level_label,
    rubric_for,
)
from lib.intercom_client import IntercomError, conversation_url, get_call_ids, get_conversation
from lib.ticket_view import learn_agents_from_conversation, render_ticket

st.set_page_config(page_title="Calibration — ZEVO Quality Evaluation", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

CALIBRATION_ADMIN = "Weng Yee"  # starts, closes and deletes sessions; sees all scores at any time
ss = st.session_state

is_reviewer = auth.is_signed_in()
is_evaluator = evaluator_auth.is_signed_in()
me = auth.current_reviewer() or evaluator_auth.current_name()
is_admin = auth.current_reviewer() == CALIBRATION_ADMIN

RUBRIC = rubric_for("Phone")
CRITICAL = critical_errors_for("Phone")

ui.page_heading("Calibration")

if not (is_reviewer or is_evaluator):
    st.info("Sign in to take part in calibration. Erwin, Weng or Kristine: sign in on Home. Phone evaluators: sign in on Phone Queue.")
    st.stop()

if is_evaluator and not is_reviewer:
    top = st.columns([3, 1])
    with top[1]:
        evaluator_auth.render_sign_out()
    with top[0]:
        st.caption(f"Signed in as **{me}**.")
else:
    st.caption(f"Signed in as **{me}**.")

st.caption(
    "Everyone picked for a session scores the same phone call on their own. Scores stay hidden from the "
    "other participants until everyone has submitted. Calibration scores never count toward any dashboard, "
    "pass rate or agent view."
)

sessions = db.list_calibration_sessions()
if sessions is None:
    st.error(
        "Calibration isn't set up in the database yet. Run "
        "sql/migrations/2026_11_07b_calibration.sql in the Supabase SQL editor."
    )
    st.stop()

all_scores = db.list_calibration_scores()


def _scores_for(session_id: str) -> dict:
    return {s["evaluator"]: s for s in all_scores if s.get("session_id") == session_id}


def _all_submitted(session: dict, scores: dict) -> bool:
    parts = session.get("participants") or []
    return bool(parts) and all(p in scores for p in parts)


def _fmt(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return str(iso)[:10]


def _flash(kind: str, text: str) -> None:
    ss["_cal_msg"] = (kind, text)


msg = ss.pop("_cal_msg", None)
if msg:
    (st.success if msg[0] == "ok" else st.error)(msg[1])


def _scoring_guide(expanded: bool = False) -> None:
    """The phone scoring guide (fixed levels, descriptions, Critical Notes) and
    the result thresholds, same wording as QA Log's Scoring guide."""
    st.subheader("Phone scoring guide")
    phone_rubric_ui.render_guide(expanded=expanded)
    with st.expander("Phone critical errors (any = automatic FAIL)", expanded=expanded):
        for c in CRITICAL:
            st.markdown(f"**{c['label']}**")
            st.caption(c["desc"])
    with st.expander("Result thresholds", expanded=expanded):
        st.markdown(
            "**PASS**: total score 85 or higher, no critical errors.  \n"
            "**COACHING**: total score 70 to 84, no critical errors.  \n"
            "**FAIL**: total score below 70.  \n"
            "**AUTO FAIL**: any critical error, regardless of total score."
        )


def _comparison(session: dict, scores: dict) -> None:
    people = [p for p in (session.get("participants") or []) if p in scores]
    if not people:
        st.caption("No scores submitted yet.")
        return
    rows = []
    for r in RUBRIC:
        vals = [int((scores[p].get("scores") or {}).get(r["key"], 0) or 0) for p in people]
        shown = [phone_level_label(r, v) for v in vals]
        rows.append({"Category": f"{r['name']} (max {r['max']})", **dict(zip(people, shown)), "Spread": max(vals) - min(vals)})
    totals = [int(scores[p].get("total_score") or 0) for p in people]
    rows.append({"Category": "Total (out of 100)", **dict(zip(people, [str(t) for t in totals])), "Spread": max(totals) - min(totals)})
    table = pd.DataFrame(rows).set_index("Category")
    st.dataframe(table, use_container_width=True)

    results = {p: scores[p].get("result") or "—" for p in people}
    st.markdown("**Result:** " + " · ".join(f"{p}: {ui.result_badge_md(results[p])}" for p in people), unsafe_allow_html=True)
    agree = len(set(results.values())) == 1
    st.caption("Everyone reached the same result." if agree else "Results differ between evaluators.")

    crit_rows = []
    for c in CRITICAL:
        marks = {p: ("Yes" if (scores[p].get("critical_errors") or {}).get(c["key"]) else "") for p in people}
        if any(marks.values()):
            crit_rows.append({"Critical error": c["label"], **marks})
    if crit_rows:
        st.markdown("**Critical errors flagged**")
        st.dataframe(pd.DataFrame(crit_rows).set_index("Critical error"), use_container_width=True)
    else:
        st.caption("No critical errors flagged by anyone.")

    with st.expander("Remarks and comments"):
        for p in people:
            s = scores[p]
            st.markdown(f"**{p}** · submitted {_fmt(s.get('submitted_at'))}")
            rem = s.get("remarks") or {}
            lines = [f"- {r['name']}: {rem[r['key']]}" for r in RUBRIC if rem.get(r["key"])]
            if s.get("overall_comments"):
                lines.append(f"- Overall: {s['overall_comments']}")
            st.markdown("\n".join(lines) if lines else "_No remarks._")


def _score_form(session: dict, existing: dict | None, locked: bool) -> None:
    sid = session["id"]
    st.subheader("Your calibration score")
    if locked:
        st.caption("Everyone has submitted, so scores are locked." if not session.get("closed_at") else "This session is closed, so scores are locked.")
    elif existing:
        st.caption(f"You submitted on {_fmt(existing.get('submitted_at'))}. You can change your score until everyone has submitted.")
    else:
        st.caption("Score from the call recording. Nobody else sees your score until everyone has submitted.")

    ex_scores = (existing or {}).get("scores") or {}
    ex_remarks = (existing or {}).get("remarks") or {}
    ex_crit = (existing or {}).get("critical_errors") or {}
    scores, remarks = {}, {}
    for r in RUBRIC:
        st.markdown(f"**{r['name']}** ({r['max']} points)")
        scores[r["key"]] = phone_rubric_ui.level_picker(
            r, key=f"cal_{sid}_{r['key']}", current=ex_scores.get(r["key"]), disabled=locked
        )
        remarks[r["key"]] = st.text_input(
            f"Remarks — {r['name']}", value=ex_remarks.get(r["key"], ""), key=f"cal_rem_{sid}_{r['key']}",
            disabled=locked, label_visibility="collapsed", placeholder="Remarks (optional)",
        )
    overall = st.text_area("Overall comments", value=(existing or {}).get("overall_comments") or "", key=f"cal_overall_{sid}", disabled=locked)
    st.markdown('**Critical errors** (any "Yes" = automatic FAIL)')
    crit = {}
    cols = st.columns(len(CRITICAL))
    for i, c in enumerate(CRITICAL):
        with cols[i]:
            crit[c["key"]] = st.checkbox(c["label"], value=bool(ex_crit.get(c["key"])), key=f"cal_crit_{sid}_{c['key']}", disabled=locked, help=c["desc"])
    total = compute_total(scores, "Phone")
    result = compute_result(total, crit, "Phone")
    st.markdown(f"### Total: {total} / 100 &nbsp;&nbsp; {ui.result_badge_md(result)}", unsafe_allow_html=True)
    if locked:
        return
    if st.button("Update my score" if existing else "Submit my score", key=f"cal_submit_{sid}", type="primary"):
        missing = phone_rubric_ui.missing_levels(scores)
        if missing:
            st.error("Pick a level for every category: " + ", ".join(missing) + ".")
            return
        err = db.save_calibration_score(
            sid,
            me,
            {
                "scores": scores,
                "remarks": remarks,
                "critical_errors": crit,
                "overall_comments": overall,
                "total_score": total,
                "result": result,
            },
        )
        _flash("error", f"Could not save: {err}") if err else _flash("ok", "Your calibration score is saved.")
        st.rerun()


# ---------- an open session ----------
open_id = ss.get("cal_open_session")
if open_id:
    session = next((s for s in sessions if s["id"] == open_id), None)
    if st.button("← Back to calibration sessions"):
        ss.pop("cal_open_session", None)
        st.rerun()
    if not session:
        st.warning("This calibration session no longer exists.")
        st.stop()
    participants = session.get("participants") or []
    if not is_admin and me not in participants:
        st.warning("You're not part of this calibration session.")
        st.stop()

    scores = _scores_for(session["id"])
    done = _all_submitted(session, scores)
    closed = bool(session.get("closed_at"))
    st.markdown(
        f"**Ticket #{session['ticket_id']}** · agent {session.get('agent_name') or 'unknown'} · started by "
        f"{session.get('created_by') or '—'} on {_fmt(session.get('created_at'))}"
        + (" · closed" if closed else "")
    )
    st.caption("Submitted: " + ", ".join(f"{p} {'✅' if p in scores else '⏳'}" for p in participants))

    try:
        with st.spinner(f"Loading conversation #{session['ticket_id']}…"):
            convo = get_conversation(str(session["ticket_id"]))
        render_ticket(
            convo,
            session.get("ticket_url") or conversation_url(str(session["ticket_id"])),
            force_phone=True,
            evaluator_mode=is_evaluator and not is_reviewer,
            show_form=False,
        )
    except IntercomError as e:
        st.error(f"Could not load conversation #{session['ticket_id']}: {e}")

    st.divider()
    _scoring_guide()
    st.divider()
    if me in participants:
        _score_form(session, scores.get(me), locked=done or closed)
        st.divider()

    st.subheader("Comparison")
    if done or is_admin:
        if is_admin and not done:
            st.caption("Only you can see this until everyone has submitted.")
        _comparison(session, scores)
    else:
        st.caption(f"Shown here once everyone has submitted ({len(scores)} of {len(participants)} so far).")

    if is_admin:
        st.divider()
        a1, a3, a2, _ = st.columns([1, 1, 1, 2])
        if a1.button("Reopen session" if closed else "Close session", key=f"cal_close_{session['id']}"):
            err = db.close_calibration_session(session["id"], reopen=closed)
            _flash("error", err) if err else _flash("ok", "Session reopened." if closed else "Session closed.")
            st.rerun()
        # Clears everyone's scores but keeps the session, so the same people can
        # score the call again (e.g. after the scoring guide changed).
        reset_ok = a3.checkbox("Confirm reset", key=f"cal_reset_confirm_{session['id']}")
        if a3.button("Reset all scores", key=f"cal_reset_{session['id']}", disabled=not reset_ok or not scores):
            err = db.reset_calibration_scores(session["id"])
            _flash("error", err) if err else _flash("ok", "All scores cleared. Everyone in the session can score it again.")
            st.rerun()
        confirm = a2.checkbox("Confirm delete", key=f"cal_del_confirm_{session['id']}")
        if a2.button("Delete session", key=f"cal_del_{session['id']}", disabled=not confirm):
            err = db.delete_calibration_session(session["id"])
            if err:
                _flash("error", err)
            else:
                ss.pop("cal_open_session", None)
                _flash("ok", "Calibration session and its scores deleted.")
            st.rerun()
    st.stop()


# ---------- start a session (Weng) ----------
def _ticket_id(raw: str) -> str:
    m = re.search(r"conversation/(\d+)", raw or "")
    if m:
        return m.group(1)
    runs = re.findall(r"\d{6,}", raw or "")
    return max(runs, key=len) if runs else ""


if is_admin:
    with st.expander("➕ Start a calibration session", expanded=not sessions):
        raw = st.text_input("Intercom phone ticket link or number", key="cal_new_ticket")
        evaluator_names = sorted(e["name"] for e in db.list_evaluators() if e.get("name"))
        options = REVIEWER_NAMES + [n for n in evaluator_names if n not in REVIEWER_NAMES]
        picked = st.multiselect("Who scores it", options, key="cal_new_people", help="Pick at least two people. You can include yourself.")
        if st.button("Start session", key="cal_new_start", type="primary"):
            tid = _ticket_id(raw)
            if not tid:
                st.error("No ticket number found in what was entered.")
            elif len(picked) < 2:
                st.error("Pick at least two people to compare.")
            else:
                try:
                    convo = get_conversation(tid)
                    seen = learn_agents_from_conversation(convo)
                    agent = next((n for aid, n in seen.items() if str(aid) == str(convo.get("admin_assignee_id"))), "")
                    try:
                        has_call = bool(get_call_ids(tid))
                    except IntercomError:
                        has_call = False
                except IntercomError as e:
                    st.error(f"Could not load ticket #{tid}: {e}")
                else:
                    sid, err = db.create_calibration_session(tid, conversation_url(tid), agent, picked, me)
                    if err:
                        st.error(f"Could not start the session: {err}")
                    else:
                        note = "" if has_call else " No phone call was found on this ticket, so there's no recording to play."
                        _flash("ok", f"Started calibration on #{tid} for {', '.join(picked)}.{note}")
                        for k in ("cal_new_ticket", "cal_new_people"):
                            ss.pop(k, None)
                        st.rerun()


# ---------- session list ----------
visible = [s for s in sessions if is_admin or me in (s.get("participants") or [])]
visible.sort(key=lambda s: s.get("created_at") or "", reverse=True)
open_sessions = [s for s in visible if not s.get("closed_at")]
closed_sessions = [s for s in visible if s.get("closed_at")]

t_open, t_closed = st.tabs([f"Open ({len(open_sessions)})", f"Closed ({len(closed_sessions)})"])
for tab, rows in ((t_open, open_sessions), (t_closed, closed_sessions)):
    with tab:
        if not rows:
            st.caption("No sessions here." if is_admin else "No calibration sessions for you here.")
        for s in rows:
            sc = _scores_for(s["id"])
            parts = s.get("participants") or []
            c = st.columns([2, 3, 3, 2])
            c[0].markdown(f"**#{s['ticket_id']}**")
            c[1].write(s.get("agent_name") or "Unknown agent")
            status = f"{len(sc)} of {len(parts)} submitted"
            if me in parts and me not in sc and not s.get("closed_at"):
                status += " · waiting on you"
            c[2].caption(status + f" · {_fmt(s.get('created_at'))}")
            if c[3].button("Open", key=f"cal_open_{s['id']}", use_container_width=True):
                ss["cal_open_session"] = s["id"]
                st.rerun()

st.divider()
_scoring_guide()
