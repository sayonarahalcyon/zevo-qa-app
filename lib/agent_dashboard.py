"""Shared read-only QA-evaluation view for one agent.

Factored out of pages/4_My_Dashboard.py so the Team Lead Dashboard can drill
into any one of its agents using the exact same summary metrics, score
trend, category breakdown, and audit list an agent sees of themselves —
rather than a second, drifting copy of this rendering.

Since 2026-10-04 render() opens with a Weekly / Monthly / To date picker
(lib/period_picker) and everything below it follows the chosen period, except
the "This Week (of 3)" quota tile, which is always the current calendar week.
period_key namespaces the picker's widget keys.

render() doesn't handle sign-in/sign-out or whose dashboard this is — the
caller owns that (My Dashboard shows its own agent_auth sign-out and "viewing
your evaluations" caption; the Team Lead Dashboard shows a back button and
the agent's name instead). It never writes to qa_entries.

show_dispute_form controls the inline "Question or dispute about this
audit?" form on each audit: both My Dashboard and the Team Lead Dashboard's
drill-down leave it at the default (True). submitted_by distinguishes who's
actually filling it in: My Dashboard leaves it unset, since the signed-in
agent is submitting on their own behalf; the Team Lead Dashboard's
drill-down passes the signed-in team lead's name, since they're submitting
on the agent's behalf (2026-10-03) — the submission is still recorded
against the agent (same agent_id/agent_name as always), with submitted_by
noting who actually filed it, visible to both the agent on My Dashboard and
the reviewer in the Questions & Disputes inbox.

can_sign_off (2026-10-18) is True only on My Dashboard. It puts a "Needs your
sign-off" section above the period picker (every evaluation still waiting on
the agent, whatever period is picked) with the sign-off form on each. Anywhere
else (team lead drill-down, View as team lead) the same sign-off state is shown
read-only as a line under each evaluation. See lib/signoff.py.

preview_sign_off (2026-10-18) is for View as agent: the agent's own layout, with
the "Needs your sign-off" section and its form drawn disabled so a reviewer can
see what the agent sees but cannot sign (and no dispute form is shown).
"""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from lib import activity, db, disputes, period_picker, signoff, weeks
from lib.constants import CRITICAL_ERRORS, RUBRIC
from lib.intercom_client import conversation_url
from lib.ui import result_badge_md

# Reuses the app's existing accent/status colors (lib/ui.py's --qa-accent /
# --qa-coach / --qa-fail) rather than introducing a new palette, so these
# charts read as the same product as the result pills elsewhere.
_ACCENT = "#14a173"
_COACH = "#d69a34"
_FAIL = "#cf4a5c"
_MUTED = "#5c6f66"


def render(
    agent: dict,
    *,
    show_dispute_form: bool = True,
    submitted_by: str | None = None,
    period_key: str = "agent_dash",
    can_sign_off: bool = False,
    preview_sign_off: bool = False,
) -> None:
    entries = [
        e
        for e in db.list_qa_entries()
        if e.get("agent_id") == agent["id"] or (e.get("agent_name") or "").lower() == agent["name"].lower()
    ]
    # Same rule as the QA Log dashboard and Home: test audits never count
    # toward an agent's own numbers, though they still show up (marked) in
    # the list below.
    all_real_entries = [e for e in entries if not e.get("is_test")]

    if not all_real_entries:
        st.info("No QA evaluations on file yet.")
        return

    # ---------- agent sign-off ----------
    # None means the evaluation_signoffs table isn't there yet (SQL not run),
    # in which case nothing about sign-off is shown at all.
    signoffs = db.list_signoffs()
    signoff_lookup = signoff.by_entry(signoffs) if signoffs is not None else None
    agent_layout = can_sign_off or preview_sign_off  # pending ones are shown at the top, not in the list
    if signoffs is not None and agent_layout:
        _render_pending_signoffs(all_real_entries, signoffs, agent, preview=preview_sign_off)

    # ---------- period picker ----------
    # Weekly / Monthly / To date (lib/period_picker). Everything below — the
    # summary, the trend, the category breakdown, and the evaluation list — is
    # limited to the chosen window; the weekly-quota tile is the one exception
    # (always the current calendar week).
    period = period_picker.pick(entries, key_prefix=period_key)
    activity.changed(
        period_key, period.label, "change_period", f"{agent['name']}: {period.label}",
        "team_lead" if submitted_by else "agent",
    )
    entries = period.filter(entries)
    real_entries = [e for e in entries if not e.get("is_test")]
    test_count = len(entries) - len(real_entries)

    # ---------- summary ----------
    total = len(real_entries)
    avg_score = round(sum(e.get("total_score") or 0 for e in real_entries) / total, 1) if total else None
    pass_rate = (
        round(sum(1 for e in real_entries if e.get("result") == "PASS") / total * 100, 1) if total else None
    )

    today = date.today()
    week_count = sum(1 for e in all_real_entries if weeks.in_week(e.get("qa_date"), today))

    if test_count:
        st.caption(f"🧪 {test_count} test audit{'s' if test_count != 1 else ''} excluded from these numbers.")
    if not entries:
        st.info(f"No evaluations {period.phrase}." if not period.is_all_time else "No QA evaluations on file yet.")

    c1, c2, c3, c4 = st.columns(4)
    # The "?" bubbles spell out how each number is calculated. Worded neutrally
    # (not "you"/"your") because a team lead sees this same view of an agent.
    c1.metric(
        "Total Evaluations",
        total,
        help=f"The number of non-test evaluations logged {period.phrase}. Test audits are never counted.",
    )
    c2.metric(
        "Avg Score",
        avg_score if avg_score is not None else "—",
        help=f"The average total score (out of 100) across the {total} non-test evaluations logged {period.phrase}.",
    )
    c3.metric(
        "Pass Rate",
        f"{pass_rate}%" if pass_rate is not None else "—",
        help=(
            f"The share of the {total} non-test evaluations logged {period.phrase} that scored PASS "
            "(85 or higher out of 100)."
        ),
    )
    c4.metric(
        "This Week (of 3)",
        f"{week_count} / 3",
        help=(
            "How many evaluations have been logged this calendar week (Sunday to Saturday), out of the 3 "
            "expected per agent each week. Always the current week, whatever period is selected above."
        ),
    )

    st.divider()

    # ---------- score trend ----------
    st.subheader(
        "Score trend",
        help=(
            "Each dot is one non-test evaluation, plotted by its date and total score (out of 100), for the "
            f"period selected above ({period.label}). The dashed lines mark the PASS (85) and COACHING (70) "
            "thresholds. At least two scored evaluations in the period are needed to draw the line."
        ),
    )
    trend_rows = sorted(
        (
            {"Date": e["qa_date"], "Score": e.get("total_score") or 0}
            for e in real_entries
            if e.get("qa_date")
        ),
        key=lambda r: r["Date"],
    )

    if len(trend_rows) >= 2:
        trend_df = pd.DataFrame(trend_rows)
        trend_df["Date"] = pd.to_datetime(trend_df["Date"])

        line = (
            alt.Chart(trend_df)
            .mark_line(color=_ACCENT, strokeWidth=2, point=alt.OverlayMarkDef(size=50, color=_ACCENT))
            .encode(
                x=alt.X("Date:T", title=None),
                y=alt.Y("Score:Q", title="Total score", scale=alt.Scale(domain=[0, 100])),
                tooltip=[alt.Tooltip("Date:T", title="Date"), alt.Tooltip("Score:Q", title="Score")],
            )
        )
        # Dashed reference lines at the same PASS/COACHING thresholds used
        # everywhere else in the app (see lib/constants.compute_result) —
        # status color, not a third data series, so no legend entry is
        # needed for them.
        pass_rule = (
            alt.Chart(pd.DataFrame({"y": [85]}))
            .mark_rule(strokeDash=[4, 4], color=_ACCENT, opacity=0.6)
            .encode(y="y:Q")
        )
        coach_rule = (
            alt.Chart(pd.DataFrame({"y": [70]}))
            .mark_rule(strokeDash=[4, 4], color=_COACH, opacity=0.6)
            .encode(y="y:Q")
        )

        st.altair_chart((pass_rule + coach_rule + line).properties(height=280), use_container_width=True)
        st.caption("Dashed lines mark the PASS (85) and COACHING (70) thresholds.")
    else:
        st.caption("Not enough scored evaluations in this period to show a trend." if not period.is_all_time else "Not enough scored evaluations yet to show a trend — check back after the next one.")

    st.divider()

    # ---------- rubric category breakdown ----------
    st.subheader(
        "Category breakdown",
        help=(
            "For each rubric category, the average points scored across the non-test evaluations in the "
            f"period selected above ({period.label}), shown as a share of that category's maximum. "
            "Green is 85% or more of the maximum, amber is 60 to 84%, and red is below 60%."
        ),
    )
    st.caption("Average score in each rubric category, as a share of that category's max points.")

    cat_rows = []
    for r in RUBRIC:
        vals = [
            (e.get("scores") or {}).get(r["key"])
            for e in real_entries
            if (e.get("scores") or {}).get(r["key"]) is not None
        ]
        if vals:
            avg = sum(vals) / len(vals)
            pct = round(avg / r["max"] * 100, 1)
        else:
            avg = pct = None
        cat_rows.append({"Category": r["name"], "Avg": avg, "Max": r["max"], "Pct": pct})

    scored_cats = [row for row in cat_rows if row["Pct"] is not None]
    if scored_cats:
        def _status_color(pct: float) -> str:
            if pct >= 85:
                return _ACCENT
            if pct >= 60:
                return _COACH
            return _FAIL

        chart_df = pd.DataFrame(
            [{"Category": row["Category"], "Pct": row["Pct"], "Color": _status_color(row["Pct"])} for row in scored_cats]
        )
        bars = (
            alt.Chart(chart_df)
            .mark_bar(size=26, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
            .encode(
                x=alt.X("Pct:Q", title="% of category max", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("Category:N", sort=None, title=None),
                color=alt.Color("Color:N", scale=None, legend=None),
                tooltip=[alt.Tooltip("Category:N", title="Category"), alt.Tooltip("Pct:Q", title="% of max")],
            )
        )
        labels = bars.mark_text(align="left", dx=4, color=_MUTED).encode(text=alt.Text("Pct:Q", format=".0f"))
        st.altair_chart((bars + labels).properties(height=36 * len(scored_cats) + 40), use_container_width=True)

        table_rows = [
            {
                "Category": row["Category"],
                "Avg score": f'{row["Avg"]:.1f} / {row["Max"]}' if row["Avg"] is not None else "—",
                "% of max": f'{row["Pct"]}%' if row["Pct"] is not None else "—",
            }
            for row in cat_rows
        ]
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No scored evaluations in this period." if not period.is_all_time else "No scored evaluations yet.")

    st.divider()

    # ---------- full list with remarks ----------
    st.subheader(
        "All evaluations",
        help=(
            f"Every evaluation dated in the period selected above ({period.label}), most recent first, "
            "including any test audits (marked 🧪 TEST, never counted in the numbers). Open one to see the "
            "score for each category, the reviewer's remarks, and to ask a question or dispute the score."
        ),
    )
    st.caption("Most recent first. Expand one to see the full scoring breakdown, reviewer remarks, and comments.")

    sorted_entries = sorted(entries, key=lambda e: (e.get("qa_date") or "", e.get("updated_at") or ""), reverse=True)
    if not sorted_entries:
        st.caption("No evaluations in this period.")

    for e in sorted_entries:
        label = (
            f"{e.get('qa_date') or '—'} · {e.get('result') or '—'} · {e.get('total_score', '—')}/100"
            + (" · 🧪 TEST" if e.get("is_test") else "")
        )
        so = signoff_lookup.get(e.get("id")) if signoff_lookup is not None else None
        so_state = signoff.state(e, so) if signoff_lookup is not None else signoff.NOT_REQUIRED
        label += signoff.label_suffix(so_state)
        with st.expander(label):
            if agent_layout and so_state in (signoff.PENDING, signoff.RESIGN):
                # Its details, sign-off form and dispute form are in the section at the top of the
                # page; repeating them here would duplicate widget keys.
                signoff.status_caption(e, so, as_agent=not preview_sign_off)
                continue
            _render_entry_details(e)
            if signoff_lookup is not None:
                signoff.status_caption(e, so, as_agent=can_sign_off)

            if not e.get("is_test") and show_dispute_form:
                st.divider()
                disputes.render_agent_form(e, agent, submitted_by=submitted_by)


def _render_pending_signoffs(
    entries: list[dict], signoffs: list[dict], agent: dict, *, preview: bool = False
) -> None:
    """The "Needs your sign-off" section at the top of My Dashboard: every
    evaluation still waiting on this agent, regardless of the period picked
    below, each with its full details, the sign-off form and the dispute form."""
    waiting = signoff.pending(entries, signoffs)
    if not waiting:
        return
    lookup = signoff.by_entry(signoffs)
    n = len(waiting)
    st.subheader(f"🔔 Needs your sign-off ({n})")
    st.caption(
        f"{'This evaluation was' if n == 1 else f'These {n} evaluations were'} logged by a reviewer and "
        "waiting for you. Open it, read it, then sign off. Signing off means you have read it. It does not "
        "mean you agree."
    )
    for i, e in enumerate(waiting[: signoff.MAX_SHOWN]):
        so = lookup.get(e.get("id"))
        resign = signoff.state(e, so) == signoff.RESIGN
        label = (
            f"🔔 {e.get('qa_date') or '—'} · {e.get('result') or '—'} · {e.get('total_score', '—')}/100"
            f" · reviewed by {e.get('qa_reviewer') or '—'}" + (" · edited, please review again" if resign else "")
        )
        with st.expander(label, expanded=(i == 0)):
            if resign:
                signoff.status_caption(e, so, as_agent=not preview)
            _render_entry_details(e)
            st.divider()
            signoff.render_form(e, agent, preview=preview)
            st.divider()
            if preview:
                st.caption("The Question or dispute form appears here for the agent. It is not shown in this preview.")
            else:
                disputes.render_agent_form(e, agent)
    if n > signoff.MAX_SHOWN:
        st.caption(f"{n - signoff.MAX_SHOWN} more will appear here once you sign off on these.")
    st.divider()


def _render_entry_details(e: dict) -> None:
    """Score, ticket, category breakdown, critical errors and comments for one
    evaluation. Shared by the All evaluations list and the sign-off section."""
    ticket_id = e.get("ticket_id") or ""
    ticket_url = e.get("ticket_link") or (conversation_url(ticket_id) if ticket_id else "")
    h1, h2, h3 = st.columns([2, 2, 3])
    h1.markdown(result_badge_md(e.get("result", "")), unsafe_allow_html=True)
    h2.markdown(f"**{e.get('total_score', '—')} / 100**")
    h3.caption(f"Reviewed by {e.get('qa_reviewer') or '—'} on {e.get('qa_date') or '—'}")

    if ticket_url:
        st.markdown(f"**Ticket:** [{ticket_id}]({ticket_url})")
    st.markdown(
        f"**Renter/Host:** {e.get('renter_host') or '—'} &nbsp;·&nbsp; "
        f"**Concern type:** {', '.join(e.get('concern_types') or []) or '—'}"
    )

    scores = e.get("scores") or {}
    remarks = e.get("remarks") or {}
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

    crit = e.get("critical_errors") or {}
    flagged = [c["label"] for c in CRITICAL_ERRORS if crit.get(c["key"])]
    for lbl in flagged:
        st.error(f"🚫 {lbl}")

    if e.get("overall_comments"):
        st.markdown("**Overall comments**")
        st.write(e["overall_comments"])

    if e.get("is_escalated"):
        st.caption("🚩 Escalated")
