"""Call recording and transcript player, shown on any open ticket that has a
phone call on it.

The app fetches both from Intercom's Calls API with its own access token
(lib/intercom_client.py), so a person with no Intercom login, like a
third-party phone evaluator, can still listen to the call and read the
transcript inside the QA App. Nothing is downloaded into the app's database
or the backup sheet.
"""

from __future__ import annotations

import streamlit as st

from lib.intercom_client import (
    IntercomError,
    get_call,
    get_call_ids,
    get_call_recording_bytes,
    get_call_recording_url,
    get_call_transcript,
)


def _fmt_duration(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _call_label(call: dict, n: int, total: int) -> str:
    bits = ["📞 Call recording" + (f" {n} of {total}" if total > 1 else "")]
    direction = (call.get("direction") or "").capitalize()
    if direction:
        bits.append(direction)
    dur = _fmt_duration(call.get("duration"))
    if dur:
        bits.append(dur)
    return " · ".join(bits)


def _render_transcript(transcript) -> None:
    if transcript is None or transcript == "" or transcript == []:
        st.caption("No transcript for this call.")
        return
    if isinstance(transcript, str):
        st.text(transcript)
        return
    if isinstance(transcript, list):
        for turn in transcript:
            if isinstance(turn, dict):
                who = turn.get("speaker") or turn.get("author") or turn.get("role") or turn.get("name") or ""
                if isinstance(who, dict):
                    who = who.get("name") or who.get("type") or ""
                text = turn.get("text") or turn.get("content") or turn.get("body") or ""
                st.markdown(f"**{who}**  \n{text}" if who else text)
            else:
                st.markdown(str(turn))
        return
    st.json(transcript)


def render_call_media(conversation_id: str) -> list[str]:
    """Renders a player and transcript for every call on the conversation.
    Returns the call ids found (empty list if none or if Intercom couldn't be
    reached), so callers can tell whether this was a phone ticket."""
    try:
        call_ids = get_call_ids(str(conversation_id))
    except IntercomError as e:
        st.warning(f"Couldn't check this ticket for a call recording: {e}")
        return []
    if not call_ids:
        return []

    for n, call_id in enumerate(call_ids, start=1):
        try:
            call = get_call(call_id)
        except IntercomError:
            call = {}
        with st.container(border=True):
            st.markdown(f"**{_call_label(call, n, len(call_ids))}**")
            try:
                url = get_call_recording_url(call_id)
            except IntercomError as e:
                url = None
                st.warning(f"Couldn't load the recording: {e}")
            else:
                if url:
                    fallback_key = f"call_bytes_{call_id}"
                    if st.session_state.get(fallback_key):
                        try:
                            got = get_call_recording_bytes(call_id)
                            if got:
                                st.audio(got[0], format=got[1])
                        except IntercomError as e:
                            st.warning(str(e))
                    else:
                        st.audio(url)
                        if st.button("Recording won't play? Load it through the app", key=f"btn_{fallback_key}"):
                            st.session_state[fallback_key] = True
                            st.rerun()
                else:
                    st.caption("No recording for this call.")

            with st.expander("Call transcript"):
                try:
                    _render_transcript(get_call_transcript(call_id))
                except IntercomError as e:
                    st.warning(f"Couldn't load the transcript: {e}")
    return call_ids
