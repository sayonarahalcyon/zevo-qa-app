# Ticket QA Sampler

ZEVO Support's Intercom ticket QA tool — samples closed Intercom conversations for review, scores them against the 5-category / 100-point rubric, and tracks results. Replaces the "2026 - ZEVO QA Tracker v2" Google Sheet, which is being sunset — log new QA audits here, not in the sheet.

Originally built as an in-conversation Claude artifact; this is the standalone Streamlit rebuild so it can run on its own from GitHub + Streamlit Community Cloud.

## Pages

- **Quick sample** (`app.py`) — pull a random closed conversation in a date range, optionally filtered by agent, and score it.
- **Weekly QA Batch** — pulls 3 topic-diverse tickets per agent per week (AI-assisted topic diversity via Anthropic, falls back to random if not configured).
- **QA Log** — dashboard (totals, pass/coaching/fail, avg score, pass rate), per-agent rollup with weekly quota tracking, a filterable audit log (filter by agent, result, channel, date, or free text), and the scoring guide.
- **Historical Log** — read-only archive of evaluations imported from the retired "2026 - ZEVO QA Tracker v2" Google Sheet. Kept separate from the QA Log's live dashboard/rollup so old sheet data never mixes into current metrics.
- **Questions & Disputes** — reviewer inbox for questions/disputes agents submit inline on My Dashboard. Linked from QA Log (with an open-count badge) and Home.
- **My Dashboard** — each agent's own read-only view of their evaluations: summary metrics, a score trend chart, a per-category rubric breakdown, and the full list of their audits, with an inline form to ask a question or dispute a score. Signs in with their name and a password a reviewer sets for them — see "Agent access" below.
- **Team Lead Dashboard** — each team lead's own view of the agents assigned to them: a team-wide rollup (same shape as QA Log's per-agent rollup, scoped to their team) plus a drill-down into any one of their agents' own My Dashboard view, read-only except for one thing: a team lead can submit a question or dispute on an agent's behalf, right from that drill-down, same form an agent uses on their own My Dashboard. Signs in the same way as My Dashboard — see "Team lead access" below.

## Setup

1. **Supabase**: create a project, then run `sql/schema.sql` in its SQL editor. Copy the project URL and an API key (anon key is fine — the app enforces write access itself via the reviewer password gate, see below).
2. **Intercom**: create a Custom App / access token with read access to conversations and admins.
3. **Anthropic (optional)**: an API key for the Weekly QA Batch's topic-diversity sampling. Without one, batches fall back to plain random selection — everything else still works.
4. **Secrets**: copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local runs (gitignored), or paste the same keys into your Streamlit Community Cloud app's **Settings → Secrets**. You'll need:
   - `[supabase] url`, `key`
   - `[intercom] access_token`
   - `[anthropic] api_key` (optional)
   - `[reviewer_passwords]` — a password for each of Erwin Bagnol, Weng Yee, Kristine Lariosa. Only these three can submit/edit a QA audit or mark a ticket reviewed; anyone with the app link can browse read-only.
5. **Agent access (My Dashboard)**: unlike the three reviewer passwords, agent passwords aren't a secret you set once — they're bcrypt hashes stored per-agent in `agents.password_hash`, since the agent roster is learned automatically and grows without a redeploy. A reviewer sets or resets an agent's password from **QA Log → Manage agents → Set / reset My Dashboard password**; an agent can change it themselves afterward from My Dashboard. Nobody has one until a reviewer sets it.
6. **Team lead access (Team Lead Dashboard)**: same pattern as agent passwords, in a separate `team_leads` table — a reviewer sets or resets a team lead's password from **QA Log → Manage team leads**, and the team lead can change it themselves afterward from their dashboard. Which agents a team lead sees is set separately, per agent, from **QA Log → Manage agents → Assign a team lead**; an agent with no team lead assigned just doesn't show up on anyone's rollup. `sql/schema.sql` seeds the 3 real team leads (Aga Luague, Elizabeth Alerta, Stella Albacite) for a new install, but that's just a starting point — a reviewer can add or remove a team lead at any time from the same **Manage team leads** panel; removing one unassigns (doesn't delete) any agents under them.
7. **Google Sheets backup (optional)**: every saved QA audit can also be mirrored, live, into a separate Google Sheet — distinct from the retired sheet imported into Historical Log. Requires a Google Cloud service account: Google Cloud Console → create/select a project → enable the **Google Sheets API** → IAM & Admin → Service Accounts → create one → Keys → Add key → JSON → share the target sheet with that service account's `client_email` as an Editor → add its key fields and the sheet's id under `[gcp_service_account]` / `qa_backup_sheet_id` in Secrets (see `.streamlit/secrets.toml.example`). Skip this section entirely and the app just skips the backup — Supabase stays the source of truth either way.
8. **Existing database?** Run any migration in `sql/migrations/` you haven't applied yet, in date order, in the Supabase SQL editor before deploying this version of the code — new installs don't need them, since `sql/schema.sql` already includes every column. Team Lead Dashboard needs `2026_10_03_add_team_leads.sql`; if you already ran that one before adding or removing a team lead was supported, also run the follow-up `2026_10_03b_team_leads_fk_set_null.sql`. The Channel tag on QA audits needs `2026_10_03c_add_channel.sql`. Letting a team lead submit a dispute on an agent's behalf needs `2026_10_03d_add_disputes_submitted_by.sql`.
9. **Run locally**: `pip install -r requirements.txt && streamlit run app.py`
10. **Deploy**: push this repo to GitHub, then create a new app on [share.streamlit.io](https://share.streamlit.io) pointed at it (main file: `app.py`). Add the secrets there before first load.

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
- Not rebuilt (considered non-essential/archival): the sheet's monthly archive tabs, its native pivot table, and the `FOR STELLA` change-request log. The `Questions` FAQ log is kept as static reference content in the Scoring Guide. The QA Audit Question & Dispute Form (Google Form) has been superseded by an in-app equivalent — see "Questions & disputes" below.
- **Questions & disputes**: agents submit questions/disputes directly on the audit, from My Dashboard, instead of a separate Google Form — see the `disputes` table in `sql/schema.sql` and `lib/disputes.py`. Reviewers respond from its own **Questions & Disputes** page (linked from QA Log, with an open-count badge, and from Home); an actual score change still goes through the existing "Edit score" → reason "Dispute" flow (`qa_entries.edit_log`), which the panel links straight into. `disputes.is_test` mirrors `qa_entries.is_test` — test rows still show in the panel (tagged 🧪 TEST) but are excluded from the open/resolved counts.
- The agent roster is learned automatically from Intercom conversations as tickets are opened (Kristine/Weng/Erwin excluded as non-frontline), not the sheet's static `Lists` tab.
- The sheet's monthly archive tabs *are* now rebuilt, as a one-time import into `historical_qa_entries` (see the Historical Log page) — 116 real evaluations across the main tab and the August archive tab, skipping test/placeholder rows and one tab that turned out to be a duplicate of another. It's read-only reference data; nothing in the app writes to it, and it's excluded from the QA Log's live dashboard and per-agent rollup so it can't skew current numbers.
- **Channel tag**: every QA audit now carries a "Channel" field — "Chat" (every audit logged so far) or "Phone" — set on the QA Audit form and filterable in the QA Log's Audit log, added ahead of Phone Support Ticket evaluations that aren't logged yet. Existing audits default to "Chat".
- **My Dashboard** and **Team Lead Dashboard** have no equivalent in the original sheet — agents and team leads previously had to ask a reviewer to pull up their own or their team's scores. Both are read-only and additive: neither changes how audits are scored or logged. Team Lead Dashboard's rollup and drill-down reuse the exact same numbers and charts as My Dashboard (`lib/agent_dashboard.py`), just scoped to one team lead's assigned agents, so a team lead and their agent are always looking at the same figures.
