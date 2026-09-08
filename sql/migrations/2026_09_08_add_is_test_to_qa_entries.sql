-- Adds the "is_test" flag to qa_entries on an existing production database.
-- Safe to run more than once (idempotent). Run this once in the Supabase
-- SQL editor, then deploy the app code that uses it — the code adds
-- is_test to every row it upserts, so it must run AFTER this migration or
-- every save (not just test ones) will fail with a missing-column error.
--
-- New installs don't need this file — sql/schema.sql already includes the
-- column for a fresh qa_entries table.

alter table qa_entries add column if not exists is_test boolean not null default false;
