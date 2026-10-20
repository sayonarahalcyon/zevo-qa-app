-- Adds a "recording_link" to qa_entries, used by phone audits (Channel =
-- Phone) to keep the link to the call recording the audit was scored from.
-- Chat audits leave it empty. New installs don't need this: sql/schema.sql
-- already includes the column.

alter table qa_entries add column if not exists recording_link text;
