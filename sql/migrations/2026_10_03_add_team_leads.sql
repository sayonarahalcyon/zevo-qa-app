-- Adds the Team Lead Dashboard: a new team_leads table (one row per team
-- lead, with its own resettable bcrypt password, same pattern as
-- agents.password_hash) plus a team_lead_id column on agents recording which
-- team lead each agent is assigned to.
--
-- Run this once in the Supabase SQL editor if `agents` was created before
-- this date (new installs don't need it — sql/schema.sql already includes
-- the table and column).
--
-- password_hash is a bcrypt hash, set via the QA Log page's "Manage team
-- leads" panel (reviewer-only) or changed by the team lead themselves on
-- their dashboard. NULL means no password has been set yet — that team lead
-- can't sign in until a reviewer sets one.
--
-- team_lead_id on agents is the source of truth for which agents show up on
-- a given team lead's rollup — set from QA Log → Manage agents → "Assign a
-- team lead".

create table if not exists team_leads (
    id             text primary key,
    name           text not null,
    password_hash  text,
    updated_at     timestamptz not null default now()
);

insert into team_leads (id, name) values
    ('aga-luague', 'Aga Luague'),
    ('elizabeth-alerta', 'Elizabeth Alerta'),
    ('stella-albacite', 'Stella Albacite')
on conflict (id) do nothing;

alter table agents add column if not exists team_lead_id text references team_leads(id);

create index if not exists idx_agents_team_lead on agents (team_lead_id);
