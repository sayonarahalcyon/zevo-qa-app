-- Adds a "zomp_link" to calibration_scores, so each calibration participant
-- can paste the ZOMP link they checked (same as the "ZOMP Link" field on the
-- audit form, which is stored in qa_entries.zomp_link). New installs don't
-- need this: sql/schema.sql already includes the column.

alter table calibration_scores add column if not exists zomp_link text;
