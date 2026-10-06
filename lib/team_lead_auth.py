"""Team lead sign-in gate for the Team Lead Dashboard page.

A third, separate auth layer from lib/auth.py (the 3 reviewers) and
lib/agent_auth.py (an individual agent's My Dashboard). A team lead signs in
with their name and a password a reviewer set for them (QA Log → Manage team
leads), scoped only to viewing the rollup and drill-down of the agents
assigned to them — there's no write access here at all, same as an agent on
My Dashboard. Password hashing reuses lib.agent_auth's generic bcrypt
helpers rather than duplicating them, since they aren't agent-specific.

Passwords are stored as a bcrypt hash in team_leads.password_hash — like
agent passwords, never in Streamlit secrets, so a reviewer can set/reset one
without a redeploy.
"""

import streamlit as st

from lib import db
from lib.agent_auth import hash_password, verify_password

SESSION_KEY = "team_lead_signed_in"  # {"id": ..., "name": ...}


def current_team_lead() -> dict | None:
    return st.session_state.get(SESSION_KEY)


def is_signed_in() -> bool:
    return bool(current_team_lead())


def render_sign_in() -> None:
    """Renders the team lead sign-in form. Call at the top of the Team Lead
    Dashboard and st.stop() unless is_signed_in() afterward."""
    leads = sorted(db.list_team_leads(), key=lambda t: (t.get("name") or "").lower())
    names = [t["name"] for t in leads if t.get("name")]

    st.markdown("**Sign in to Team Lead Dashboard**")
    st.caption("Use your name and the password a reviewer set for you.")
    name = st.selectbox("Your name", [""] + names, key="tl_auth_name_select")
    if not name:
        return

    lead = next((t for t in leads if t["name"] == name), None)
    pw = st.text_input("Password", type="password", key="tl_auth_pw_input")
    if st.button("Sign in", use_container_width=True, key="tl_auth_sign_in"):
        if lead and not lead.get("password_hash"):
            st.error(
                "No password has been set for you yet — ask a reviewer to set one "
                "on the QA Log page (Manage team leads)."
            )
        elif lead and verify_password(pw, lead.get("password_hash")):
            st.session_state[SESSION_KEY] = {"id": lead["id"], "name": lead["name"]}
            db.record_login("team_lead", lead["id"], lead["name"])
            st.rerun()
        else:
            st.error("Wrong password.")


def render_sign_out(container=None) -> None:
    container = container or st
    lead = current_team_lead()
    if not lead:
        return
    container.success(f"Signed in as {lead['name']}")
    if container.button("Sign out", key="tl_auth_sign_out"):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()


def render_change_password() -> None:
    """Lets a signed-in team lead set their own new password. Requires the
    current one, so losing it still requires a reviewer reset."""
    lead = current_team_lead()
    if not lead:
        return
    with st.expander("Change password"):
        current_pw = st.text_input("Current password", type="password", key="tl_change_current_pw")
        new_pw = st.text_input("New password", type="password", key="tl_change_new_pw")
        confirm_pw = st.text_input("Confirm new password", type="password", key="tl_change_confirm_pw")
        if st.button("Update password", key="tl_change_submit"):
            fresh = next((t for t in db.list_team_leads() if t["id"] == lead["id"]), None)
            if not fresh or not verify_password(current_pw, fresh.get("password_hash")):
                st.error("Current password is incorrect.")
            elif not new_pw:
                st.error("Enter a new password.")
            elif new_pw != confirm_pw:
                st.error("New password and confirmation don't match.")
            else:
                err = db.set_team_lead_password(lead["id"], hash_password(new_pw))
                if err:
                    st.error(f"Could not update password: {err}")
                else:
                    st.success("Password updated.")
