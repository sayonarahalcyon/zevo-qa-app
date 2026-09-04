-- Ticket QA Sampler — Supabase (Postgres) schema
-- Run this once in the Supabase SQL editor for a new project.
-- Replaces the Claude artifact's `db` capability (a small document store);
-- table names match the original collections 1:1.

create table if not exists agents (
    id          text primary key,          -- Intercom admin id
    name        text not null,
    email       text,
    updated_at  timestamptz not null default now()
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
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);

create index if not exists idx_qa_entries_agent on qa_entries (agent_name);
create index if not exists idx_qa_entries_qa_date on qa_entries (qa_date);
create index if not exists idx_weekly_picks_agent on weekly_picks (agent_id);

-- Row Level Security: the app connects with the Supabase anon/service key
-- set in Streamlit secrets, and enforces who can *write* itself (the
-- reviewer password gate in lib/auth.py). If you'd rather enforce reads/
-- writes at the database level too, enable RLS and add policies here —
-- left permissive by default so the app works out of the box.
