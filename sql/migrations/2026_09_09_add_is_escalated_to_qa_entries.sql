-- Adds the "is_escalated" flag to qa_entries on an existing production
-- database. Safe to run more than once (idempotent). Run this once in the
-- Supabase SQL editor, then deploy the app code that uses it — the code
-- adds is_escalated to every row it upserts, so it must run AFTER this
-- migration or every save (not just escalated ones) will fail with a
-- missing-column error. Same pattern as the earlier is_test migration.
--
-- New installs don't need this file — sql/schema.sql already includes the
-- column for a fresh qa_entries table.

alter table qa_entries add column if not exists is_escalated boolean not null default false;
