"""Phone evaluator sign-in gate for the Phone Queue page.

A fourth auth layer, next to lib/auth.py (the 3 reviewers), lib/agent_auth.py
(an agent's My Dashboard) and lib/team_lead_auth.py (Team Lead Dashboard). A
phone evaluator (e.g. a third-party evaluator with no Intercom access) signs
in with their name and a password Weng set for them (QA Log -> Manage phone
evaluators). Once signed in they can claim and audit phone tickets from the
Phone Queue and nothing else: app.py shows them only that page, and the audit
form locks the channel to Phone for them.

Passwords are bcrypt hashes in evaluators.password_hash, never in Streamlit
secrets, so Weng can add or reset one without a redeploy.
"""

import streamlit as st

from lib import activity, db, persist
from lib.agent_auth import hash_password, verify_password

SESSION_KEY = "evaluator_signed_in"  # {"id": ..., "name": ...}


def current_evaluator() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def current_name() -> str | None:
    ev = current_evaluator()
    return ev["name"] if ev else None


def is_signed_in() -> bool:
    return bool(current_evaluator())


def render_sign_in() -> None:
    """Sign-in form for phone evaluators. Call on the Phone Queue page when
    nobody who can audit is signed in."""
    evaluators = sorted(db.list_evaluators(), key=lambda e: (e.get("name") or "").lower())
    names = [e["name"] for e in evaluators if e.get("name")]

    st.markdown("**Phone evaluator sign-in**")
    if not names:
        st.caption("No phone evaluators have been added yet.")
        return
    st.caption("Use your name and the password you were given.")
    name = st.selectbox("Your name", [""] + names, key="ev_auth_name_select")
    if not name:
        return
    ev = next((e for e in evaluators if e["name"] == name), None)
    pw = st.text_input("Password", type="password", key="ev_auth_pw_input")
    if st.button("Sign in", use_container_width=True, key="ev_auth_sign_in"):
        if ev and not ev.get("password_hash"):
            st.error("No password has been set for you yet. Ask Weng to set one.")
        elif ev and verify_password(pw, ev.get("password_hash")):
            st.session_state[SESSION_KEY] = {"id": ev["id"], "name": ev["name"]}
            db.record_login("evaluator", ev["id"], ev["name"])
            persist.remember("evaluator", ev["id"], ev["name"])
            activity.reset()
            st.rerun()
        else:
            st.error("Wrong password.")


def render_sign_out(container=None) -> None:
    container = container or st
    ev = current_evaluator()
    if not ev:
        return
    container.success(f"Signed in as {ev['name']}")
    if container.button("Sign out", key="ev_auth_sign_out"):
        activity.log("sign_out", "", "evaluator")
        activity.reset()
        persist.forget()
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()


def render_change_password() -> None:
    """Lets a signed-in evaluator change their own password (needs the current one)."""
    ev = current_evaluator()
    if not ev:
        return
    with st.expander("Change password"):
        current_pw = st.text_input("Current password", type="password", key="ev_change_current_pw")
        new_pw = st.text_input("New password", type="password", key="ev_change_new_pw")
        confirm_pw = st.text_input("Confirm new password", type="password", key="ev_change_confirm_pw")
        if st.button("Update password", key="ev_change_submit"):
            fresh = next((e for e in db.list_evaluators() if e["id"] == ev["id"]), None)
            if not fresh or not verify_password(current_pw, fresh.get("password_hash")):
                st.error("Current password is incorrect.")
            elif not new_pw:
                st.error("Enter a new password.")
            elif new_pw != confirm_pw:
                st.error("New password and confirmation don't match.")
            else:
                err = db.set_evaluator_password(ev["id"], hash_password(new_pw))
                if err:
                    st.error(f"Could not update password: {err}")
                else:
                    st.success("Password updated.")


__all__ = ["current_evaluator", "current_name", "is_signed_in", "render_sign_in", "render_sign_out",
           "render_change_password", "hash_password"]
