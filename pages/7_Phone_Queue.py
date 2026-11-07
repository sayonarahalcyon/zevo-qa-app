"""Phone Queue: phone tickets loaded for evaluation, claimed and audited by
reviewers or phone evaluators.

- A reviewer pastes a batch of Intercom ticket links ("Load phone tickets"),
  then clicks Notify channel once to post one message for the batch to the
  phone QA Slack channel (lib/slack_notify.py).
- Erwin or a phone evaluator claims a waiting ticket. Claiming locks it to
  them, so two people never audit the same call. The person who claimed it, or
  Weng, can release it back to the queue.
- Opening a claimed ticket shows the call recording and transcript (fetched
  from Intercom by the app, so a phone evaluator needs no Intercom access), the
  conversation, and the audit form locked to the phone rubric. Saving the audit
  moves the ticket to Audited (read from qa_entries; nothing extra is stored).

Phone evaluators sign in on this page (lib/evaluator_auth.py) and see only
this page (app.py).
"""

from __future__ import annotations

import re
from datetime import datetime

import streamlit as st

from lib import auth, db, evaluator_auth, slack_notify, ui
from lib.intercom_client import IntercomError, conversation_url, get_call_ids, get_conversation
from lib.ticket_view import learn_agents_from_conversation, render_ticket
from lib.ui import result_badge_md

st.set_page_config(page_title="Phone Queue — ZEVO Quality Evaluation", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

RELEASE_ANY = "Weng Yee"  # besides the person who claimed it, who can release a claimed ticket
ss = st.session_state

is_reviewer = auth.is_signed_in()
is_evaluator = evaluator_auth.is_signed_in()
me = auth.current_reviewer() or evaluator_auth.current_name()

ui.page_heading("Phone Queue")

if not (is_reviewer or is_evaluator):
    st.caption("Phone tickets waiting to be audited.")
    evaluator_auth.render_sign_in()
    st.write("")
    st.caption("Erwin, Weng or Kristine: sign in on Home, then come back here.")
    st.stop()

if is_evaluator and not is_reviewer:
    top = st.columns([3, 1])
    with top[1]:
        evaluator_auth.render_sign_out()
    with top[0]:
        st.caption(f"Auditing as **{me}**. Claim a ticket, listen to the call, and score it.")
    evaluator_auth.render_change_password()
else:
    st.caption(f"Signed in as **{me}**.")

queue = db.list_phone_queue()
if queue is None:
    st.error(
        "The phone queue isn't set up in the database yet. Run "
        "sql/migrations/2026_11_07_phone_queue_and_evaluators.sql in the Supabase SQL editor."
    )
    st.stop()

entries = {str(e.get("id")): e for e in db.list_qa_entries()}


def _fmt(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return str(iso)[:10]


def _status(row: dict) -> str:
    if str(row["ticket_id"]) in entries:
        return "audited"
    return "claimed" if row.get("claimed_by") else "waiting"


def _flash(kind: str, text: str) -> None:
    ss["_pq_msg"] = (kind, text)


msg = ss.pop("_pq_msg", None)
if msg:
    (st.success if msg[0] == "ok" else st.error)(msg[1])


# ---------- an open ticket ----------
open_id = ss.get("pq_open_ticket")
if open_id:
    row = next((r for r in queue if str(r["ticket_id"]) == str(open_id)), None)
    if st.button("← Back to the queue"):
        ss.pop("pq_open_ticket", None)
        st.rerun()
    if not row:
        st.warning("This ticket is no longer in the queue.")
        st.stop()

    status = _status(row)
    entry = entries.get(str(row["ticket_id"]))
    show_form = True
    note = ""
    if status == "claimed" and row.get("claimed_by") != me:
        show_form = False
        note = f"Claimed by {row.get('claimed_by')}. Only they can audit it until it's released."
    elif status == "waiting":
        show_form = False
        note = "Claim this ticket in the queue to audit it."
    elif status == "audited" and not is_reviewer and (entry or {}).get("qa_reviewer") != me:
        show_form = False
        note = f"Already audited by {(entry or {}).get('qa_reviewer') or 'someone else'}."

    try:
        with st.spinner(f"Loading conversation #{open_id}…"):
            convo = get_conversation(str(open_id))
        render_ticket(
            convo,
            row.get("ticket_url") or conversation_url(str(open_id)),
            default_escalated=False,
            force_phone=True,
            evaluator_mode=is_evaluator and not is_reviewer,
            show_form=show_form,
            form_note=note,
        )
    except IntercomError as e:
        st.error(f"Could not load conversation #{open_id}: {e}")
    st.stop()


# ---------- load tickets and notify (reviewers) ----------
def _parse_ticket_ids(raw: str) -> list[str]:
    ids = []
    for chunk in re.split(r"[\s,]+", raw or ""):
        if not chunk:
            continue
        m = re.search(r"conversation/(\d+)", chunk)
        if m:
            tid = m.group(1)
        else:
            runs = re.findall(r"\d{6,}", chunk)
            tid = max(runs, key=len) if runs else ""
        if tid and tid not in ids:
            ids.append(tid)
    return ids


if is_reviewer:
    with st.expander("➕ Load phone tickets", expanded=not queue):
        st.caption(
            "Paste Intercom ticket links or ticket numbers, one per line. They're added to the queue "
            "without notifying anyone. When the batch is complete, click Notify channel below."
        )
        raw = st.text_area("Ticket links", key="pq_load_input", height=140, label_visibility="collapsed")
        if st.button("Add to queue", key="pq_load_button", type="primary"):
            ids = _parse_ticket_ids(raw)
            already = {str(r["ticket_id"]) for r in queue}
            rows, problems, no_call, skipped = [], [], [], []
            for tid in ids:
                if tid in already:
                    skipped.append(tid)
                    continue
                if tid in entries:
                    problems.append(f"#{tid}: already audited")
                    continue
                try:
                    convo = get_conversation(tid)
                except IntercomError as e:
                    problems.append(f"#{tid}: {e}")
                    continue
                seen = learn_agents_from_conversation(convo)
                agent = next((n for aid, n in seen.items() if str(aid) == str(convo.get("admin_assignee_id"))), "")
                try:
                    call_ids = get_call_ids(tid)
                except IntercomError:
                    call_ids = []
                if not call_ids:
                    no_call.append(tid)
                rows.append(
                    {
                        "ticket_id": tid,
                        "ticket_url": conversation_url(tid),
                        "agent_name": agent,
                        "call_ids": call_ids,
                        "loaded_by": me,
                    }
                )
            err = db.add_to_phone_queue(rows)
            if not ids:
                _flash("error", "No ticket numbers found in what was pasted.")
            elif err:
                _flash("error", f"Could not add tickets: {err}")
            else:
                parts = [f"Added {len(rows)} ticket{'s' if len(rows) != 1 else ''} to the queue."]
                if skipped:
                    parts.append(f"{len(skipped)} already in the queue.")
                if no_call:
                    parts.append(
                        "No phone call found on: " + ", ".join(f"#{t}" for t in no_call)
                        + ". They were added, but there's no recording to play."
                    )
                if problems:
                    parts.append("Not added: " + "; ".join(problems) + ".")
                _flash("ok" if rows else "error", " ".join(parts))
                ss.pop("pq_load_input", None)
            st.rerun()

    pending_notice = [r for r in queue if not r.get("notified_at") and _status(r) != "audited"]
    waiting_total = sum(1 for r in queue if _status(r) == "waiting")
    hook = slack_notify.webhook_url()
    n1, n2 = st.columns([1, 3])
    clicked = n1.button(
        f"📣 Notify channel ({len(pending_notice)} new)",
        key="pq_notify",
        disabled=not hook or not pending_notice,
        use_container_width=True,
    )
    if not hook:
        n2.caption("Slack isn't connected yet. Once the channel's webhook is added to the app's Secrets, this button posts one message for the batch.")
    elif not pending_notice:
        n2.caption("Nothing new to announce. Tickets you load next will be listed here.")
    else:
        n2.caption("Posts one message listing the tickets added since the last notice.")
    if clicked:
        pending_notice.sort(key=lambda r: r.get("loaded_at") or "")
        err = slack_notify.post(slack_notify.build_message(pending_notice, waiting_total))
        if err:
            _flash("error", err)
        else:
            db.mark_phone_tickets_notified([r["ticket_id"] for r in pending_notice])
            _flash("ok", f"Posted to the phone QA channel: {len(pending_notice)} ticket(s).")
        st.rerun()
    st.write("")


# ---------- the queue ----------
waiting = sorted([r for r in queue if _status(r) == "waiting"], key=lambda r: r.get("loaded_at") or "")
claimed = sorted([r for r in queue if _status(r) == "claimed"], key=lambda r: r.get("claimed_at") or "")
audited = sorted(
    [r for r in queue if _status(r) == "audited"],
    key=lambda r: (entries[str(r["ticket_id"])].get("updated_at") or ""),
    reverse=True,
)
mine = [r for r in claimed if r.get("claimed_by") == me]

t_wait, t_claimed, t_done = st.tabs([f"Waiting ({len(waiting)})", f"Claimed ({len(claimed)})", f"Audited ({len(audited)})"])

with t_wait:
    if not waiting:
        st.caption("No tickets waiting.")
    for r in waiting:
        tid = str(r["ticket_id"])
        c = st.columns([2, 3, 2, 2, 1])
        c[0].markdown(f"**#{tid}**")
        c[1].write(r.get("agent_name") or "Unknown agent")
        c[2].caption(f"Loaded {_fmt(r.get('loaded_at'))}" + ("" if r.get("call_ids") else " · no call found"))
        if c[3].button("Claim & open", key=f"pq_claim_{tid}", type="primary", use_container_width=True):
            err = db.claim_phone_ticket(tid, me)
            if err:
                _flash("error", f"#{tid}: {err}")
            else:
                ss["pq_open_ticket"] = tid
            st.rerun()
        if is_reviewer and c[4].button("Remove", key=f"pq_remove_{tid}"):
            err = db.remove_from_phone_queue(tid)
            _flash("error", err) if err else _flash("ok", f"Removed #{tid} from the queue.")
            st.rerun()

with t_claimed:
    if mine:
        st.caption(f"You have {len(mine)} claimed ticket{'s' if len(mine) != 1 else ''} to audit.")
    if not claimed:
        st.caption("No claimed tickets.")
    for r in claimed:
        tid = str(r["ticket_id"])
        holder = r.get("claimed_by")
        c = st.columns([2, 3, 2, 2, 1])
        c[0].markdown(f"**#{tid}**")
        c[1].write(r.get("agent_name") or "Unknown agent")
        c[2].caption(f"{'You' if holder == me else holder} · since {_fmt(r.get('claimed_at'))}")
        if (holder == me or is_reviewer) and c[3].button(
            "Open" if holder == me else "View", key=f"pq_open_{tid}", use_container_width=True
        ):
            ss["pq_open_ticket"] = tid
            st.rerun()
        if (holder == me or me == RELEASE_ANY) and c[4].button("Release", key=f"pq_release_{tid}"):
            err = db.release_phone_ticket(tid)
            _flash("error", err) if err else _flash("ok", f"Released #{tid} back to the queue.")
            st.rerun()

with t_done:
    if not audited:
        st.caption("No audited tickets yet.")
    for r in audited:
        tid = str(r["ticket_id"])
        e = entries[tid]
        c = st.columns([2, 3, 2, 2, 1])
        c[0].markdown(f"**#{tid}**")
        c[1].write(e.get("agent_name") or r.get("agent_name") or "Unknown agent")
        c[2].markdown(
            f"{e.get('total_score', '—')}/100 &nbsp; {result_badge_md(e.get('result', ''))}"
            + (" · 🧪 test" if e.get("is_test") else ""),
            unsafe_allow_html=True,
        )
        c[3].caption(f"{e.get('qa_reviewer') or '—'} · {e.get('qa_date') or ''}")
        if (is_reviewer or e.get("qa_reviewer") == me) and c[4].button("Open", key=f"pq_done_open_{tid}"):
            ss["pq_open_ticket"] = tid
            st.rerun()
