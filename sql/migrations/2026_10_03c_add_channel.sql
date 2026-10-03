-- Adds a "Channel" tag to qa_entries, distinguishing the Intercom chat
-- audits logged so far from the Phone Support Ticket evaluations planned
-- for later (QA Log → Audit log → Channel filter; the field itself is set
-- per-audit on the QA Audit form). New installs don't need this —
-- sql/schema.sql already includes the column. Existing rows default to
-- "Chat", since every audit logged before this migration came from an
-- Intercom conversation.

alter table qa_entries add column if not exists channel text not null default 'Chat';
