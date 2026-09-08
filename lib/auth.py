"""Reviewer sign-in gate.

Anyone with the app link can browse Quick Sample / Weekly QA Batch / QA Log
read-only. Submitting or editing a QA audit, and marking a ticket reviewed,
requires being signed in as one of the three reviewers — enforced here with
a real password check against Streamlit secrets, unlike the original Claude
artifact (which had no identity capability and relied on claude.ai's own
page-sharing permissions instead).

Required secret shape:
    [reviewer_passwords]
    "Erwin Bagnol" = "..."
    "Weng Yee" = "..."
    "Kristine Lariosa" = "..."
"""

import streamlit as st

from lib.constants import REVIEWER_NAMES

SESSION_KEY = "reviewer_name"


def current_reviewer() -> str | None:
    return st.session_state.get(SESSION_KEY)


def is_signed_in() -> bool:
    return bool(current_reviewer())


def _check_password(name: str, password: str) -> bool:
    try:
        expected = st.secrets["reviewer_passwords"][name]
    except Exception:
        return False
    return bool(password) and password == expected


def render_auth(container) -> None:
    """Renders the sign-in / sign-out control into any container (st, st.sidebar,
    a st.container(), or a column) — lets Home place it inline on the page
    instead of in the sidebar, while every other page still passes st.sidebar.
    Call once per page.
    """
    container.markdown("**Reviewing as**")
    signed_in = current_reviewer()

    if signed_in:
        container.success(f"Signed in as {signed_in}")
        if container.button("Sign out", use_container_width=True, key="auth_sign_out"):
            st.session_state.pop(SESSION_KEY, None)
            st.rerun()
        return

    name = container.selectbox("Name", [""] + REVIEWER_NAMES, key="auth_name_select")
    if name:
        pw = container.text_input("Password", type="password", key="auth_pw_input")
        if container.button("Sign in", use_container_width=True, key="auth_sign_in"):
            if _check_password(name, pw):
                st.session_state[SESSION_KEY] = name
                # Reviewers sign in to pull and score tickets, and that tool
                # lives on Weekly QA Batch (not wherever they happened to sign
                # in from) — send them straight there instead of just rerunning.
                st.switch_page("pages/1_Weekly_QA_Batch.py")
            else:
                container.error("Wrong password.")
    container.caption(
        "Only Erwin, Weng, and Kristine have edit access — everyone else can view the app read-only."
    )


def render_sidebar_auth() -> None:
    """Renders the sign-in / sign-out control in the sidebar. Call once per page."""
    render_auth(st.sidebar)
