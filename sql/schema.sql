-- Ticket QA Sampler — Supabase (Postgres) schema
-- Run this once in the Supabase SQL editor for a new project.
-- Replaces the Claude artifact's `db` capability (a small document store);
-- table names match the original collections 1:1.

create table if not exists agents (
    id             text primary key,          -- Intercom admin id
    name           text not null,
    email          text,
    password_hash  text,                      -- bcrypt hash for My Dashboard sign-in;
                                                -- NULL until a reviewer sets one (see
                                                -- QA Log → Manage agents)
    updated_at     timestamptz not null default now()
);

create table if not exists reviewed (
    id           text primary key,         -- Intercom conversation id
    subject      text,
    state        text,
    url          text,
    reviewed_at  timestamptz not null default now()
);

create table if not exists weekly_picks (
    id          text primary key,          -- "<agent_id>__<week_start ISO date>"
    agent_id    text not null,
    agent_name  text not null,
    week_start  date not null,
    tickets     jsonb not null default '[]'::jsonb,  -- [{id, topic, reason, subject, url, reviewed}]
    updated_at  timestamptz not null default now()
);

create table if not exists qa_entries (
    id                     text primary key,   -- Intercom conversation id
    agent_id               text,
    agent_name             text not null,
    ticket_id              text not null,
    ticket_link            text,
    zomp_link              text,
    renter_host            text,
    concern_types          jsonb not null default '[]'::jsonb,
    scores                 jsonb not null default '{}'::jsonb,
    remarks                jsonb not null default '{}'::jsonb,
    overall_comments       text,
    total_score            int not null default 0,
    result                 text not null,          -- PASS | COACHING | FAIL | AUTO FAIL
    critical_errors        jsonb not null default '{}'::jsonb,
    critical_error_status  text,
    qa_reviewer            text not null,
    qa_date                date not null,
    is_test                boolean not null default false,  -- flagged via the "Mark as test audit" checkbox;
                                                              -- excluded from the QA Log's dashboard totals and
                                                              -- per-agent rollup, but still visible in the audit log
    is_escalated           boolean not null default false,  -- flagged via "Mark as escalated" or auto-set when the
                                                              -- ticket came from "Manually log a ticket" (as opposed
                                                              -- to the random Weekly QA batch / Quick Sample pulls)
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);

-- One-time, read-only import from the retired "2026 - ZEVO QA Tracker v2"
-- Google Sheet (see the Historical Log page). Nothing in the app writes to
-- this table after the import — it's a reference archive, deliberately
-- separate from qa_entries so old sheet rows never mix into the live QA
-- Log's dashboard, pass rate, or per-agent rollup.
create table if not exists historical_qa_entries (
    id                     text primary key,   -- "sheet_<tab>_<sheet row>"
    source_tab             text not null,      -- which tab of the old sheet this came from
    submitted_at           timestamptz,        -- form-submission timestamp, when parseable
    qa_date                date,               -- date of the audit, when parseable
    agent_name             text not null,
    ticket_link            text,
    zomp_link              text,
    renter_host            text,
    concern_types          jsonb not null default '[]'::jsonb,
    scores                 jsonb not null default '{}'::jsonb,   -- {acknowledge, communication, policy, resolution, documentation}
    remarks                jsonb not null default '{}'::jsonb,   -- same keys, per-category remarks
    overall_comments       text,
    total_score            int,
    result                 text,               -- PASS | COACHING | FAIL | AUTO FAIL
    qa_reviewer            text,
    critical_errors        jsonb not null default '{}'::jsonb,   -- {refund, access, policy, safety}
    critical_error_status  text,
    imported_at            timestamptz not null default now()
);

-- Agent-submitted questions/disputes from My Dashboard's inline "Question or
-- dispute about this audit?" form — replaces the old external QA Audit
-- Question & Dispute Form (Google Form). Always tied to one qa_entries row
-- via entry_id, since the app already knows who the agent is and which
-- audit they're looking at.
create table if not exists disputes (
    id                   text primary key,
    entry_id             text not null references qa_entries(id) on delete cascade,
    agent_id             text,
    agent_name           text not null,
    request_type         text not null check (request_type in ('question', 'dispute')),
    categories           jsonb not null default '[]'::jsonb,
    message              text not null,
    supporting_evidence  text,
    status               text not null default 'open' check (status in ('open', 'resolved')),
    reviewer_response    text,
    resolved_by          text,
    resolved_at          timestamptz,
    is_test              boolean not null default false,  -- test rows (created directly, not
                                                              -- via the agent form) excluded from
                                                              -- the Questions & Disputes open/resolved counts
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

create index if not exists idx_qa_entries_agent on qa_entries (agent_name);
create index if not exists idx_qa_entries_qa_date on qa_entries (qa_date);
create index if not exists idx_weekly_picks_agent on weekly_picks (agent_id);
create index if not exists idx_historical_qa_entries_agent on historical_qa_entries (agent_name);
create index if not exists idx_historical_qa_entries_date on historical_qa_entries (qa_date);
create index if not exists idx_disputes_entry on disputes (entry_id);
create index if not exists idx_disputes_agent on disputes (agent_id);
create index if not exists idx_disputes_status on disputes (status);

-- Row Level Security: the app connects with the Supabase anon/service key
-- set in Streamlit secrets, and enforces who can *write* itself (the
-- reviewer password gate in lib/auth.py). If you'd rather enforce reads/
-- writes at the database level too, enable RLS and add policies here —
-- left permissive by default so the app works out of the box.
