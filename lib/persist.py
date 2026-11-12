"""Stay signed in across a reload or a dropped connection.

Streamlit keeps sign-ins in session state, which is lost whenever the browser
reconnects (a page reload, the app restarting, a laptop waking from sleep).
For reviewers and phone evaluators, a successful sign-in also stores a random
token in a cookie in that browser (and a SHA-256 hash of it in app_sessions).
On a new session, restore() reads the cookie and signs the person back in.
Tokens expire after TTL_HOURS; signing out deletes the token and the cookie.

The cookie is written by a tiny invisible component (flush_cookie(), called
from app.py on every run), because Streamlit can read cookies
(st.context.cookies) but has no API to set them.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import streamlit as st

from lib import db

COOKIE = "zevo_qa_session"
TTL_HOURS = 12

# Session-state keys owned by lib/auth.py and lib/evaluator_auth.py (repeated
# here as strings so those modules can import this one without a cycle).
REVIEWER_KEY = "reviewer_name"
EVALUATOR_KEY = "evaluator_signed_in"

_PENDING = "_persist_cookie_action"  # ("set", token) or ("clear", None)
_CHECKED = "_persist_checked"
_TOKEN = "_persist_token"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def remember(kind: str, ident: str, name: str) -> None:
    """Call right after a successful sign-in ("reviewer" or "evaluator")."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=TTL_HOURS)).isoformat()
    if db.create_app_session(_hash(token), kind, ident, name, expires):
        st.session_state[_TOKEN] = token
        st.session_state[_PENDING] = ("set", token)
    st.session_state[_CHECKED] = True


def forget() -> None:
    """Call on sign-out: the token stops working and the cookie is removed."""
    token = st.session_state.pop(_TOKEN, None) or _cookie_token()
    if token:
        db.delete_app_session(_hash(token))
    st.session_state[_PENDING] = ("clear", None)
    st.session_state[_CHECKED] = True


def _cookie_token() -> str | None:
    try:
        value = st.context.cookies.get(COOKIE)
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def restore() -> None:
    """Once per session: sign the person back in from their cookie, if it
    holds a valid, unexpired token. Call at the top of app.py."""
    ss = st.session_state
    if ss.get(_CHECKED):
        return
    ss[_CHECKED] = True
    if ss.get(REVIEWER_KEY) or ss.get(EVALUATOR_KEY):
        return
    token = _cookie_token()
    if not token:
        return
    row = db.get_app_session(_hash(token))
    if not row:
        return
    if row.get("kind") == "reviewer":
        ss[REVIEWER_KEY] = row["name"]
    elif row.get("kind") == "evaluator":
        # Only if Weng hasn't removed this evaluator since.
        if not any(str(e.get("id")) == str(row.get("ident")) for e in db.list_evaluators()):
            return
        ss[EVALUATOR_KEY] = {"id": row["ident"], "name": row["name"]}
    else:
        return
    ss[_TOKEN] = token


def flush_cookie() -> None:
    """Writes or clears the cookie after a sign-in or sign-out in this session.
    Call from app.py on every run, before the page runs. The same invisible
    element is drawn on every run (not just once), because a rerun straight
    after signing in could otherwise remove it before the browser ran it; an
    unchanged element stays mounted, so its script runs only once."""
    action = st.session_state.get(_PENDING)
    if not action:
        return
    kind, token = action
    if kind == "set":
        value = json.dumps(token)
        js = (
            f"var c = '{COOKIE}=' + {value} + '; path=/; max-age={TTL_HOURS * 3600}; SameSite=Lax'"
            " + (location.protocol === 'https:' ? '; Secure' : '');"
        )
    else:
        js = f"var c = '{COOKIE}=; path=/; max-age=0; SameSite=Lax';"
    js += " try { window.parent.document.cookie = c; } catch (e) { document.cookie = c; }"
    try:
        import streamlit.components.v1 as components

        components.html(f"<script>{js}</script>", height=0)
    except Exception:
        pass
