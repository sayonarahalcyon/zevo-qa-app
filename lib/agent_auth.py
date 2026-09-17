"""Agent sign-in gate for the My Dashboard page.

Distinct from lib/auth.py (the reviewer gate). An agent signs in with their
own name plus a password a reviewer set for them (QA Log → Manage agents →
"Set/reset agent password"), scoped only to viewing their own evaluations on
My Dashboard — there's no write access here at all. An agent with no
password set yet can't sign in until a reviewer sets one; once signed in,
they can change it themselves via render_change_password() below.

Passwords are stored as a bcrypt hash in agents.password_hash — never in
Streamlit secrets, since (unlike the three reviewers) the agent roster is
learned automatically and grows without a redeploy.
"""

import bcrypt
import streamlit as st

from lib import db

SESSION_KEY = "agent_signed_in"  # {"id": ..., "name": ...}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        # Covers a malformed/legacy hash rather than raising through the UI.
        return False


def current_agent() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def is_signed_in() -> bool:
    return bool(current_agent())


def render_sign_in() -> None:
    """Renders the agent sign-in form. Call at the top of My Dashboard and
    st.stop() unless is_signed_in() afterward."""
    agents = sorted(db.list_agents(), key=lambda a: (a.get("name") or "").lower())
    names = [a["name"] for a in agents if a.get("name")]

    st.markdown("**Sign in to My Dashboard**")
    st.caption("Use your name and the password your manager set for you.")
    name = st.selectbox("Your name", [""] + names, key="agent_auth_name_select")
    if not name:
        return

    agent = next((a for a in agents if a["name"] == name), None)
    pw = st.text_input("Password", type="password", key="agent_auth_pw_input")
    if st.button("Sign in", use_container_width=True, key="agent_auth_sign_in"):
        if agent and not agent.get("password_hash"):
            st.error(
                "No password has been set for you yet — ask a reviewer to set one "
                "on the QA Log page (Manage agents)."
            )
        elif agent and verify_password(pw, agent.get("password_hash")):
            st.session_state[SESSION_KEY] = {"id": agent["id"], "name": agent["name"]}
            st.rerun()
        else:
            st.error("Wrong password.")


def render_sign_out(container=None) -> None:
    container = container or st
    agent = current_agent()
    if not agent:
        return
    container.success(f"Signed in as {agent['name']}")
    if container.button("Sign out", key="agent_auth_sign_out"):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()


def render_change_password() -> None:
    """Lets a signed-in agent set their own new password. Requires the
    current one, so losing it still requires a reviewer reset."""
    agent = current_agent()
    if not agent:
        return
    with st.expander("Change password"):
        current_pw = st.text_input("Current password", type="password", key="agent_change_current_pw")
        new_pw = st.text_input("New password", type="password", key="agent_change_new_pw")
        confirm_pw = st.text_input("Confirm new password", type="password", key="agent_change_confirm_pw")
        if st.button("Update password", key="agent_change_submit"):
            fresh = next((a for a in db.list_agents() if a["id"] == agent["id"]), None)
            if not fresh or not verify_password(current_pw, fresh.get("password_hash")):
                st.error("Current password is incorrect.")
            elif not new_pw:
                st.error("Enter a new password.")
            elif new_pw != confirm_pw:
                st.error("New password and confirmation don't match.")
            else:
                err = db.set_agent_password(agent["id"], hash_password(new_pw))
                if err:
                    st.error(f"Could not update password: {err}")
                else:
                    st.success("Password updated.")
