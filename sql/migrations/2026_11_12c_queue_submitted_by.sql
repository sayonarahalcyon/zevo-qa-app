-- Adds "ticket_submitted_by" to phone_queue: Weng can set Sales or T1 when
-- loading a batch of phone tickets. It pre-fills the phone audit form, where
-- whoever audits the ticket can still change it (qa_entries.ticket_submitted_by
-- holds the final answer). New installs don't need this: sql/schema.sql has it.

alter table phone_queue add column if not exists ticket_submitted_by text;
