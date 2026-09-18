-- Adds the disputes table backing My Dashboard's in-app "Question or dispute
-- about this audit?" form, replacing the old external QA Audit Question &
-- Dispute Form (Google Form) for agent-initiated submissions.
--
-- Each row is tied to one qa_entries audit via entry_id, so the agent never
-- re-types who they are, which ticket it was, or what the score was — the
-- app already knows. request_type distinguishes a plain question (answered
-- with just a written response) from a dispute (which may separately lead a
-- reviewer to use "Edit score" on that audit, logged in qa_entries.edit_log
-- as it already is today).
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
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

create index if not exists idx_disputes_entry on disputes (entry_id);
create index if not exists idx_disputes_agent on disputes (agent_id);
create index if not exists idx_disputes_status on disputes (status);
