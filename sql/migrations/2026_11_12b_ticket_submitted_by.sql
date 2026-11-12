-- Adds "ticket_submitted_by" to qa_entries: on a phone audit, which team
-- submitted the phone ticket for evaluation ("Sales" or "T1"). Required on the
-- phone audit form; chat audits leave it empty. New installs don't need this:
-- sql/schema.sql already includes the column.

alter table qa_entries add column if not exists ticket_submitted_by text;
