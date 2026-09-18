-- Adds the "is_test" flag to disputes on an existing production database.
-- Mirrors the qa_entries is_test migration (2026_09_08_add_is_test_to_qa_entries.sql).
-- New installs don't need this -- sql/schema.sql already includes the
-- column for fresh setups.
--
-- Run this once in the Supabase SQL editor, then flag any existing test
-- rows so they're excluded from the Questions & Disputes open/resolved
-- counts, e.g.:
--   update disputes set is_test = true where id in ('...', '...');

alter table disputes add column if not exists is_test boolean not null default false;
