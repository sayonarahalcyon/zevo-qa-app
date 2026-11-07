-- Calibration mode (added 2026-11-07).
--
-- A calibration session is one phone ticket that several chosen evaluators
-- (reviewers and/or phone evaluators) each score independently, to check that
-- they score consistently. Calibration scores are kept here only: they never
-- go into qa_entries, never count toward any dashboard, rollup, pass rate or
-- agent view, and are not copied to the backup sheet.
--
-- Safe to run more than once.

create table if not exists calibration_sessions (
    id             text primary key,          -- uuid4
    ticket_id      text not null,             -- Intercom conversation id
    ticket_url     text,
    agent_name     text,                      -- assignee when the session was started
    participants   jsonb not null default '[]'::jsonb,  -- evaluator names who score it
    created_by     text,
    created_at     timestamptz not null default now(),
    closed_at      timestamptz                -- set when Weng closes the session
);

create table if not exists calibration_scores (
    session_id       text not null references calibration_sessions (id) on delete cascade,
    evaluator        text not null,
    scores           jsonb not null default '{}'::jsonb,
    remarks          jsonb not null default '{}'::jsonb,
    critical_errors  jsonb not null default '{}'::jsonb,
    overall_comments text,
    total_score      integer,
    result           text,
    submitted_at     timestamptz not null default now(),
    primary key (session_id, evaluator)
);

create index if not exists idx_calibration_sessions_ticket on calibration_sessions (ticket_id);
