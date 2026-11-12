-- Autosaved audit drafts, and "stay signed in" sessions.
--
-- audit_drafts: what a reviewer or phone evaluator has filled in on a QA audit
-- form but not submitted yet, one row per ticket and person. Deleted when the
-- audit is submitted. Lets a dropped session (app restart, laptop sleep,
-- reload) come back to the half-finished form.
--
-- app_sessions: one row per browser that signed in as a reviewer or phone
-- evaluator. Only a SHA-256 hash of the browser's token is stored; the token
-- is in that browser's cookie. Rows expire after 12 hours, and signing out
-- deletes the row. New installs don't need this: sql/schema.sql has both.

create table if not exists audit_drafts (
    ticket_id   text not null,
    author      text not null,
    data        jsonb not null default '{}'::jsonb,
    updated_at  timestamptz not null default now(),
    primary key (ticket_id, author)
);

create table if not exists app_sessions (
    token_hash  text primary key,
    kind        text not null,          -- 'reviewer' or 'evaluator'
    ident       text not null,          -- reviewer name, or evaluators.id
    name        text not null,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null
);
