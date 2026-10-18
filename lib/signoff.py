"""Agent sign-off on QA evaluations.

Every non-test evaluation a reviewer logs asks the agent to open it, read it,
and sign off. The prompt lives at the top of My Dashboard (lib/agent_dashboard)
and stays there until the agent signs. Signing off confirms the agent has READ
the evaluation. It does not mean they agree; disputing stays available on the
same evaluation through the existing "Question or dispute" form.

How "needs sign-off" is decided (one row per evaluation in evaluation_signoffs):

  no row                      -> pending (every new evaluation starts here)
  status 'signed'             -> done, unless a reviewer edited the evaluation
                                 AFTER the agent signed, then pending again
                                 ("please review again")
  status 'not_required'       -> never asked (evaluations that existed when the
                                 feature was switched on; see the SQL migration)
  is_test evaluations         -> never asked

If the evaluation_signoffs table is missing (SQL not run yet) db.list_signoffs()
returns None and the whole feature stays hidden rather than flagging every
evaluation as pending.

There is no outside notification (Slack or email). The "notification" is the
prompt an agent sees the next time they open My Dashboard. The app cannot reach
anyone who does not open it.
"""

from datetime import datetime, timezone

import streamlit as st

from lib import activity, db

PENDING = "pending"
RESIGN = "resign"  # edited after the agent signed
SIGNED = "signed"
NOT_REQUIRED = "not_required"

# How many pending evaluations are opened at once at the top of My Dashboard.
MAX_SHOWN = 10


def _parse(ts) -> datetime | None:
    """ISO text (naive means UTC) to an aware UTC datetime, or None."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_edit(entry: dict) -> dict | None:
    """Most recent edit_log item with a readable timestamp, or None."""
    items = [i for i in (entry.get("edit_log") or []) if _parse(i.get("edited_at"))]
    return max(items, key=lambda i: _parse(i["edited_at"])) if items else None


def state(entry: dict, signoff: dict | None) -> str:
    """PENDING, RESIGN, SIGNED or NOT_REQUIRED for one evaluation."""
    if entry.get("is_test"):
        return NOT_REQUIRED
    if not signoff:
        return PENDING
    status = signoff.get("status")
    if status == "not_required":
        return NOT_REQUIRED
    signed_at = _parse(signoff.get("signed_at"))
    edit = last_edit(entry)
    if signed_at and edit and _parse(edit["edited_at"]) > signed_at:
        return RESIGN
    return SIGNED if signed_at else PENDING


def by_entry(signoffs: list[dict]) -> dict[str, dict]:
    return {s["entry_id"]: s for s in signoffs if s.get("entry_id")}


def pending(entries: list[dict], signoffs: list[dict]) -> list[dict]:
    """Evaluations still waiting on the agent, newest first."""
    lookup = by_entry(signoffs)
    rows = [e for e in entries if state(e, lookup.get(e.get("id"))) in (PENDING, RESIGN)]
    return sorted(rows, key=lambda e: (e.get("qa_date") or "", e.get("updated_at") or ""), reverse=True)


def label_suffix(st_: str) -> str:
    return {
        PENDING: " · 🔔 Awaiting sign-off",
        RESIGN: " · 🔔 Edited, please review again",
        SIGNED: " · ✅ Signed off",
    }.get(st_, "")


def _fmt_date(ts) -> str:
    dt = _parse(ts)
    return dt.strftime("%b %-d, %Y") if dt else "—"


def status_caption(entry: dict, signoff: dict | None, *, as_agent: bool) -> None:
    """One line under an evaluation's details saying where its sign-off stands.
    Nothing for evaluations that never needed one."""
    s = state(entry, signoff)
    who = "You" if as_agent else (entry.get("agent_name") or "The agent")
    if s == SIGNED:
        st.caption(f"✅ {who} signed off on {_fmt_date(signoff.get('signed_at'))}.")
        if signoff.get("comment"):
            st.caption(f"Comment: {signoff['comment']}")
    elif s == RESIGN:
        edit = last_edit(entry) or {}
        st.caption(
            f"🔔 Edited by {edit.get('edited_by') or 'a reviewer'} on {_fmt_date(edit.get('edited_at'))}, "
            f"after {who.lower() if not as_agent else 'you'} signed off. Waiting for a new sign-off."
        )
    elif s == PENDING:
        if as_agent:
            st.caption("🔔 Waiting for your sign-off. See the top of this page.")
        else:
            st.caption(f"🔔 Waiting for {who} to sign off.")


def render_form(entry: dict, agent: dict) -> None:
    """Acknowledge checkbox, optional comment, and the Sign off button for one
    pending evaluation. Widget keys are namespaced by evaluation id."""
    eid = entry["id"]
    st.markdown("**Sign off**")
    st.caption(
        "Signing off confirms you have read this evaluation. It does not mean you agree with it. "
        "If you disagree or have a question, use the Question or dispute form below instead or as well."
    )
    ack = st.checkbox("I have read this evaluation.", key=f"signoff_ack_{eid}")
    comment = st.text_area("Comment for the reviewer (optional)", key=f"signoff_comment_{eid}")
    if st.button("Sign off", key=f"signoff_btn_{eid}", type="primary"):
        if not ack:
            st.error("Tick the box to confirm you have read it.")
            return
        err = db.sign_off(eid, agent.get("id"), agent.get("name") or entry.get("agent_name") or "", comment.strip())
        if err:
            st.error(f"Couldn't save your sign-off: {err}")
            return
        activity.log("sign_off", f"{agent.get('name')}, ticket {entry.get('ticket_id') or eid}", "agent")
        st.success("Signed off. Thank you.")
        st.rerun()


# ---------- reviewer view ----------

def render_reviewer_panel() -> None:
    """QA Log section for reviewers: who still has evaluations waiting for
    sign-off, how long they have waited, and recent sign-offs with comments."""
    render_panel()


def render_team_panel(team_agents: list[dict]) -> None:
    """Team Lead Dashboard section: the same view as the reviewers' panel,
    limited to one team lead's agents. Read-only."""
    render_panel(team_agents, key_prefix="tl_signoff")


def _on_team(entry: dict, ids: set, names: set) -> bool:
    return entry.get("agent_id") in ids or (entry.get("agent_name") or "").lower() in names


def render_panel(team_agents: list[dict] | None = None, *, key_prefix: str = "signoff") -> None:
    """Shared body of both panels. team_agents=None means every agent."""
    import pandas as pd

    signoffs = db.list_signoffs()
    if signoffs is None:
        if team_agents is None:
            st.caption(
                "Agent sign-off is not switched on yet. Run the sign-off SQL in Supabase "
                "(sql/migrations/2026_10_18_add_evaluation_signoffs.sql) to turn it on."
            )
        else:
            st.caption("Agent sign-off is not switched on yet.")
        return

    entries = [e for e in db.list_qa_entries() if not e.get("is_test")]
    if team_agents is not None:
        ids = {a["id"] for a in team_agents}
        names = {(a.get("name") or "").lower() for a in team_agents}
        entries = [e for e in entries if _on_team(e, ids, names)]
    lookup = by_entry(signoffs)
    waiting = pending(entries, signoffs)
    today = datetime.now(timezone.utc).date()

    signed_rows = [
        (e, lookup[e["id"]]) for e in entries if state(e, lookup.get(e["id"])) == SIGNED
    ]
    c1, c2, c3 = st.columns(3)
    c1.metric("Waiting for sign-off", len(waiting))
    c2.metric("Signed off", len(signed_rows))
    waiting_agents = {e.get("agent_name") for e in waiting}
    c3.metric("Agents with something waiting", len(waiting_agents))
    if team_agents is not None and not entries:
        st.caption("No evaluations on file for your team yet.")

    if waiting:
        rows = []
        for e in waiting:
            created = _parse(e.get("created_at"))
            rows.append(
                {
                    "Agent": e.get("agent_name") or "—",
                    "Ticket": e.get("ticket_id") or "—",
                    "Evaluation date": e.get("qa_date") or "—",
                    "Score": e.get("total_score"),
                    "Result": e.get("result") or "—",
                    "Reviewer": e.get("qa_reviewer") or "—",
                    "Days waiting": (today - created.date()).days if created else None,
                    "Why": "Edited after signing" if state(e, lookup.get(e["id"])) == RESIGN else "New",
                }
            )
        df = pd.DataFrame(rows).sort_values(["Agent", "Evaluation date"], ascending=[True, False])
        agent_pick = st.selectbox(
            "Filter by agent", ["All agents"] + sorted(waiting_agents - {None}), key=f"{key_prefix}_agent_filter"
        )
        if agent_pick != "All agents":
            df = df[df["Agent"] == agent_pick]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.success("Nothing is waiting. Every evaluation that needs a sign-off has one.")

    with st.expander(f"Recent sign-offs ({len(signed_rows)})"):
        recent = sorted(signed_rows, key=lambda r: r[1].get("signed_at") or "", reverse=True)[:50]
        if not recent:
            st.caption("No sign-offs yet.")
        for e, s in recent:
            line = (
                f"**{e.get('agent_name') or '—'}** signed off on {_fmt_date(s.get('signed_at'))} · "
                f"ticket {e.get('ticket_id') or '—'} · {e.get('result') or '—'} {e.get('total_score')}/100"
            )
            st.markdown(line)
            if s.get("comment"):
                st.caption(f"Comment: {s['comment']}")
