-- Adds per-agent dashboard passwords, for the new "My Dashboard" page where
-- each agent signs in to see only their own QA evaluations.
--
-- Run this once in the Supabase SQL editor if `agents` was created before
-- this date (new installs don't need it — sql/schema.sql already includes
-- the column).
--
-- password_hash is a bcrypt hash, set via the QA Log page's "Manage agents"
-- panel (reviewer-only) or changed by the agent themselves on My Dashboard.
-- NULL means no password has been set yet — that agent can't sign in until
-- a reviewer sets one.

alter table agents add column if not exists password_hash text;
