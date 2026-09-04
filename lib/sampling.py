"""AI topic-diversity sampling for the Weekly QA batch.

Replaces the Claude artifact's `sample` capability with a direct call to the
Anthropic API, billed to Weng's own API key (separate from her Claude
usage). Falls back to plain random selection if no key is configured, or if
the call fails for any reason — the batch should never get stuck just
because sampling is unavailable.
"""

from __future__ import annotations

import json
import random
import re

import streamlit as st

MODEL = "claude-3-5-haiku-20241022"


def _client():
    try:
        key = st.secrets["anthropic"]["api_key"]
    except Exception:
        return None
    if not key:
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def _build_prompt(candidates: list[dict], needed_now: int, existing_topics: list[str], agent_name: str) -> str:
    listing = [{"id": c["id"], "excerpt": re.sub(r"\s+", " ", c.get("text") or "")[:320]} for c in candidates]
    topics = ", ".join(existing_topics) if existing_topics else "(none yet)"
    return (
        f'You are helping a support-quality reviewer choose Intercom conversations handled by the agent "{agent_name}" '
        "to review this week.\n"
        "Each ticket you choose must be about a clearly different customer concern from the others you choose AND "
        f"from these concerns already covered this week: {topics}.\n\n"
        f"Choose exactly {needed_now} ticket(s) from the candidates below (each candidate is {{id, excerpt}}, where "
        "excerpt is the start of the conversation). Reply with ONLY a JSON array of "
        f'{needed_now} object(s), each shaped {{"id": string, "topic": string, "reason": string}} where topic is '
        '2-4 words describing the concern (e.g. "rental extension", "vehicle access issue", "payment dispute") and '
        "reason is one short sentence on why you picked it.\n\n"
        f"Candidates:\n{json.dumps(listing)}"
    )


def pick_diverse(candidates: list[dict], needed_now: int, existing_topics: list[str], agent_name: str) -> list[dict]:
    """Returns up to needed_now picks: [{id, topic, reason}]. Never raises —
    falls back to random selection on any failure."""
    sample_pool = candidates[: min(len(candidates), 40)]
    random.shuffle(sample_pool)

    client = _client()
    if client:
        try:
            prompt = _build_prompt(sample_pool, needed_now, existing_topics, agent_name)
            resp = client.messages.create(
                model=MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
            match = re.search(r"\[.*\]", text, re.DOTALL)
            picked = json.loads(match.group(0)) if match else []
            by_id = {c["id"]: c for c in sample_pool}
            final = []
            for p in picked:
                c = by_id.get(str(p.get("id")))
                if c and len(final) < needed_now and c["id"] not in {f["id"] for f in final}:
                    final.append(
                        {
                            "id": c["id"],
                            "topic": (p.get("topic") or "")[:60],
                            "reason": (p.get("reason") or "")[:200],
                            "url": c.get("url", ""),
                            "subject": c.get("title", ""),
                        }
                    )
            i = 0
            while len(final) < needed_now and i < len(sample_pool):
                c = sample_pool[i]
                i += 1
                if c["id"] not in {f["id"] for f in final}:
                    final.append({"id": c["id"], "topic": "", "reason": "", "url": c.get("url", ""), "subject": c.get("title", "")})
            return final[:needed_now]
        except Exception:
            pass  # fall through to plain random below

    return [
        {"id": c["id"], "topic": "", "reason": "", "url": c.get("url", ""), "subject": c.get("title", "")}
        for c in sample_pool[:needed_now]
    ]
