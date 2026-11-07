-- Phone audit queue and phone-only evaluators (added 2026-11-07).
--
-- evaluators: people who audit phone tickets only (e.g. a third-party
--   evaluator with no Intercom access). They sign in on the Phone Queue page
--   with a password Weng sets in QA Log -> Manage phone evaluators. Same
--   resettable bcrypt pattern as agents and team leads.
-- phone_queue: phone tickets a reviewer loaded for evaluation. One row per
--   ticket. An evaluator or reviewer claims a ticket before auditing it, so
--   two people never audit the same call. Whether a ticket is audited is read
--   from qa_entries (same ticket id), not stored here.
--
-- Safe to run more than once.

create table if not exists evaluators (
    id             text primary key,          -- slug, e.g. "alrose-santos"
    name           text not null,
    password_hash  text,                      -- NULL until Weng sets one
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create table if not exists phone_queue (
    ticket_id      text primary key,          -- Intercom conversation id
    ticket_url     text,
    agent_name     text,                      -- assignee when loaded, for the list
    call_ids       jsonb not null default '[]'::jsonb,  -- Intercom call ids found on the ticket
    loaded_by      text,
    loaded_at      timestamptz not null default now(),
    notified_at    timestamptz,               -- set when "Notify channel" announced it
    claimed_by     text,
    claimed_at     timestamptz
);

create index if not exists idx_phone_queue_claimed_by on phone_queue (claimed_by);
create index if not exists idx_phone_queue_notified on phone_queue (notified_at);
