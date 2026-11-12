"""Shared display of the phone scoring guide (fixed levels with descriptions,
plus each category's Critical Note), used by the audit form, Calibration and
QA Log so the wording is identical everywhere. The text lives in
lib/constants.PHONE_RUBRIC.
"""

from __future__ import annotations

import streamlit as st

from lib.constants import PHONE_RUBRIC, phone_level_label


def level_picker(r: dict, key: str, current=None, disabled: bool = False):
    """One phone category: its levels as a choice, highest first, each with its
    description, then the Critical Note. Nothing is preselected for a new score
    (or for an old score that isn't one of the levels), so every category has
    to be picked on purpose. Returns the chosen points, or None."""
    options = sorted(r["options"], reverse=True)
    levels = r.get("levels") or {}
    index = options.index(current) if current in options else None
    value = st.radio(
        r["name"],
        options,
        index=index,
        key=key,
        format_func=lambda v: phone_level_label(r, v),
        captions=[levels.get(v, ("", ""))[1] for v in options],
        disabled=disabled,
        label_visibility="collapsed",
    )
    if r.get("critical_note"):
        st.caption(f"**Critical note:** {r['critical_note']}")
    return value


def missing_levels(scores: dict) -> list[str]:
    """Names of phone categories with no level picked yet."""
    return [r["name"] for r in PHONE_RUBRIC if scores.get(r["key"]) is None]


def render_guide(expanded: bool = False, nested: bool = False) -> None:
    """The full phone scoring guide. One expander per category, or plain
    sections when `nested` (Streamlit doesn't allow an expander inside
    another, e.g. inside QA Log's "Phone scoring rubric" expander)."""
    st.caption(
        "Phone audits are scored from the call recording, not a transcript, and the call's Intercom/ZOMP "
        "notes are checked for Documentation. Pick one level per category."
    )
    for r in PHONE_RUBRIC:
        title = f"{r['name']} ({r['max']} points)"
        if nested:
            st.markdown(f"#### {title}")
            _category_body(r)
        else:
            with st.expander(title, expanded=expanded):
                _category_body(r)


def _category_body(r: dict) -> None:
    for v in sorted(r["options"], reverse=True):
        label, desc = (r.get("levels") or {}).get(v, ("", ""))
        st.markdown(f"**{v} - {label}**  \n{desc}")
    if r.get("critical_note"):
        st.markdown(f"**Critical note**  \n{r['critical_note']}")
