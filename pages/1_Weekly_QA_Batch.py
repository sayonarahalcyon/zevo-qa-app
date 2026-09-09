"""Weekly QA batch — pulls 3 topic-diverse tickets per agent per custom date
range, plus Quick Sample: a one-off tool to pull a single random ticket in
any date range. Both live here, on the main page (not the sidebar) — this
page requires signing in; anyone not signed in gets a sign-in prompt and
none of the ticket-selection controls or pull logic run.
"""

import random
import re
from datetime import date, timedelta

import streamlit as st
import streamlit.components.v1 as components

from lib import auth, db, sampling, ui
from lib.intercom_client import IntercomError, conversation_url, get_conversation, search_conversations
from lib.ticket_view import render_ticket

st.set_page_config(page_title="Weekly QA Batch — Ticket QA Sampler", page_icon=ui.LOGO_URL, layout="wide")
ui.inject_style()

# ---------- reset unsaved ticket-selection state on a real browser reload ----------
# Streamlit keeps the same session_state across a hard refresh, so filters,
# a Quick Sample pool, or a manually-loaded ticket used to stay on screen
# after F5 — nothing here is meant to survive a reload, unlike the QA Log's
# saved audits. A real reload (not a widget rerun, not sidebar navigation,
# both of which never touch browser navigation at all) sets ?reset=1 via
# the script below, and we clear the unsaved keys for it here before any
# widget reads them. Persisted data (weekly picks, the QA Log) is untouched.
_RESET_KEYS = [
    "batch_agent_select", "batch_range_start", "batch_range_end", "batch_exclude_fin", "batch_open_ticket_id",
    "qs_pool", "qs_pool_total", "qs_used_ids", "qs_current_ticket_id", "qs_current_ticket_url", "qs_fin_filter_warning",
    "qs_start_date", "qs_end_date", "qs_exclude_fin", "qs_agent_filter", "qs_skip_reviewed",
    "manual_open_ticket_id", "manual_ticket_input",
]
if st.query_params.get("reset") == "1":
    for _k in _RESET_KEYS:
        st.session_state.pop(_k, None)
    del st.query_params["reset"]

components.html(
    """
    <script>
    (function () {
        try {
            var nav = window.parent.performance.getEntriesByType('navigation')[0];
            if (nav && nav.type === 'reload') {
                var url = new URL(window.parent.location.href);
                if (url.searchParams.get('reset') !== '1') {
                    url.searchParams.set('reset', '1');
                    window.parent.location.replace(url.toString());
                }
            }
        } catch (e) {}
    })();
    </script>
    """,
    height=0,
)

if not auth.is_signed_in():
    ui.page_heading("Weekly QA Batch")
    st.warning("Sign in to pull and score tickets. Head to Home and sign in as one of the three reviewers.")
    st.page_link("pages/0_Home.py", label="🏠 Go to Home to sign in", use_container_width=False)
    st.stop()

ui.page_heading("Ticket Selection")
st.caption(f"Reviewing as **{auth.current_reviewer()}**")

st.write("")

ss = st.session_state

agent_roster = {a["name"].lower(): a for a in db.list_agents()}
agent_names = sorted({a["name"] for a in db.list_agents() if a.get("name")})

col_batch, col_quick = st.columns(2, gap="large")

# ---------- Weekly QA batch ----------
with col_batch:
    with st.container(border=True):
        st.subheader("Weekly QA batch")

        def monday_of(d: date) -> date:
            return d - timedelta(days=d.weekday())

        _this_monday = monday_of(date.today())
        ss.setdefault("batch_range_start", _this_monday)
        ss.setdefault("batch_range_end", _this_monday + timedelta(days=6))
        ss.setdefault("batch_open_ticket_id", None)

        agent_options = ["Select an agent..."] + agent_names
        agent_choice = st.selectbox("Agent", agent_options, key="batch_agent_select")
        agent_input = "" if agent_choice == "Select an agent..." else agent_choice

        agent_id = agent_roster.get(agent_input.lower(), {}).get("id") if agent_input else None

        if not agent_input:
            st.caption("Pick an agent to begin.")

        rc1, rc2 = st.columns(2)
        start_date = rc1.date_input("Start date", key="batch_range_start")
        end_date = rc2.date_input("End date", key="batch_range_end")

        range_valid = end_date >= start_date
        is_current_period = range_valid and start_date <= date.today() <= end_date

        if not range_valid:
            st.error("End date must be on or after the start date.")
        else:
            days_in_range = (end_date - start_date).days + 1
            if is_current_period:
                st.caption(f"📍 {days_in_range}-day range, in progress")
            elif start_date > date.today():
                st.caption(f"{days_in_range}-day range, starts in the future")
            else:
                st.caption(f"{days_in_range}-day range, completed")

        exclude_fin = st.checkbox("Exclude Fin AI-handled tickets", value=True, key="batch_exclude_fin")

        picks_row = (
            db.get_weekly_picks(agent_id, start_date.isoformat(), end_date.isoformat())
            if agent_id and range_valid
            else None
        )
        tickets = (picks_row or {}).get("tickets") or []

        st.markdown("**Progress in range**")
        slot_cols = st.columns(3)
        for i in range(3):
            with slot_cols[i]:
                if i < len(tickets):
                    t = tickets[i]
                    state = "✅ Reviewed" if t.get("reviewed") else "Pulled"
                    if st.button(t.get("topic") or f"#{t['id']}", key=f"slot_{i}", use_container_width=True):
                        ss["batch_open_ticket_id"] = t["id"]
                        ss["qs_current_ticket_id"] = None
                        ss["manual_open_ticket_id"] = None
                        st.rerun()
                    st.caption(state)
                else:
                    st.caption(f"Slot {i+1}\n\n_empty_")

        remaining = 3 - len(tickets)
        if not range_valid:
            pull_label, pull_disabled = "Fix date range", True
        elif not agent_id:
            pull_label, pull_disabled = "Pick an agent", True
        elif remaining <= 0:
            pull_label, pull_disabled = "Quota met (3 of 3)", True
        elif is_current_period:
            pull_label, pull_disabled = f"Pull today's ticket (#{len(tickets)+1} of 3)", False
        else:
            pull_label, pull_disabled = f"Pick remaining {remaining} ticket{'s' if remaining != 1 else ''}", False

        batch_status = st.empty()

        if st.button(pull_label, type="primary", disabled=pull_disabled, use_container_width=True, key="batch_pull_button"):
            have_ids = {t["id"] for t in tickets}
            have_topics = [t.get("topic") for t in tickets if t.get("topic")]
            reviewed_map = db.list_reviewed()
            needed_now = 1 if is_current_period else remaining
            range_end_effective = min(end_date, date.today())

            with st.spinner("Searching Intercom…"):
                try:
                    results, _total, _fin = search_conversations(start_date, range_end_effective, exclude_fin, agent_id)
                except IntercomError as e:
                    batch_status.error(str(e))
                    results = None

            if results is not None:
                candidates = []
                for r in results:
                    rid = str(r.get("id", "")).replace("conversation_", "")
                    if rid and rid not in have_ids and rid not in reviewed_map:
                        candidates.append({"id": rid, "text": r.get("source", {}).get("body", "") or r.get("text", ""), "title": r.get("title", ""), "url": r.get("url") or conversation_url(rid)})

                if not candidates:
                    batch_status.info(
                        f"No new closed, unreviewed tickets from {agent_input} yet in this range. Check back later."
                        if is_current_period
                        else f"No closed, unreviewed tickets found for {agent_input} in this range."
                    )
                else:
                    batch_status.info(f"Reading {min(len(candidates), 40)} ticket(s) to find different concerns…")
                    picks = sampling.pick_diverse(candidates, needed_now, have_topics, agent_input)
                    new_tickets = [
                        {
                            "id": p["id"],
                            "topic": p.get("topic", ""),
                            "reason": p.get("reason", ""),
                            "subject": p.get("subject", ""),
                            "url": p.get("url") or conversation_url(p["id"]),
                            "reviewed": False,
                        }
                        for p in picks
                    ]
                    merged = (tickets + new_tickets)[:3]
                    db.save_weekly_picks(agent_id, agent_input, start_date.isoformat(), end_date.isoformat(), merged)
                    batch_status.empty()
                    if new_tickets:
                        ss["batch_open_ticket_id"] = new_tickets[0]["id"]
                        ss["qs_current_ticket_id"] = None
                        ss["manual_open_ticket_id"] = None
                    st.rerun()

# ---------- Quick Sample: pull one random ticket, any date range ----------
with col_quick:
    with st.container(border=True):
        st.subheader("🎲 Quick Sample")
        st.caption("A separate one-off tool — pulls a single random closed ticket in any date range, independent of the weekly batch.")

        ss.setdefault("qs_pool", [])
        ss.setdefault("qs_pool_total", 0)
        ss.setdefault("qs_used_ids", set())
        ss.setdefault("qs_current_ticket_id", None)
        ss.setdefault("qs_fin_filter_warning", False)

        def qs_resolve_agent_id(raw: str):
            raw = (raw or "").strip()
            if not raw:
                return None, True
            if raw.isdigit():
                return raw, True
            hit = agent_roster.get(raw.lower())
            if hit:
                return hit["id"], True
            return None, False

        def qs_pull_pool():
            agent_id2, _ok = qs_resolve_agent_id(qs_agent_filter)
            if qs_start_date > qs_end_date:
                st.error('Check your dates — "From" is after "To".')
                return
            with st.spinner("Pulling matching tickets from Intercom…"):
                try:
                    results, total, fin_applied = search_conversations(qs_start_date, qs_end_date, qs_exclude_fin, agent_id2)
                except IntercomError as e:
                    st.error(f"{e} ")
                    return
            pool = []
            for r in results:
                rid = str(r.get("id", "")).replace("conversation_", "")
                if not rid:
                    continue
                pool.append({"raw_id": rid, "title": r.get("title", ""), "text": r.get("source", {}).get("body", "") or r.get("text", ""), "url": r.get("url") or conversation_url(rid)})
            ss["qs_pool"] = pool
            ss["qs_pool_total"] = total
            ss["qs_used_ids"] = set()
            ss["qs_fin_filter_warning"] = qs_exclude_fin and not fin_applied
            if pool:
                qs_pick_random()
            else:
                ss["qs_current_ticket_id"] = None

        def qs_eligible_pool():
            reviewed = db.list_reviewed() if qs_skip_reviewed else {}
            return [t for t in ss["qs_pool"] if not (qs_skip_reviewed and t["raw_id"] in reviewed)]

        def qs_pick_random():
            candidates = [t for t in qs_eligible_pool() if t["raw_id"] not in ss["qs_used_ids"]]
            if not candidates:
                candidates = qs_eligible_pool()
                if not candidates:
                    ss["qs_current_ticket_id"] = None
                    return
                ss["qs_used_ids"] = set()  # exhausted this pass, allow repeats
            pick = random.choice(candidates)
            ss["qs_used_ids"].add(pick["raw_id"])
            ss["qs_current_ticket_id"] = pick["raw_id"]
            ss["qs_current_ticket_url"] = pick["url"]

        qs_preset_cols = st.columns(3)
        if qs_preset_cols[0].button("7d", use_container_width=True, key="qs_preset_7d"):
            ss["qs_start_date"] = date.today() - timedelta(days=7)
            ss["qs_end_date"] = date.today()
        if qs_preset_cols[1].button("30d", use_container_width=True, key="qs_preset_30d"):
            ss["qs_start_date"] = date.today() - timedelta(days=30)
            ss["qs_end_date"] = date.today()
        if qs_preset_cols[2].button("This mo.", use_container_width=True, key="qs_preset_mo"):
            ss["qs_start_date"] = date.today().replace(day=1)
            ss["qs_end_date"] = date.today()

        ss.setdefault("qs_start_date", date.today() - timedelta(days=7))
        ss.setdefault("qs_end_date", date.today())

        qs_start_date = st.date_input("From", key="qs_start_date")
        qs_end_date = st.date_input("To", key="qs_end_date")
        st.caption("Only **closed** conversations are sampled.")

        qs_exclude_fin = st.checkbox("Exclude Fin AI-handled tickets", value=True, key="qs_exclude_fin")

        qs_agent_filter = st.selectbox("Agent", ["All agents"] + agent_names, key="qs_agent_filter")
        if qs_agent_filter == "All agents":
            qs_agent_filter = ""

        qs_skip_reviewed = st.checkbox("Skip already-reviewed tickets", value=True, key="qs_skip_reviewed")

        if st.button("Pull random ticket", type="primary", use_container_width=True, key="qs_pull_button"):
            ss["batch_open_ticket_id"] = None
            ss["manual_open_ticket_id"] = None
            qs_pull_pool()

        if ss["qs_pool"]:
            eligible = len(qs_eligible_pool())
            msg = f"**{ss['qs_pool_total']:,}** tickets match · sampling from a pool of **{len(ss['qs_pool'])}** (Intercom's 150-per-pull limit)"
            if qs_skip_reviewed:
                msg += f", **{eligible}** not yet reviewed"
            st.caption(msg)
        else:
            st.caption("Set a timeframe and pull a ticket to begin.")

        if ss.get("qs_fin_filter_warning"):
            st.warning(
                "Couldn't filter Fin-handled tickets server-side in this workspace — showing all closed tickets instead. "
                "Double-check the Fin badge on what you review.",
                icon="⚠️",
            )

st.write("")

# ---------- Manually log a ticket (escalated) ----------
# For tickets spotted directly in Intercom — a complaint, an escalation,
# something a TL flags — rather than surfaced by the random Weekly QA batch
# or Quick Sample pulls above. Scored with the same form as any other
# ticket; the only difference is it's auto-flagged "🚩 Escalated" (still
# editable) so it's easy to tell apart in the QA Log.
with st.container(border=True):
    st.subheader("🚩 Manually log a ticket")
    st.caption(
        "Noticed something in Intercom that needs a QA look — outside the random pull? "
        "Paste the ticket ID or its Intercom link below."
    )
    ss.setdefault("manual_open_ticket_id", None)
    mc1, mc2 = st.columns([4, 1])
    manual_raw = mc1.text_input(
        "Ticket ID or Intercom link",
        key="manual_ticket_input",
        label_visibility="collapsed",
        placeholder="e.g. 215475815894618 or an Intercom conversation link",
    )
    if mc2.button("Load ticket", use_container_width=True, key="manual_load_button"):
        digits = re.findall(r"\d+", manual_raw or "")
        manual_id = digits[-1] if digits else ""
        if not manual_id:
            st.error("Couldn't find a ticket ID in that — paste the numeric ID or the full Intercom link.")
        else:
            ss["manual_open_ticket_id"] = manual_id
            ss["batch_open_ticket_id"] = None
            ss["qs_current_ticket_id"] = None
            st.rerun()

st.write("")
st.divider()

# ---------- main stage ----------
# Manually-logged tickets take priority (an explicit just-now action),
# then Quick Sample if a ticket is loaded there, then the weekly batch.
manual_ticket_id = ss.get("manual_open_ticket_id")
qs_ticket_id = ss.get("qs_current_ticket_id")
open_id = ss.get("batch_open_ticket_id")

if manual_ticket_id:
    if st.button("← Back to manual entry"):
        ss["manual_open_ticket_id"] = None
        st.rerun()
    try:
        with st.spinner(f"Loading conversation #{manual_ticket_id}…"):
            convo = get_conversation(manual_ticket_id)
        render_ticket(convo, conversation_url(manual_ticket_id), default_escalated=True)
    except IntercomError as e:
        st.error(f"Could not load conversation #{manual_ticket_id}: {e}")
elif qs_ticket_id:
    try:
        with st.spinner(f"Loading conversation #{qs_ticket_id}…"):
            convo = get_conversation(qs_ticket_id)
    except IntercomError as e:
        st.error(f"Could not load conversation #{qs_ticket_id}: {e}")
        convo = None
    if convo:
        st.caption(f"Quick Sample pool: {len(ss['qs_pool'])} tickets in this timeframe · {ss['qs_pool_total']:,} total match")
        render_ticket(convo, ss.get("qs_current_ticket_url") or conversation_url(qs_ticket_id), on_pick_another=qs_pick_random)
elif not open_id:
    st.info(
        "Pick an agent and a date range above, then pull this range's QA batch — 3 topic-diverse "
        "tickets per agent. Or use **Quick Sample** to pull one single random ticket instead."
    )
else:
    ticket_url = next((t["url"] for t in tickets if t["id"] == open_id), conversation_url(open_id))
    try:
        with st.spinner(f"Loading conversation #{open_id}…"):
            convo = get_conversation(open_id)
        render_ticket(convo, ticket_url)
    except IntercomError as e:
        st.error(f"Could not load conversation #{open_id}: {e}")
