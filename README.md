# Ticket QA Sampler

ZEVO Support's Intercom ticket QA tool — samples closed Intercom conversations for review, scores them against the 5-category / 100-point rubric, and tracks results. Replaces the "2026 - ZEVO QA Tracker v2" Google Sheet, which is being sunset — log new QA audits here, not in the sheet.

Originally built as an in-conversation Claude artifact; this is the standalone Streamlit rebuild so it can run on its own from GitHub + Streamlit Community Cloud.

## Pages

- **Quick sample** (`app.py`) — pull a random closed conversation in a date range, optionally filtered by agent, and score it.
- **Weekly QA Batch** — pulls 3 topic-diverse tickets per agent per week (AI-assisted topic diversity via Anthropic, falls back to random if not configured).
- **QA Log** — dashboard (totals, pass/coaching/fail, avg score, pass rate), per-agent rollup with weekly quota tracking, a filterable audit log, and the scoring guide.

## Setup

1. **Supabase**: create a project, then run `sql/schema.sql` in its SQL editor. Copy the project URL and an API key (anon key is fine — the app enforces write access itself via the reviewer password gate, see below).
2. **Intercom**: create a Custom App / access token with read access to conversations and admins.
3. **Anthropic (optional)**: an API key for the Weekly QA Batch's topic-diversity sampling. Without one, batches fall back to plain random selection — everything else still works.
4. **Secrets**: copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local runs (gitignored), or paste the same keys into your Streamlit Community Cloud app's **Settings → Secrets**. You'll need:
   - `[supabase] url`, `key`
   - `[intercom] access_token`
   - `[anthropic] api_key` (optional)
   - `[reviewer_passwords]` — a password for each of Erwin Bagnol, Weng Yee, Kristine Lariosa. Only these three can submit/edit a QA audit or mark a ticket reviewed; anyone with the app link can browse read-only.
5. **Run locally**: `pip install -r requirements.txt && streamlit run app.py`
6. **Deploy**: push this repo to GitHub, then create a new app on [share.streamlit.io](https://share.streamlit.io) pointed at it (main file: `app.py`). Add the secrets there before first load.

## First-deploy sanity check

`lib/intercom_client.py` was written from Intercom's public API docs, not verified against a live workspace. Before trusting it day-to-day, run one Quick Sample pull and check:

- that **Exclude Fin AI-handled tickets** actually excludes anything — if the `ai_agent_participated` field isn't filterable via the Search API in this workspace, the app falls back to an unfiltered search and shows a warning rather than erroring out; verify the Fin badge on what you get.
- that `custom_attributes["AI Title"]` is the right key for this workspace's Fin-generated conversation title.

## Deliberate differences from the original sheet

- **Resolution Quality** now offers 0/10/20 (the sheet only allowed 0 or 20 — no middle tier).
- **Acknowledge Issue, Communication, Documentation** now include 0 as an option (the sheet's dropdown only allowed 5/10/15).
- Policy Accuracy/Process Compliance/Risk & Safety is unchanged (15/25/35).
- Result thresholds, the AUTO FAIL rule, and the 5-category/100-point structure match the sheet exactly.
- Per-agent and dashboard stats are computed live from real data, not the sheet's broken hardcoded `QA Stats` rows.
- Not rebuilt (considered non-essential/archival): the sheet's monthly archive tabs, its native pivot table, and the `FOR STELLA` change-request log. The `Questions` FAQ log and the QA Audit Dispute Form are kept as static reference content / an external link in the Scoring Guide.
- The agent roster is learned automatically from Intercom conversations as tickets are opened (Kristine/Weng/Erwin excluded as non-frontline), not the sheet's static `Lists` tab.
